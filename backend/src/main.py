from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
import re
import time
import logging
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from io import BytesIO
from typing import List, Dict, Set, Optional
from utils.rag_utils import fetch_product_image, query_rag, generate_product_description
from utils.supabase_utils import init_supabase, fetch_products, fetch_featured_products, save_featured_product, check_featured_product_exists, supabase

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
IGNORE_WORDS: Set[str] = {
    "qty", "quantity", "date", "updated", "price", "total", "amount", "cost",
    "each", "unit", "units", "subtotal", "tax", "shipping", "discount",
    "description", "item", "items", "product", "products", "model", "sku",
    "code", "number", "id", "size", "color", "weight", "dimensions", "page",
    "of", "the", "and", "or", "for", "with", "without", "in", "on", "at",
    "invoice", "receipt", "order", "summary", "contact", "phone", "email",
    "address", "subtotal", "tax", "total", "balance", "due"
}
NON_PRODUCT_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$'),
    re.compile(r'^\d{4}-\d{2}-\d{2}'),
    re.compile(r'^(date|updated)\s*[:]?\s*.*', re.IGNORECASE),
    re.compile(r'^\s*page\s+\d+\s+of\s+\d+\s*$', re.IGNORECASE),
    re.compile(r'^(invoice|receipt|order)\s+number', re.IGNORECASE),
    re.compile(r'^(subtotal|tax|total|amount)\s*[:]?\s*[\$\₹€]?\s*\d', re.IGNORECASE),
    re.compile(r'^\s*terms\s+and\s+conditions', re.IGNORECASE),
]
all_products_with_images = {}
product_image_cache = {}

def is_likely_product(line: str) -> bool:
    line = line.strip()
    if len(line) < 10 or len(line) > 100:
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 10:
        return False
    for pattern in NON_PRODUCT_PATTERNS:
        if pattern.search(line):
            return False
    if any(word in line.lower().split() for word in IGNORE_WORDS):
        if not (re.search(r'\b(core|gpu|ram|motherboard|cpu|ssd|hdd|monitor|keyboard|mouse)\b', line.lower()) and
                any(w in line.lower() for w in ['size', 'color', 'model', 'gb', 'tb', 'inch'])):
            return False
    has_brand = any(word[0].isupper() and word.lower() not in IGNORE_WORDS for word in words[:3])
    has_specs = re.search(r'\d+[A-Za-z]+|\d+\.\d+', line)
    return has_brand and has_specs

def extract_product_names(text: str) -> List[str]:
    products: Set[str] = set()
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if is_likely_product(line):
            products.add(line)
    product_patterns = [
        r'([A-Z][a-z]+\s+[A-Za-z]+\s+[A-Za-z]?\d+[-+]?[A-Za-z0-9]*)',
        r'([A-Z]+\s+\d+[A-Z]*\s*[A-Za-z]*)',
        r'([A-Z][a-z]+\s+[A-Z][a-z]+\s+\d+[A-Za-z]*)',
    ]
    for pattern in product_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            cleaned_match = clean_product_name(match.strip())
            if is_likely_product(cleaned_match):
                products.add(cleaned_match)
    for i, line in enumerate(lines):
        if re.search(r'[\$\₹€]\s*\d+[\.\,]?\d*', line):
            for j in range(max(0, i - 3), i):
                candidate = lines[j].strip()
                if is_likely_product(candidate):
                    products.add(candidate)
    filtered_products = [clean_product_name(p) for p in products]
    unique_products = list(dict.fromkeys(filtered_products))
    unique_products.sort(key=len, reverse=True)
    return unique_products[:6]

def clean_product_name(name: str) -> str:
    patterns_to_remove = [
        r'^\d+[\.\)\-\s]*',
        r'[\s\.\-]+$',
        r'\b(qty|quantity|each|unit|price|total)\b.*$',
    ]
    cleaned = name
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\.{3,}\s*$', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'\s*-\s*', '-', cleaned)
    cleaned = re.sub(r'\s*\/\s*', '/', cleaned)
    return cleaned

