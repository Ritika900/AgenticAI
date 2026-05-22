"""
rag_store.py
------------
RAG layer for bug triage.

Responsibilities:
  1. Embed bug descriptions using Azure OpenAI embeddings.
  2. Store / retrieve them in a persistent ChromaDB collection.
  3. Expose add_issue() and search_similar() for the agents layer.

Environment variables expected (loaded via dotenv in main.py):
  OPENAI_API_KEY      – Azure OpenAI key
  OPENAI_API_BASE     – Azure endpoint, e.g. https://<resource>.openai.azure.com
  OPENAI_API_VERSION  – e.g. 2025-04-01-preview
  EMBEDDING_DEPLOYMENT – Azure deployment name for embeddings
                         (defaults to "text-embedding-ada-002")
"""

import os
import chromadb
from openai import AzureOpenAI

# ── ChromaDB (persistent on disk so data survives restarts) ──────────────────
_CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
_chroma_client = chromadb.PersistentClient(path=_CHROMA_PATH)
_collection = _chroma_client.get_or_create_collection(
    name="bug_issues",
    metadata={"hnsw:space": "cosine"},   # cosine similarity for text
)

# ── Azure OpenAI client for embeddings ──────────────────────────────────────
_embed_client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    azure_endpoint=os.getenv("OPENAI_API_BASE", ""),
    api_version=os.getenv("OPENAI_API_VERSION", "2025-04-01-preview"),
)
_EMBED_DEPLOYMENT = os.getenv("EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")


# ── Internal helper ──────────────────────────────────────────────────────────
def _embed(text: str) -> list[float]:
    """Return the embedding vector for *text* using Azure OpenAI."""
    response = _embed_client.embeddings.create(
        input=text,
        model=_EMBED_DEPLOYMENT,
    )
    return response.data[0].embedding


# ── Public API ───────────────────────────────────────────────────────────────
def add_issue(issue_id: str, text: str, metadata: dict | None = None) -> None:
    """
    Embed *text* and upsert it into the ChromaDB collection.

    Args:
        issue_id:  Unique identifier (e.g. GitHub issue number or incident ID).
        text:      The bug description / document to index.
        metadata:  Optional key-value pairs stored alongside the embedding
                   (e.g. {"priority": 2, "source": "github"}).
    """
    embedding = _embed(text)
    _collection.upsert(          # upsert = add or update
        ids=[issue_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[metadata or {}],
    )


def search_similar(text: str, top_k: int = 3) -> list[dict]:
    """
    Return the *top_k* most similar issues to *text*.

    Returns a list of dicts, each with keys:
        id        – the issue_id that was stored
        document  – the original text
        metadata  – the metadata dict
        score     – cosine similarity (higher = more similar)
    """
    if _collection.count() == 0:
        return []

    embedding = _embed(text)
    results = _collection.query(
        query_embeddings=[embedding],
        n_results=min(top_k, _collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    ids        = results.get("ids", [[]])[0]
    documents  = results.get("documents", [[]])[0]
    metadatas  = results.get("metadatas", [[]])[0]
    distances  = results.get("distances", [[]])[0]

    for issue_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        hits.append({
            "id":       issue_id,
            "document": doc,
            "metadata": meta,
            "score":    round(1 - dist, 4),   # convert cosine distance → similarity
        })

    return hits


def delete_issue(issue_id: str) -> None:
    """Remove a single issue from the collection by its ID."""
    _collection.delete(ids=[issue_id])


def collection_size() -> int:
    """Return the number of documents currently indexed."""
    return _collection.count()