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


def normalize_product_name(product_name: str) -> str:
    """Use Gemini to normalize/expand short product names into a precise query.

    The output is a single short line suitable for search, typically:
    "Brand Model Category" (e.g., "NZXT H510 Flow PC case").
    Falls back to the input on any error or empty response.
    """
    name = (product_name or "").strip()
    if not name:
        return product_name
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = (
            "You are normalizing a product name for image search. Given a short or generic name, "
            "return a precise, concise search string with brand and model if obvious. "
            "Avoid extra words, keep it under 8 words. Examples:\n"
            "keyboard -> mechanical keyboard product photo\n"
            "H510 Flow -> NZXT H510 Flow PC case product photo\n"
            "Trident Z 32GB -> G.Skill Trident Z 32GB DDR5 RAM product photo\n"
            f"Input: {name}\nOutput:"
        )
        response = model.generate_content(prompt)
        normalized = (response.text or "").strip()
        # Guardrails: keep it short and on one line
        normalized = normalized.splitlines()[0][:120]
        return normalized or name
    except Exception as e:
        logger.warning(f"Gemini normalize_product_name failed for '{name}': {e}")
        return name

def _looks_like_image_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    if any(bad in lower for bad in ["sprite", "placeholder", "logo", "icon", "thumbnail"]):
        return False
    if any(lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
        return True
    return False

def _is_real_image(url: str) -> bool:
    try:
        # Cheap HEAD check to ensure image content
        r = requests.head(url, timeout=8, allow_redirects=True)
        ctype = r.headers.get("Content-Type", "").lower()
        return r.status_code < 400 and ctype.startswith("image/")
    except Exception:
        return False

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
    
    normalized = normalize_product_name(product_name)
    query_candidates = [
        f"{normalized} product photo", 
        f"{normalized} official product image", 
        f"{normalized} box photo",
        product_name,
    ]
    preferred_domains = [
        "nzxt.com", "gskill.com", "intel.com", "nvidia.com", "samsung.com",
        "asus.com", "corsair.com", "coolermaster.com", "msi.com"
    ]

    for attempt in range(max_retries):
        try:
            url = "https://api.firecrawl.dev/v2/search"
            payload = {
                "query": f"Find direct image file URLs for: {query_candidates[attempt % len(query_candidates)]}",
                "sources": ["images"],
                "categories": [],
                "limit": 8,
                "scrapeOptions": {
                    "onlyMainContent": True,
                    "maxAge": 172800000,
                    "parsers": [],
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

            # Extract viable image URLs and score by domain preference
            images = data.get("data", {}).get("images", [])
            candidates = []
            for item in images:
                candidate = item.get("imageUrl") or item.get("url")
                if not candidate:
                    continue
                if not _looks_like_image_url(candidate):
                    continue
                score = 0
                for d in preferred_domains:
                    if d in candidate:
                        score += 5
                candidates.append((score, candidate))
            candidates.sort(reverse=True)
            selected = []
            for _, candidate_url in candidates:
                if _is_real_image(candidate_url):
                    selected.append(candidate_url)
                    if len(selected) >= 1:
                        logger.info(f"Selected product image: {selected[0]}")
                        return selected[0]
            
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

def _choose_chunk_params(total_chars: int) -> tuple[int, int]:
    """Pick chunk_size and chunk_overlap dynamically based on document size.

    - Aim for ~120 chunks for large docs; clamp sizes for stability.
    - chunk_overlap ≈ 15% of chunk_size, capped at 400.
    """
    target_chunks = 120
    chunk_size = max(800, min(3000, (total_chars + target_chunks - 1) // target_chunks))
    chunk_overlap = min(400, int(chunk_size * 0.15))
    return chunk_size, chunk_overlap

def fetch_product_image(product_name: str) -> str:
    if not FIRECRAWL_API_KEY:
        logger.error("FIRECRAWL_API_KEY not set.")
        return f"https://placehold.co/400x400/4A5568/FFFFFF/png?text={product_name.replace(' ', '+')}"

    try:
        url = "https://api.firecrawl.dev/v2/search"
        payload = {
            "query": f"give me public image url for the following products: {product_name}",
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
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        logger.info(f"Firecrawl response status: {response.status_code}")
        data = response.json()
        logger.info(f"Firecrawl response data: {data}")

        # Try to extract the first image URL from the response
        images = data.get("data", {}).get("images", [])
        if images:
            image_url = images[0].get("url")
            if image_url:
                logger.info(f"Found image URL: {image_url}")
                return image_url

    except Exception as e:
        logger.error(f"Error fetching image for {product_name}: {e}")


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

    # Dynamically size chunks so bigger files yield larger chunks (fewer, richer chunks)
    total_chars = sum(len((d.page_content or "").strip()) for d in docs)
    cs, co = _choose_chunk_params(total_chars)
    splitter = RecursiveCharacterTextSplitter(chunk_size=cs, chunk_overlap=co)
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

    # Avoid heavy image lookups here to reduce external API calls.
    # We only persist product names; the /upload endpoint will fetch images for up to 6 items.
    for product in set(product_lines):
        try:
            save_product(name=product.strip(), image_url=None)
    for product in set(product_lines):
        try:
            image_url = fetch_product_image(product.strip())
            save_product(name=product.strip(), image_url=image_url)
        except Exception as e:
            logger.error(f"Product save error: {e}")
    return "✅ Document processed, products saved, and embeddings stored in Supabase."

def query_rag(query: str, history: list | None = None):
    """Answer a user query using RAG with optional chat history.

    history: list of {"role": "user"|"assistant", "content": str}
    """
    try:
        query_vec = embedder.encode([query])[0].tolist()
        # Fetch a larger set of similar chunks to give the model more context to work with
        similar_docs = fetch_similar(query_vec, k=8) or []
        if not similar_docs:
            return "⚠️ No relevant documents found in Supabase."
        context = "\n".join([doc.get("content", "") for doc in similar_docs if doc.get("content")])

        history_text = ""
        if history:
            # Keep last 10 turns
            trimmed = history[-10:]
            lines = []
            for m in trimmed:
                role = m.get("role", "user")
                content = m.get("content", "").strip()
                if not content:
                    continue
                prefix = "User" if role == "user" else "Assistant"
                lines.append(f"{prefix}: {content}")
            history_text = "\n".join(lines)

        prompt = (
            "You are a helpful assistant. Base your answer strictly on the provided context from the uploaded document(s).\n"
            "- Combine and summarize facts from multiple context snippets as needed.\n"
            "- Do NOT invent facts that are not in the context.\n"
            "- If information is missing, clearly state what's missing and answer only with what the context supports.\n"
            "- For requests like recommendations or budgets, propose options using ONLY items/prices/specs present in the context; if insufficient, note the gaps and give the best-available partial answer.\n\n"
            f"Context:\n{context}\n\n"
            f"Chat history (most recent last):\n{history_text}\n\n"
            f"User: {query}\n"
            "Assistant:"
        )

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
