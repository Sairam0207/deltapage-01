from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import requests
import re
import time
import random
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from io import BytesIO
from typing import List, Dict, Set

# Load environment variables from .env file
load_dotenv()

# In-memory stores
all_products_with_images = {}
product_image_cache = {}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API key for Firecrawl
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

# Common words to ignore in product names
IGNORE_WORDS: Set[str] = {
    "qty", "quantity", "date", "updated", "price", "total", "amount", "cost",
    "each", "unit", "units", "subtotal", "tax", "shipping", "discount",
    "description", "item", "items", "product", "products", "model", "sku",
    "code", "number", "id", "size", "color", "weight", "dimensions", "page",
    "of", "the", "and", "or", "for", "with", "without", "in", "on", "at",
    "invoice", "receipt", "order", "summary", "contact", "phone", "email",
    "address", "subtotal", "tax", "total", "balance", "due"
}

# New patterns to explicitly exclude non-product lines
NON_PRODUCT_PATTERNS: List[re.Pattern] = [
    re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$'),  # Date format like 17-09-2025
    re.compile(r'^\d{4}-\d{2}-\d{2}'),  # ISO date format
    re.compile(r'^(date|updated)\s*[:]?\s*.*', re.IGNORECASE),  # Lines starting with 'date' or 'updated'
    re.compile(r'^\s*page\s+\d+\s+of\s+\d+\s*$', re.IGNORECASE),  # Page numbers
    re.compile(r'^(invoice|receipt|order)\s+number', re.IGNORECASE),  # Document numbers
    re.compile(r'^(subtotal|tax|total|amount)\s*[:]?\s*[\$\₹€]?\s*\d', re.IGNORECASE),  # Summary lines
    re.compile(r'^\s*terms\s+and\s+conditions', re.IGNORECASE),
]

# Local fallback product data
def get_local_product_data():
    return [
        {"product_name": "Intel Core i9-13900K Processor", "image_url": "https://m.media-amazon.com/images/I/61M6c2+VnTL._AC_SL1500_.jpg"},
        {"product_name": "AMD Ryzen 9 7950X CPU", "image_url": "https://m.media-amazon.com/images/I/61tH6qX-XcL._AC_SL1500_.jpg"},
        {"product_name": "NVIDIA RTX 4090 24GB Graphics Card", "image_url": "https://m.media-amazon.com/images/I/81x0K9l6m3L._AC_SL1500_.jpg"},
        {"product_name": "Corsair Vengeance 16GB DDR5 RAM", "image_url": "https://m.media-amazon.com/images/I/61N+V3v-7uL._AC_SL1500_.jpg"},
        {"product_name": "ASUS ROG STRIX Z790-E Motherboard", "image_url": "https://m.media-amazon.com/images/I/71YvR51xPUL._AC_SL1500_.jpg"},
    ]

@app.on_event("startup")
async def startup_event():
    """Populates the in-memory store with local data on startup."""
    global all_products_with_images
    local_data = get_local_product_data()
    all_products_with_images = {p["product_name"]: p["image_url"] for p in local_data}
    print("Backend started and populated with local data.")

def is_likely_product(line: str) -> bool:
    """
    Determines if a given line of text is a likely product name,
    based on a series of robust heuristics.
    """
    line = line.strip()

    # 1. Reject based on general characteristics
    if len(line) < 10 or len(line) > 100:  # Too short or too long
        return False

    words = line.split()
    if len(words) < 2 or len(words) > 10:  # Not a phrase
        return False

    # 2. Reject based on explicit non-product patterns (dates, headers, etc.)
    for pattern in NON_PRODUCT_PATTERNS:
        if pattern.search(line):
            return False

    # 3. Reject if it contains common non-product keywords
    if any(word in line.lower().split() for word in IGNORE_WORDS):
        # A more nuanced check to avoid false positives for product names containing these words
        if not (re.search(r'\b(core|gpu|ram|motherboard|cpu)\b', line.lower()) and
                any(w in line.lower() for w in ['size', 'color', 'model'])):
            return False

    # 4. Accept if it matches strong product-name heuristics
    has_brand = any(word[0].isupper() and word.lower() not in IGNORE_WORDS for word in words[:3])  # First few words are capitalized (e.g., brands)
    has_specs = re.search(r'\d+[A-Za-z]+|\d+\.\d+', line)  # Contains numbers with possible units (e.g., 16GB, 2TB)

    # Require at least one of these strong indicators
    return has_brand and has_specs