def find_product_image_url(product_name: str) -> str:
    """Wrapper to reuse fetch_product_image from rag_utils.py."""
    if product_name in product_image_cache:
        return product_image_cache[product_name]
    image_url = fetch_product_image(product_name)
    product_image_cache[product_name] = image_url
    return image_url

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    global all_products_with_images
    content = await file.read()
    filename = file.filename
    if filename.endswith(".pdf"):
        try:
            pdf_file = BytesIO(content)
            reader = PdfReader(pdf_file)
            text = "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read PDF: {e}")
    elif filename.endswith(".txt"):
        text = content.decode("utf-8", errors="ignore")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Please upload PDF or TXT.")
    product_names = extract_product_names(text)
    logger.info(f"Extracted product names: {product_names}")
    processed_products = []
    for i, name in enumerate(product_names[:3]):
        if i > 0:
            time.sleep(2)
        image_url = find_product_image_url(name)
        processed_products.append({"product_name": name, "image_url": image_url})
    all_products_with_images = {p["product_name"]: p["image_url"] for p in processed_products}
    return {"message": f"{filename} processed.", "products": processed_products, "total_products": len(processed_products)}



@app.get("/products")
def get_products():
    # Fetch products from Supabase instead of local memory
    products = fetch_products()
    return {"products": products}


@app.get("/chat")
async def chat(query: str):
    answer = query_rag(query)
    return {"answer": answer}

@app.get("/featured-products")
async def get_featured_products():
    """Fetch featured products from Supabase, only call Firecrawl for missing images"""

    # Predefined IT product names for consistent results
    product_names = [
        "Intel Core i7 processor",
        "NVIDIA RTX 4080 graphics card", 
        "Samsung 1TB SSD",
        "Corsair 32GB DDR4 RAM",
        "ASUS ROG motherboard",
        "Cooler Master CPU cooler"
    ]

    logger.info("Checking featured products in Supabase...")
    featured_products = []
    missing_products = []

    # First, check what's already in Supabase
    for name in product_names:
        existing_product = check_featured_product_exists(name)
        if existing_product:
            logger.info(f"Found existing product in Supabase: {name}")
            featured_products.append({
                "product_name": name,
                "image_url": existing_product["image_url"],
                "description": existing_product.get("description", f"High-quality {name} with excellent performance.")
            })
        else:
            logger.info(f"Product not found in Supabase, will fetch from Firecrawl: {name}")
            missing_products.append(name)

    # Only fetch missing products from Firecrawl
    if missing_products:
        logger.info(f"Fetching {len(missing_products)} missing products from Firecrawl...")
        
        if not FIRECRAWL_API_KEY:
            logger.error("FIRECRAWL_API_KEY not set, using fallback images")
            for name in missing_products:
                fallback_url = f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={name.replace(' ', '+')}"
                fallback_description = f"High-quality {name} with excellent performance and reliability."
                featured_products.append({
                    "product_name": name,
                    "image_url": fallback_url,
                    "description": fallback_description
                })
                # Still save to Supabase for future use
                save_featured_product(name, fallback_url, fallback_description)
        else:
            for i, name in enumerate(missing_products):
                try:
                    # Add 5 second delay between calls to avoid rate limiting
                    if i > 0:
                        logger.info(f"Waiting 5 seconds before fetching image for: {name}")
                        time.sleep(5)
                    
                    logger.info(f"Fetching image for: {name}")
                    image_url = fetch_product_image(name)
                    
                    logger.info(f"Generating description for: {name}")
                    description = generate_product_description(name)
                    
                    # Save to Supabase for future use
                    save_featured_product(name, image_url, description)
                    
                    featured_products.append({
                        "product_name": name,
                        "image_url": image_url,
                        "description": description
                    })
                    logger.info(f"Successfully fetched and saved image + description for {name}")
                    
                except Exception as e:
                    logger.error(f"Error fetching image for {name}: {e}")
                    # Add fallback image and description, save to Supabase
                    fallback_url = f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={name.replace(' ', '+')}"
                    fallback_description = f"High-quality {name} with excellent performance and reliability."
                    featured_products.append({
                        "product_name": name,
                        "image_url": fallback_url,
                        "description": fallback_description
                    })
                    save_featured_product(name, fallback_url, fallback_description)
    else:
        logger.info("All featured products found in Supabase, no Firecrawl calls needed!")
    
    logger.info(f"Returning {len(featured_products)} featured products")
    return {"products": featured_products, "from_supabase": True, "firecrawl_calls": len(missing_products)}

