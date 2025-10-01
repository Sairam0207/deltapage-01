import os
import logging
from supabase import create_client, Client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def init_supabase():
    """Initialize Supabase client (tables/functions must already exist)."""
    logger.info("✅ Supabase client initialized.")
    return supabase

def save_embedding(content: str, embedding: list):
    try:
        supabase.table("documents").insert({"content": content, "embedding": embedding}).execute()
    except Exception as e:
        logger.error(f"Supabase save embedding error: {e}")

def fetch_similar(query_vec: list, k=3):
    try:
        response = supabase.rpc("match_documents", {"query_embedding": query_vec, "match_count": k}).execute()
        return response.data
    except Exception as e:
        logger.error(f"Supabase fetch similar error: {e}")
        return []

def save_product(name: str, description: str = None, price: float = None, image_url: str = None, product_link: str = None):
    """Save product details to Supabase, including a link to the product page."""
    try:
        data_to_insert = {
            "name": name, 
            "description": description, 
            "price": price, 
            "image_url": image_url, 
            "product_link": product_link  # Added new field
        }
        supabase.table("products").insert(data_to_insert).execute()
    except Exception as e:
        logger.error(f"Supabase save product error: {e}")

def save_featured_product(name: str, image_url: str, description: str = None):
    """Save a featured product with its image URL and description to Supabase"""
    try:
        data_to_insert = {
            "name": name, 
            "image_url": image_url,
            "description": description or f"Featured product: {name}"
        }
        supabase.table("products").insert(data_to_insert).execute()
        logger.info(f"Saved featured product to Supabase: {name}")
    except Exception as e:
        logger.error(f"Supabase save featured product error: {e}")

def fetch_featured_products():
    """Fetch featured products from Supabase (all products with image_url)"""
    try:
        response = supabase.table("products").select("*").not_.is_("image_url", "null").order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        logger.error(f"Supabase fetch featured products error: {e}")
        return []

def check_featured_product_exists(name: str):
    """Check if a featured product already exists in Supabase"""
    try:
        response = supabase.table("products").select("id, image_url, description").eq("name", name).not_.is_("image_url", "null").execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Supabase check featured product error: {e}")
        return None

# Deduplicated: keep a single definition of save_product and fetch_products
def fetch_products():
    try:
        response = supabase.table("products").select("*").order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        logger.error(f"Supabase fetch products error: {e}")
        return []