def extract_product_names(text: str) -> List[str]:
    """
    Extract complete product names from text using a refined, rule-based approach.
    """
    products: Set[str] = set()
    lines = text.split('\n')

    # Strategy 1: Iterate through lines and apply the comprehensive filter
    for i, line in enumerate(lines):
        if is_likely_product(line):
            products.add(line)

    # Strategy 2: Look for product patterns in context
    # This acts as a fallback or a second pass to catch products missed by the line-by-line check.
    product_patterns = [
        r'([A-Z][a-z]+\s+[A-Za-z]+\s+[A-Za-z]?\d+[-+]?[A-Za-z0-9]*)',  # e.g., Intel Core i9-13900K
        r'([A-Z]+\s+\d+[A-Z]*\s*[A-Za-z]*)',  # e.g., RTX 4090, 16GB DDR4
        r'([A-Z][a-z]+\s+[A-Z][a-z]+\s+\d+[A-Za-z]*)',  # e.g., Corsair Vengeance 16GB
    ]

    for pattern in product_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            cleaned_match = clean_product_name(match.strip())
            if is_likely_product(cleaned_match):  # Filter matches with the same logic
                products.add(cleaned_match)

    # Strategy 3: Look near price indicators
    for i, line in enumerate(lines):
        if re.search(r'[\$\₹€]\s*\d+[\.\,]?\d*', line):
            for j in range(max(0, i - 3), i):
                candidate = lines[j].strip()
                if is_likely_product(candidate):
                    products.add(candidate)

    # Final cleaning and sorting
    filtered_products = [clean_product_name(p) for p in products]
    unique_products = list(dict.fromkeys(filtered_products))  # Preserve order while removing duplicates
    unique_products.sort(key=len, reverse=True)

    return unique_products[:6]

def clean_product_name(name: str) -> str:
    """
    Clean and standardize product names for better search results.
    """
    # Remove common non-product prefixes/suffixes
    patterns_to_remove = [
        r'^\d+[\.\)\-\s]*',  # Remove leading numbers/dots/dashes
        r'[\s\.\-]+$',  # Remove trailing whitespace, dots, or dashes
        r'\b(qty|quantity|each|unit|price|total)\b.*$',  # Quantity/price info
    ]
    
    cleaned = name
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Specific fix to remove trailing dots "..." or "........"
    cleaned = re.sub(r'\s*\.{3,}\s*$', '', cleaned)
    
    # Standardize spacing and formatting
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'\s*-\s*', '-', cleaned)  # Standardize hyphens
    cleaned = re.sub(r'\s*\/\s*', '/', cleaned)  # Standardize slashes
    
    return cleaned

def extract_image_from_response(data: dict) -> str:
    """
    Extract image URL from Firecrawl API response based on different possible structures.
    """
    # Structure 1: Direct imageUrl in results
    if data.get("results") and isinstance(data["results"], list):
        for result in data["results"]:
            if result.get("imageUrl"):
                return result["imageUrl"]

    # Structure 2: Nested data with images
    if data.get("data") and data["data"].get("images"):
        images = data["data"]["images"]
        if images and isinstance(images, list) and len(images) > 0:
            return images[0].get("url", "")

    # Structure 3: Direct images array
    if data.get("images") and isinstance(data["images"], list) and len(data["images"]) > 0:
        return data["images"][0].get("url", "")

    # Structure 4: Results with image property
    if data.get("results") and isinstance(data["results"], list):
        for result in data["results"]:
            if result.get("image"):
                return result["image"]

    # Structure 5: Try to find any image URL in the response
    # Convert the entire response to string and search for image URLs
    response_str = str(data)
    image_urls = re.findall(r'"imageUrl"\s*:\s*"([^"]+)"', response_str)
    if image_urls:
        return image_urls[0]

    image_urls = re.findall(r'"image"\s*:\s*"([^"]+)"', response_str)
    if image_urls:
        return image_urls[0]

    image_urls = re.findall(r'"url"\s*:\s*"([^"]+)"', response_str)
    if image_urls:
        for url in image_urls:
            if url.startswith(('http://', 'https://')) and any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                return url

    return ""

