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
from utils.rag_utils import fetch_product_image, query_rag, generate_product_description, process_document, search_product_page
import json
from redis import Redis
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
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Redis connected")
except Exception:
    redis_client = None
    logger.warning("Redis not available; using in-memory session store")

inmemory_sessions: Dict[str, list] = {}

def _token_trim_history(messages: list, max_messages: int = 20) -> list:
    # Simple heuristic: keep last N messages; can be replaced with token-based trim
    return messages[-max_messages:]

def load_session_history(session_id: str) -> list:
    if not session_id:
        return []
    try:
        if redis_client:
            data = redis_client.get(f"chat:{session_id}")
            return json.loads(data) if data else []
    except Exception as e:
        logger.error(f"Redis load error: {e}")
    return inmemory_sessions.get(session_id, [])

def save_session_history(session_id: str, messages: list) -> None:
    if not session_id:
        return
    trimmed = _token_trim_history(messages)
    try:
        if redis_client:
            redis_client.set(f"chat:{session_id}", json.dumps(trimmed), ex=60*60*2)
            return
    except Exception as e:
        logger.error(f"Redis save error: {e}")
    inmemory_sessions[session_id] = trimmed
IGNORE_WORDS: Set[str] = {
    "qty", "quantity", "date", "updated", "price", "total", "amount", "cost",
    "each", "unit", "units", "subtotal", "tax", "shipping", "discount",
    "description", "item", "items", "product", "products", "model", "sku",
    "code", "number", "id", "size", "color", "weight", "dimensions", "page",
    "of", "the", "and", "or", "for", "with", "without", "in", "on", "at",
    "invoice", "receipt", "order", "summary", "contact", "phone", "email",
    "address", "subtotal", "tax", "total", "balance", "due",
    # Common catalog headings (skip as product names)
    "processors", "processor", "motherboards", "motherboard", "ram", "memory",
    "storage", "ssd", "hdd", "graphics", "cards", "graphicscards", "gpu", "gpus",
    "power", "supply", "units", "psu", "cabinets", "cabinet", "case", "cases"
}
NON_PRODUCT_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$'),
    re.compile(r'^\d{4}-\d{2}-\d{2}'),
    re.compile(r'^(date|updated)\s*[:]?:\s*.*', re.IGNORECASE),
    re.compile(r'^\s*page\s+\d+\s+of\s+\d+\s*$', re.IGNORECASE),
    re.compile(r'^(invoice|receipt|order)\s+number', re.IGNORECASE),
    re.compile(r'^(subtotal|tax|total|amount)\s*[:]?:\s*[\$\₹€]?\s*\d', re.IGNORECASE),
    re.compile(r'^\s*terms\s+and\s+conditions', re.IGNORECASE),
    # Section/category headings like "1. Processors"
    re.compile(r'^\s*\d+\.\s+[A-Za-z][A-Za-z\s()/&+-]*$', re.IGNORECASE),
    # Standalone category names such as "Processors", "Storage (SSD/HDD)", "PSU"
    re.compile(r'^\s*(processors?|motherboards?|ram|memory|storage(\s*\(.+\))?|graphics\s*cards?|psu|power\s*supply\s*units?|cabinets?|cases?)\s*$', re.IGNORECASE),
]
all_products_with_images = {}
product_image_cache = {}

