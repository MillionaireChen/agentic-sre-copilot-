"""Embedding via Qwen3-Embedding-0.6B (sentence-transformers), lazy-loaded."""
from functools import lru_cache

from backend.config import settings


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embedding_model, trust_remote_code=True)


def embed_texts(texts: list[str], is_query: bool = False) -> list[list[float]]:
    prompt_name = "query" if is_query else None
    vecs = _model().encode(texts, prompt_name=prompt_name, normalize_embeddings=True)
    return [v.tolist() for v in vecs]