def find_product_image_url(product_name: str) -> str:
    """Search for product images using the complete product name."""
    # Check cache first
    if product_name in product_image_cache:
        return product_image_cache[product_name]

    if not FIRECRAWL_API_KEY:
        print("Error: FIRECRAWL_API_KEY not set. Using placeholder.")
        return f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={product_name.replace(' ', '+')}"

    # Clean the product name for better search results
    clean_name = clean_product_name(product_name)

    # Use the complete product name in quotes for exact matching
    query = f'"{clean_name}" product'

    api_url = "https://api.firecrawl.dev/v2/search"
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query,
        "limit": 3,  # Get more results to find a good image
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=15)
        print(f"Firecrawl API status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"API Response received for: {clean_name}")

            # Extract image URL from the response based on the actual structure
            image_url = extract_image_from_response(data)

            if image_url and image_url.startswith(('http://', 'https://')):
                print(f"✅ Found image for {clean_name}: {image_url}")
                product_image_cache[product_name] = image_url
                return image_url
            else:
                print(f"❌ No valid image URL found in response for {clean_name}")

    except Exception as e:
        print(f"❌ Error searching for {clean_name}: {e}")

    # Fallback: Use placeholder with the full product name
    placeholder = f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={clean_name.replace(' ', '+')}"
    product_image_cache[product_name] = placeholder
    return placeholder

@app.get("/")
def root():
    return {"status": "Backend running 🚀"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a PDF/TXT, extract product names, fetch images."""
    global all_products_with_images
    content = await file.read()
    filename = file.filename

    if filename.endswith(".pdf"):
        try:
            # Process PDF in memory
            pdf_file = BytesIO(content)
            reader = PdfReader(pdf_file)
            text = "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read PDF: {e}")

    elif filename.endswith(".txt"):
        text = content.decode("utf-8", errors="ignore")
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Please upload PDF or TXT.")

    # Extract product names
    product_names = extract_product_names(text)
    print(f"Extracted product names: {product_names}")

    # Find images for products (limited to 3 to avoid rate limiting)
    processed_products = []
    for i, name in enumerate(product_names[:3]):  # Limit to 3 products
        # Add a small delay between API calls
        if i > 0:
            time.sleep(2)  # Increased delay to avoid rate limiting

        image_url = find_product_image_url(name)
        processed_products.append({
            "product_name": name,
            "image_url": image_url
        })

    # Update in-memory store
    all_products_with_images = {p["product_name"]: p["image_url"] for p in processed_products}

    return {
        "message": f"{filename} processed.",
        "products": processed_products,
        "total_products": len(processed_products)
    }

@app.get("/get_all_products")
def get_all_products():
    products_list = [{"product_name": n, "image_url": u} for n, u in all_products_with_images.items()]
    return {"products": products_list}

@app.get("/products")
def get_products():
    return get_all_products()

@app.post("/debug_search")
async def debug_search(product_name: str):
    """Debug endpoint to see what the Firecrawl API returns for a search."""
    if not FIRECRAWL_API_KEY:
        return {"error": "FIRECRAWL_API_KEY not set"}

    query = f'"{product_name}" product'

    api_url = "https://api.firecrawl.dev/v2/search"
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query,
        "limit": 3,
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=15)
        return {
            "status_code": response.status_code,
            "response": response.json() if response.status_code == 200 else response.text
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)