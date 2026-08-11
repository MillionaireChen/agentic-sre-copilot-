"""Runbook semantic search tool (READ, no approval required)."""
from backend.db.session import SessionLocal
from backend.db.models import RunbookChunk
from backend.rag.embeddings import embed_texts


def search_runbooks(query: str, top_k: int = 5) -> dict:
    """Semantic search over ingested runbooks. Returns top_k chunks."""
    qvec = embed_texts([query], is_query=True)[0]
    with SessionLocal() as db:
        rows = (db.query(
                    RunbookChunk,
                    RunbookChunk.embedding.cosine_distance(qvec).label("dist"))
                .order_by("dist").limit(top_k).all())
        return {"query": query, "results": [{
            "document": c.document_name,
            "section": c.section,
            "content": c.content,
            "similarity": round(1 - dist, 3),
        } for c, dist in rows]}
