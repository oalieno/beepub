"""Embedding service — calls OpenAI-compatible embedding API."""

from __future__ import annotations

import logging
import math

import httpx

from app.services.llm import TokenUsage

logger = logging.getLogger(__name__)

# Output dimensionality (Qwen3-Embedding-0.6B default)
EMBEDDING_DIMENSIONS = 1024

# Qwen3-Embedding instruction prompt for query-side asymmetric retrieval.
EMBEDDING_PROMPT_QUERY = (
    "Instruct: Given a user search query, retrieve relevant book passages\nQuery: "
)


def _normalize(vector: list[float]) -> list[float]:
    """L2-normalize a vector."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


async def embed_texts(
    texts: list[str],
    *,
    api_url: str,
    model: str,
    api_key: str = "",
    prompt: str = "",
) -> tuple[list[list[float]], TokenUsage]:
    """Embed a batch of texts using an OpenAI-compatible /v1/embeddings endpoint.

    Returns (embeddings, usage) where embeddings is a list of normalized vectors.
    """
    if not texts:
        return [], TokenUsage()

    url = f"{api_url}/embeddings"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict = {"model": model, "input": texts}
    if prompt:
        body["prompt"] = prompt

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    embeddings = []
    for item in sorted(data["data"], key=lambda x: x["index"]):
        vector = item["embedding"]
        embeddings.append(_normalize(vector))

    # OpenAI-compatible usage
    usage_data = data.get("usage", {})
    token_count = usage_data.get("total_tokens") or usage_data.get("prompt_tokens") or 0

    # Some local servers (e.g. LM Studio) report 0 tokens — estimate from input
    if not token_count:
        token_count = sum(len(t) for t in texts)

    usage = TokenUsage(
        input_tokens=token_count,
        output_tokens=0,
        total_tokens=token_count,
    )

    return embeddings, usage


async def embed_text(
    text: str,
    *,
    api_url: str,
    model: str,
    api_key: str = "",
    prompt: str = "",
) -> tuple[list[float], TokenUsage]:
    """Embed a single text. Convenience wrapper around embed_texts."""
    results, usage = await embed_texts(
        [text], api_url=api_url, model=model, api_key=api_key, prompt=prompt
    )
    return results[0], usage
