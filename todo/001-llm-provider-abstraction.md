# 001 — LLM Provider Abstraction ✅ DONE

## Goal

Refactor the current Gemini-only integration into a provider-agnostic LLM service layer. Add SSE streaming support for text generation (the current illustration flow uses poll-based status, which is too slow for conversational AI features).

## User Story

As a developer, I want a clean LLM abstraction so that adding new AI features (explain, translate, summarize, chat) doesn't couple them to Gemini, and so we can later swap in Ollama or OpenAI without changing feature code.

## Technical Approach

### 1. LLM Provider Protocol

Create `backend/app/services/llm.py` with:

```python
class LLMProvider(Protocol):
    async def generate(self, prompt: str, system: str | None = None) -> str: ...
    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]: ...
```

### 2. Gemini Provider

Move API call logic from `backend/app/services/gemini.py` into a `GeminiProvider` class implementing `LLMProvider`. Keep the image generation function separate (it has different response handling).

- `generate()` — single-shot text response (for AI notes, tagging)
- `stream()` — SSE streaming via Gemini's `streamGenerateContent` endpoint (for explain, translate, summarize, chat)

### 3. SSE Streaming Endpoint Pattern

Create a reusable FastAPI helper for SSE responses:

```python
from fastapi.responses import StreamingResponse

async def sse_stream(provider: LLMProvider, prompt: str, system: str):
    async def event_generator():
        async for chunk in provider.stream(prompt, system):
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 4. Configuration

Add to `backend/app/config.py`:
- `llm_provider: str = "gemini"` (future: `"ollama"`, `"openai"`)
- Keep existing `gemini_api_key` and `gemini_model`

### 5. Preserve Illustration Flow

`generate_illustration()` stays as-is in `gemini.py` — image generation is Gemini-specific and doesn't need the abstraction layer yet.

## Key Files

- `backend/app/services/gemini.py` — current Gemini service (keep for image gen, extract text gen logic)
- `backend/app/services/llm.py` — new provider abstraction + GeminiProvider
- `backend/app/config.py` — add `llm_provider` setting
- `backend/app/routers/illustrations.py` — reference for background task pattern (don't change)

## Dependencies

None. This is a foundation ticket — no new features, just infrastructure.

## Verification

- Existing illustration generation still works unchanged
- New `LLMProvider.generate()` returns text from Gemini API
- New `LLMProvider.stream()` yields text chunks
- Unit test calling `generate()` with a simple prompt