def is_likely_product(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    # Be more permissive so simple names like "keyboard"/"mouse" are kept
    if len(line) > 120:
        return False
    words = line.split()
    if len(words) > 8:
        return False
    for pattern in NON_PRODUCT_PATTERNS:
        if pattern.search(line):
            return False
    tokens_lower = [w.lower() for w in words]
    if len(words) == 1 and tokens_lower[0] in IGNORE_WORDS:
        return False
    if all(w in IGNORE_WORDS for w in tokens_lower):
        return False
    has_alpha = any(re.search(r'[a-zA-Z]', w) for w in words)
    return has_alpha

def extract_product_names(text: str) -> List[str]:
    products: Set[str] = set()
    lines = text.split('\n')
    # 1) Primary permissive line-based candidates
    for line in lines:
        candidate = clean_product_name(line)
        if is_likely_product(candidate):
            products.add(candidate)
    # 2) Pattern-based (model numbers etc.)
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
    # 3) Price proximity
    for i, line in enumerate(lines):
        if re.search(r'[\$\₹€]\s*\d+[\.\,]?\d*', line):
            for j in range(max(0, i - 2), i + 1):
                candidate = clean_product_name(lines[j].strip())
                if is_likely_product(candidate):
                    products.add(candidate)
    # 4) Fallback: simple nouns (1-2 words) not entirely ignored
    if len(products) < 4:
        for line in lines:
            t = clean_product_name(line)
            if not t:
                continue
            words = t.split()
            if 1 <= len(words) <= 2:
                lows = [w.lower() for w in words]
                if any(re.search(r'[a-zA-Z]', w) for w in words) and not all(w in IGNORE_WORDS for w in lows):
                    products.add(t)
            if len(products) >= 10:
                break
    filtered_products = [clean_product_name(p) for p in products if p]
    unique_products = list(dict.fromkeys(filtered_products))
    # Hard cap to avoid many downstream API calls
    return unique_products[:10]

def clean_product_name(name: str) -> str:
    patterns_to_remove = [
        r'^\d+[\.\)\-\s]*',
        r'[\s\.\-]+$',
        r'\b(qty|quantity|each|unit|price|total)\b.*$',
        r'^[-•\s]+',
        r'\s*\([^)]*\)\s*$',
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
    # Store document chunks and embeddings for RAG
    try:
        filetype = "pdf" if filename.endswith(".pdf") else "txt"
        process_document(content, filetype=filetype)
    except Exception as e:
        logger.error(f"Error processing document for RAG: {e}")
    product_names = extract_product_names(text)
    logger.info(f"Extracted product names: {product_names}")
    processed_products = []
    max_results = 6
    min_results = 4
    for i, name in enumerate(product_names):
        if len(processed_products) >= max_results:
            break
        if i > 0:
            time.sleep(1)
        image_url = find_product_image_url(name)
        # Skip placeholders or clearly invalid URLs to reduce noise
        if not image_url or "placehold.co" in image_url:
            continue
        # Persist to Supabase if not already present
        try:
            existing = check_featured_product_exists(name)
            if not existing:
                description = generate_product_description(name)
                save_featured_product(name, image_url, description)
        except Exception as e:
            logger.error(f"Failed to save uploaded product to Supabase ({name}): {e}")
        processed_products.append({"product_name": name, "image_url": image_url})
    # Top-up with safe fallbacks to ensure at least 4 tiles
    if len(processed_products) < min_results:
        fallback_names = [
            "Intel Core i7 processor",
            "NVIDIA RTX 4080 graphics card",
            "Samsung 1TB SSD",
            "Corsair 32GB DDR4 RAM",
            "ASUS ROG motherboard",
            "Cooler Master CPU cooler",
        ]
        existing = {p["product_name"].lower() for p in processed_products}
        for name in fallback_names:
            if len(processed_products) >= min_results:
                break
            if name.lower() in existing:
                continue
            image_url = find_product_image_url(name)
            if not image_url or "placehold.co" in image_url:
                continue
            try:
                existing2 = check_featured_product_exists(name)
                if not existing2:
                    description2 = generate_product_description(name)
                    save_featured_product(name, image_url, description2)
            except Exception as e:
                logger.error(f"Failed to save fallback product to Supabase ({name}): {e}")
            processed_products.append({"product_name": name, "image_url": image_url})
    all_products_with_images = {p["product_name"]: p["image_url"] for p in processed_products}
    return {"message": f"{filename} processed.", "products": processed_products, "total_products": len(processed_products)}



@app.get("/products")
def get_products():
    # Fetch products from Supabase instead of local memory
    products = fetch_products()
    return {"products": products}


@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    query = body.get("query", "")
    session_id = body.get("sessionId", "")
    # Load persisted history, append new user message
    history = load_session_history(session_id)
    history.append({"role": "user", "content": query})
    # Get answer using trimmed history
    answer = query_rag(query, history)
    # Append assistant message and save
    history.append({"role": "assistant", "content": answer})
    save_session_history(session_id, history)
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

@app.get("/uploaded-products")
async def get_uploaded_products():
    """Return last uploaded document's extracted products with image URLs."""
    global all_products_with_images
    products = [{"product_name": name, "image_url": url} for name, url in all_products_with_images.items()]
    return {"products": products, "count": len(products)}

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

@app.get("/product-link")
async def get_product_link(product_name: str):
    """Return a best-guess product page URL for the given product name using Firecrawl.

    Query param: product_name
    Response: { "product_name": str, "product_url": str | None }
    """
    try:
        url = search_product_page(product_name)
        return {"product_name": product_name, "product_url": url}
    except Exception as e:
        logger.error(f"Error in /product-link for '{product_name}': {e}")
        return {"product_name": product_name, "product_url": None, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)