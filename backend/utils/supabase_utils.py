import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def init_supabase():
    """Initialize Supabase client (tables/functions must already exist)."""
    print("✅ Supabase client initialized.")
    return supabase


# ---------------- Embeddings ---------------- #

def save_embedding(content: str, embedding: list):
    """Save a chunk embedding into Supabase documents table."""
    supabase.table("documents").insert({
        "content": content,
        "embedding": embedding
    }).execute()


def fetch_similar(query_vec: list, k=3):
    """Fetch top-k most similar docs using Supabase pgvector"""
    response = supabase.rpc("match_documents", {
        "query_embedding": query_vec,
        "match_count": k
    }).execute()
    return response.data


# ---------------- Products ---------------- #

def save_product(name: str, description: str = None, price: float = None, image_url: str = None):
    """Save a product into Supabase products table."""
    data_to_insert = {
        "name": name,
        "description": description,
        "price": price,
        "image_url": image_url
    }
    
    supabase.table("products").insert(data_to_insert).execute()


def fetch_products():
    """Fetch all products from Supabase products table."""
    response = supabase.table("products").select("*").order("created_at", desc=True).execute()
    return response.data
