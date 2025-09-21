import os
import re
import google.generativeai as genai
import requests
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from supabase_utils import save_embedding, fetch_similar, save_product, supabase

# Load environment variables
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Embedding model (SentenceTransformers)
embedder = SentenceTransformer("all-MiniLM-L6-v2")

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

# ---------------- IMAGE FETCHER ----------------
def fetch_product_image(product_name: str):
    """Fetch image URL for a product using Firecrawl (or fallback)."""
    try:
        url = "https://api.firecrawl.dev/v1/search"
        headers = {"Authorization": f"Bearer {FIRECRAWL_API_KEY}"}
        params = {"q": f"{product_name} product image"}
        
        print(f"Searching for image for: {product_name}")
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        print(f"Firecrawl API response status code: {response.status_code}")
        
        if response.ok:
            results = response.json().get("results", [])
            if results and "image" in results[0]:
                image_url = results[0]["image"]
                print(f"Found image URL: {image_url}")
                return image_url

        print(f"No valid image found. Using fallback placeholder for {product_name}.")
        return f"https://via.placeholder.com/300x200.png?text={product_name}"
    except Exception as e:
        print(f"Image fetch error: {e}")
        return f"https://via.placeholder.com/300x200.png?text={product_name}"


# ---------------- DOCUMENT PROCESSOR ----------------
def process_document(content, filetype="pdf"):
    """Extract, split, embed, and also extract products -> Supabase"""
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
        vector = embedder.encode([text_chunk])[0].tolist()
        save_embedding(text_chunk, vector)

    # Extract products from the document text
    product_lines = re.findall(r"(?:Product|Item|Name)[:\-]?\s*(.+)", full_text, re.IGNORECASE)
    if not product_lines:
        # fallback: try to extract capitalized words
        product_lines = re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", full_text)

    # Save products with images
    # The save_product function is now correctly called from supabase_utils
    for product in set(product_lines):
        image_url = fetch_product_image(product.strip())
        save_product(name=product.strip(), image_url=image_url)

    return "✅ Document processed, products saved, and embeddings stored in Supabase."


# ---------------- QUERY PIPELINE ----------------
def query_rag(query: str):
    """Retrieve relevant docs from Supabase, then ask Gemini"""
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
