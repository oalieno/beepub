"""Embedding service — calls Gemini embedding API to produce vector embeddings."""

from __future__ import annotations

import logging
import math

import httpx

logger = logging.getLogger(__name__)

# Gemini embedding API base URL
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _normalize(vector: list[float]) -> list[float]:
    """L2-normalize a vector (required for Matryoshka-reduced dimensions)."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


async def embed_texts(
    texts: list[str],
    *,
    api_key: str,
    model: str = "gemini-embedding-001",
    dimensionality: int = 768,
) -> list[list[float]]:
    """Embed a batch of texts using Gemini embedding API.

    Returns a list of normalized embedding vectors (one per input text).
    Max batch size for Gemini is 100 texts per request.
    """
    if not texts:
        return []

    url = f"{_GEMINI_BASE}/models/{model}:batchEmbedContents"
    requests_body = [
        {
            "model": f"models/{model}",
            "content": {"parts": [{"text": t}]},
            "outputDimensionality": dimensionality,
        }
        for t in texts
    ]

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"x-goog-api-key": api_key},
            json={"requests": requests_body},
        )
        resp.raise_for_status()
        data = resp.json()

    embeddings = []
    for emb in data["embeddings"]:
        vector = emb["values"]
        embeddings.append(_normalize(vector))
    return embeddings


async def embed_text(
    text: str,
    *,
    api_key: str,
    model: str = "gemini-embedding-001",
    dimensionality: int = 768,
) -> list[float]:
    """Embed a single text. Convenience wrapper around embed_texts."""
    results = await embed_texts(
        [text], api_key=api_key, model=model, dimensionality=dimensionality
    )
    return results[0]
