"""Semantic course search over catalog_course.embedding (pgvector, cosine distance).

Queries are embedded with the same Ollama model and plain-text format the loader used
for documents (pipelines/ingest/load_catalog.py), so query and document vectors match.
"""

from functools import lru_cache
from typing import Any

import httpx
from sqlalchemy import Engine, create_engine, text

from settings import get_settings

@lru_cache
def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)

def embed_query(query: str) -> list[float]:
    s = get_settings()
    resp = httpx.post(
        f"{s.ollama_host}/api/embed",
        json={"model": s.embedding_model, "input": [query]},
        timeout=30,
    )
    return resp.raise_for_status().json()["embeddings"][0]

_SEARCH = text(
    """
    SELECT code, title, description, credit_hours, credit_hours_max, prerequisites,
           catalog_term, embedding <=> CAST(:vec AS vector) AS distance
    FROM catalog_course
    WHERE embedding IS NOT NULL
      AND (CAST(:level AS text) IS NULL OR CAST(:level AS text) = ANY(levels))
    ORDER BY distance
    LIMIT :limit
    """
)

# Fallback when Ollama is down: plain keyword match on title/description.
_KEYWORD = text(
    """
    SELECT code, title, description, credit_hours, credit_hours_max, prerequisites,
           catalog_term, NULL AS distance
    FROM catalog_course
    WHERE (title ILIKE :pat OR description ILIKE :pat)
      AND (CAST(:level AS text) IS NULL OR CAST(:level AS text) = ANY(levels))
    ORDER BY code
    LIMIT :limit
    """
)

def search_catalog(query: str, limit: int = 5, level: str | None = None) -> list[dict[str, Any]]:
    try:
        vec = "[" + ",".join(f"{x:.7g}" for x in embed_query(query)) + "]"
        stmt, params = _SEARCH, {"vec": vec}
    except (httpx.HTTPError, KeyError, IndexError):
        stmt, params = _KEYWORD, {"pat": f"%{query}%"}
    with _engine().connect() as conn:
        rows = conn.execute(stmt, params | {"level": level, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]
