import os
import re
import logging
import time
import google.generativeai as genai
import requests
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from utils.supabase_utils import save_embedding, fetch_similar, save_product, supabase

logger = logging.getLogger(__name__)
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
embedder = SentenceTransformer("all-MiniLM-L6-v2")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

def generate_product_description(product_name: str) -> str:
    """Generate a product description using Gemini 2.5 Flash API"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-exp')
        
        prompt = f"""
        Generate a concise, informative product description for "{product_name}". 
        The description should be:
        - 2-3 sentences long
        - Highlight key features and benefits
        - Professional and marketing-friendly
        - Focus on technical specifications and performance
        - Suitable for an e-commerce website
        
        Product: {product_name}
        """
        
        response = model.generate_content(prompt)
        description = response.text.strip()
        
        logger.info(f"Generated description for {product_name} using Gemini 2.5 Flash: {description[:100]}...")
        return description
        
    except Exception as e:
        logger.error(f"Error generating description for {product_name}: {e}")
        return f"High-quality {product_name} with excellent performance and reliability."

def fetch_product_image(product_name: str) -> str:
    if not FIRECRAWL_API_KEY:
        logger.error("FIRECRAWL_API_KEY not set.")
        return f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={product_name.replace(' ', '+')}"

    max_retries = 3
    retry_delay = 10  # seconds
    
    for attempt in range(max_retries):
        try:
            url = "https://api.firecrawl.dev/v2/search"
            payload = {
                "query": f"direct image file url for product: {product_name}",
                "sources": ["images"],
                "categories": [],
                "limit": 1,
                "scrapeOptions": {
                    "onlyMainContent": True,
                    "maxAge": 172800000,
                    "parsers": ["pdf"],
                    "formats": []
                }
            }
            headers = {
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json"
            }
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            logger.info(f"Firecrawl response status: {response.status_code}")
            data = response.json()
            
            # Check for rate limiting
            if response.status_code == 429:
                error_msg = data.get("error", "Rate limit exceeded")
                logger.warning(f"Rate limit hit (attempt {attempt + 1}/{max_retries}): {error_msg}")
                if attempt < max_retries - 1:
                    logger.info(f"Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.error(f"Max retries reached for {product_name}, using fallback")
                    break
            
            logger.info(f"Firecrawl response data: {data}")

            # Try to extract the first image URL from the response
            images = data.get("data", {}).get("images", [])
            if images:
                # Extract the actual image URL, not the product page URL
                image_url = images[0].get("imageUrl")
                if image_url:
                    logger.info(f"Found image URL: {image_url}")
                    return image_url
                # Fallback to url if imageUrl is not available
                fallback_url = images[0].get("url")
                if fallback_url:
                    logger.info(f"Using fallback URL: {fallback_url}")
                    return fallback_url
            
            # If no images found, break and use fallback
            break

        except Exception as e:
            logger.error(f"Error fetching image for {product_name} (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error(f"Max retries reached for {product_name}, using fallback")

    return f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={product_name.replace(' ', '+')}"

def process_document(content, filetype="pdf"):
    if filetype == "pdf":
        with open("temp.pdf", "wb") as f:
            f.write(content)
        loader = PyPDFLoader("temp.pdf")
        docs = loader.load()
    elif filetype == "txt":
        text = content.decode("utf-8")
        docs = [Document(page_content=text)]
    else:
        raise ValueError("Unsupported file type")
    if not docs or all(len(doc.page_content.strip()) == 0 for doc in docs):
        return "⚠️ Document is empty or has no extractable text."
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)
    full_text = ""
    for chunk in chunks:
        text_chunk = chunk.page_content.strip()
        if not text_chunk:
            continue
        full_text += text_chunk + "\n"
        try:
            vector = embedder.encode([text_chunk])[0].tolist()
            save_embedding(text_chunk, vector)
        except Exception as e:
            logger.error(f"Embedding error: {e}")
    product_lines = re.findall(r"(?:Product|Item|Name)[:\-]?\s*(.+)", full_text, re.IGNORECASE)
    if not product_lines:
        product_lines = re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", full_text)
    for product in set(product_lines):
        try:
            image_url = fetch_product_image(product.strip())
            save_product(name=product.strip(), image_url=image_url)
        except Exception as e:
            logger.error(f"Product save error: {e}")
    return "✅ Document processed, products saved, and embeddings stored in Supabase."

def query_rag(query: str):
    try:
        query_vec = embedder.encode([query])[0].tolist()
        similar_docs = fetch_similar(query_vec, k=3) or []
        if not similar_docs:
            return "⚠️ No relevant documents found in Supabase."
        context = "\n".join([doc["content"] for doc in similar_docs if doc.get("content")])
        prompt = f"""You are a helpful assistant.
Use the context below to answer the question.
Context:
{context}
Question: {query}
Answer in detail using only the context above:"""
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        return response.text if response else "⚠️ Gemini returned no response."
    except Exception as e:
        logger.error(f"RAG query error: {e}")
        return "⚠️ Error processing your query."
