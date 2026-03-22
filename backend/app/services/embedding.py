"""Embedding service — calls Gemini embedding API to produce vector embeddings."""

from __future__ import annotations

import logging
import math

import httpx

from app.services.llm import TokenUsage

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
) -> tuple[list[list[float]], TokenUsage]:
    """Embed a batch of texts using Gemini embedding API.

    Returns (embeddings, usage) where embeddings is a list of normalized vectors.
    Max batch size for Gemini is 100 texts per request.
    """
    if not texts:
        return [], TokenUsage()

    url = f"{_GEMINI_BASE}/models/{model}:batchEmbedContents"
    requests_body = [
        {
            "model": f"models/{model}",
            "content": {"parts": [{"text": t}]},
            "outputDimensionality": dimensionality,
        }
        for t in texts
    ]

    headers = {"x-goog-api-key": api_key}

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Embed
        resp = await client.post(url, headers=headers, json={"requests": requests_body})
        resp.raise_for_status()
        data = resp.json()

        # Count tokens (free API) — batchEmbedContents doesn't return usage
        count_url = f"{_GEMINI_BASE}/models/{model}:countTokens"
        count_resp = await client.post(
            count_url,
            headers=headers,
            json={
                "contents": [{"parts": [{"text": t}]} for t in texts],
            },
        )
        if count_resp.status_code == 200:
            token_count = count_resp.json().get("totalTokens", 0)
        else:
            token_count = 0

    embeddings = []
    for emb in data["embeddings"]:
        vector = emb["values"]
        embeddings.append(_normalize(vector))

    usage = TokenUsage(
        input_tokens=token_count,
        output_tokens=0,
        total_tokens=token_count,
    )

    return embeddings, usage


async def embed_text(
    text: str,
    *,
    api_key: str,
    model: str = "gemini-embedding-001",
    dimensionality: int = 768,
) -> tuple[list[float], TokenUsage]:
    """Embed a single text. Convenience wrapper around embed_texts."""
    results, usage = await embed_texts(
        [text], api_key=api_key, model=model, dimensionality=dimensionality
    )
    return results[0], usage
