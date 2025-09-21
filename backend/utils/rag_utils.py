import os
import re
import logging
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
