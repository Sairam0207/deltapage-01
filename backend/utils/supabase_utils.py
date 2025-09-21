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

def save_product(name: str, description: str = None, price: float = None, image_url: str = None):
    try:
        data_to_insert = {"name": name, "description": description, "price": price, "image_url": image_url}
        supabase.table("products").insert(data_to_insert).execute()
    except Exception as e:
        logger.error(f"Supabase save product error: {e}")

def fetch_products():
    try:
        response = supabase.table("products").select("*").order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        logger.error(f"Supabase fetch products error: {e}")
        return []