@app.get("/featured-products-readonly")
async def get_featured_products_readonly():
    """Fetch featured products from Supabase ONLY - no Firecrawl calls (for user-ecommerce-app)"""

    # Predefined IT product names for consistent results
    product_names = [
        "Intel Core i7 processor",
        "NVIDIA RTX 4080 graphics card", 
        "Samsung 1TB SSD",
        "Corsair 32GB DDR4 RAM",
        "ASUS ROG motherboard",
        "Cooler Master CPU cooler"
    ]

    logger.info("Fetching featured products from Supabase (readonly mode)...")
    featured_products = []

    # Only check what's already in Supabase - no Firecrawl calls
    for name in product_names:
        existing_product = check_featured_product_exists(name)
        if existing_product:
            logger.info(f"Found existing product in Supabase: {name}")
            featured_products.append({
                "product_name": name,
                "image_url": existing_product["image_url"],
                "description": existing_product.get("description", f"High-quality {name} with excellent performance.")
            })
        else:
            logger.info(f"Product not found in Supabase: {name} (no Firecrawl call in readonly mode)")
            # Add placeholder for missing products
            featured_products.append({
                "product_name": name,
                "image_url": f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={name.replace(' ', '+')}",
                "description": f"High-quality {name} with excellent performance and reliability."
            })
    
    logger.info(f"Returning {len(featured_products)} featured products (readonly mode)")
    return {"products": featured_products, "from_supabase": True, "firecrawl_calls": 0, "mode": "readonly"}

@app.post("/refresh-featured-products")
async def refresh_featured_products():
    """Force refresh featured products by clearing Supabase and re-fetching from Firecrawl"""
    logger.info("Refreshing featured products - this will fetch all images from Firecrawl again")
    
    # Clear existing featured products from Supabase (products with image_url)
    try:
        # Get all products with image_url first
        existing_products = supabase.table("products").select("id").not_.is_("image_url", "null").execute()
        if existing_products.data:
            # Delete them by ID
            for product in existing_products.data:
                supabase.table("products").delete().eq("id", product["id"]).execute()
            logger.info(f"Cleared {len(existing_products.data)} existing featured products from Supabase")
        else:
            logger.info("No existing featured products found in Supabase")
    except Exception as e:
        logger.error(f"Error clearing Supabase: {e}")
    
    # Now call the featured-products endpoint which will fetch fresh images
    return {"message": "Featured products cleared. Next call to /featured-products will fetch fresh images from Firecrawl."}

@app.get("/test-supabase-featured")
async def test_supabase_featured():
    """Test endpoint to check featured products in Supabase"""
    try:
        featured_products = fetch_featured_products()
        return {
            "message": f"Found {len(featured_products)} featured products in Supabase",
            "products": featured_products
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/test-supabase-schema")
async def test_supabase_schema():
    """Test endpoint to check Supabase products table schema"""
    try:
        # Try to get all products to see the schema
        response = supabase.table("products").select("*").limit(1).execute()
        return {
            "message": "Supabase connection successful",
            "sample_data": response.data,
            "schema_columns": list(response.data[0].keys()) if response.data else []
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/test-single-image")
async def test_single_image():
    """Test endpoint to fetch a single image URL"""
    if not FIRECRAWL_API_KEY:
        return {"error": "FIRECRAWL_API_KEY not set"}
    try:
        image_url = fetch_product_image("Intel Core i7 processor")
        return {"product_name": "Intel Core i7 processor", "image_url": image_url}
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug_search")
async def debug_search(product_name: str):
    if not FIRECRAWL_API_KEY:
        return {"error": "FIRECRAWL_API_KEY not set"}
    try:
        image_url = fetch_product_image(product_name)
        return {"product_name": product_name, "image_url": image_url}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
