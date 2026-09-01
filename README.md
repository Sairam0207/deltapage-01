# DeltaPage

Upload a product catalogue as a PDF, get a working storefront out the other end.

The backend parses the document, pulls product names out of unstructured text,
generates a description for each one with Gemini, finds a real product image by
searching the web, and persists the result. A separate chat endpoint answers
questions about the uploaded document over a vector search of its own chunks.

Built with one collaborator over ~17 commits on a PR-based branch workflow.

## What it actually does

```
PDF upload
   -> PyPDFLoader extracts text
   -> adaptive chunking (chunk size scales with document length)
   -> embed each chunk (all-MiniLM-L6-v2) -> store in Supabase
   -> heuristics pull candidate product names out of the raw lines
   -> per product: Gemini writes a description, Firecrawl search finds an image
   -> storefront renders from Supabase

chat query
   -> embed query -> vector search over the stored chunks
   -> Gemini answers from retrieved context + trimmed session history (Redis)
```

## Layout

```
backend/
  src/main.py            FastAPI app: /upload, /chat, /products,
                         /featured-products, /product-link
  utils/rag_utils.py     chunking, embedding, retrieval, description
                         generation, image search
  utils/supabase_utils.py  persistence
frontend/
  admin-upload-app/      React + Vite. Upload a catalogue, watch it process.
  user-ecommerce-app/    React + Vite. The generated storefront.
```

Roughly 1,000 lines of Python across the backend, two Vite apps on the front.

## Three decisions worth pointing at

**Chunk size adapts to document length** (`_choose_chunk_params`). Fixed chunk
sizes behave badly across a corpus where one upload is 2 pages and the next is
200. This targets ~120 chunks per document and clamps chunk size to 800–3000
chars, with overlap at 15% capped at 400, so a short document doesn't get
shredded into fragments and a long one doesn't collapse into a handful of
enormous chunks.

**Retrieval depth depends on the question.** `query_rag` pulls k=12 instead of
k=8 when the query looks like planning or comparison ("build", "budget",
"best", "vs"), because those questions need to see several products at once to
answer, while a lookup only needs the one chunk that mentions it.

**Image search validates before it accepts.** `fetch_product_image` doesn't
trust the first search result — `_is_real_image` and `_is_reachable_html`
check that a URL actually resolves to an image before it reaches the
storefront, with a `placehold.co` fallback when nothing does. Product pages
full of broken image icons was the failure mode this exists to prevent.

## A design choice I'd now argue with

When vector search returns nothing relevant, `query_rag` deliberately falls
back to answering from the model's general knowledge with a stated caveat,
rather than refusing. For a shopping assistant that is defensible — a user
asking "what's a good budget GPU" is better served by a caveated answer than a
shrug.

It is also the opposite of what I built in
[adaptive-retrieval-agent](https://github.com/Sairam0207/adaptive-retrieval-agent),
where the agent abstains instead of answering ungrounded. Which behaviour is
correct depends entirely on what happens downstream when the system is wrong,
and that is a product decision, not a technical one.

## Running it

Backend:

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt
uvicorn src.main:app --reload
```

Requires a `.env` in `backend/` with:

```
GOOGLE_API_KEY=      # Gemini
SUPABASE_URL=
SUPABASE_KEY=
FIRECRAWL_API_KEY=   # image/product search; degrades to placeholders without it
REDIS_URL=redis://localhost:6379/0
```

Frontend (either app):

```bash
cd frontend/user-ecommerce-app
npm install
npm run dev
```

## Known rough edges

Kept honest rather than quietly cleaned up:

- `process_document` writes every upload to a single hardcoded `temp.pdf`
  before parsing. Two concurrent uploads would race over that file. It wants a
  `tempfile.NamedTemporaryFile`.
- `main.py` is 509 lines and carries several `/test-*` and `/debug_search`
  endpoints left over from development. They should be behind a flag or gone.
- Product-name extraction is regex and heuristics over raw PDF lines. It works
  on catalogues shaped the way the ones I tested were shaped, and there is no
  eval measuring how often it is wrong.
- No test suite.
