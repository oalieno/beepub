import base64
import io

import httpx
from PIL import Image

from app.config import settings

BASE_INSTRUCTION = (
    "You are a book illustrator. Create a single illustration that could appear as a page insert "
    "in a published novel or literary work. The image should depict the scene described below in a "
    "natural, artistic way — NOT an infographic, diagram, or explanatory image. "
    "Focus on atmosphere, emotion, and composition like a real book illustration. "
    "No text, labels, or captions in the image.\n\n"
)

STYLE_PROMPTS = {
    "ink_wash": {
        "label": "Ink Wash",
        "description": "Elegant ink wash, like classic novel illustrations",
        "prompt": BASE_INSTRUCTION + "Style: Black-and-white ink wash illustration with delicate line work and subtle grey tones, reminiscent of classic literary novel illustrations from the 19th-20th century.\n\nScene: {text}",
    },
    "watercolor": {
        "label": "Watercolor",
        "description": "Soft watercolor with muted tones",
        "prompt": BASE_INSTRUCTION + "Style: Soft watercolor painting with muted, natural tones and gentle washes. The feel of a hand-painted book plate illustration.\n\nScene: {text}",
    },
    "pencil_sketch": {
        "label": "Pencil Sketch",
        "description": "Detailed pencil drawing, like a chapter heading",
        "prompt": BASE_INSTRUCTION + "Style: Detailed pencil or graphite sketch with fine hatching and shading, like a chapter heading illustration in a hardcover novel.\n\nScene: {text}",
    },
    "woodcut": {
        "label": "Woodcut",
        "description": "Bold woodcut / linocut print style",
        "prompt": BASE_INSTRUCTION + "Style: Bold black-and-white woodcut or linocut print illustration with strong contrast, like illustrations found in classic fairy tales and folklore collections.\n\nScene: {text}",
    },
    "anime": {
        "label": "Light Novel",
        "description": "Japanese light novel illustration style",
        "prompt": BASE_INSTRUCTION + "Style: Japanese light novel illustration — clean line art with soft cel-shading, a full-color character scene suitable for a light novel insert page.\n\nScene: {text}",
    },
    "oil_painting": {
        "label": "Oil Painting",
        "description": "Rich oil painting, like a fantasy novel cover",
        "prompt": BASE_INSTRUCTION + "Style: Rich oil painting with deep colors, dramatic lighting, and textured brushwork, like a fantasy or historical novel frontispiece illustration.\n\nScene: {text}",
    },
}


def get_style_prompts() -> list[dict]:
    return [
        {"key": k, "label": v["label"], "description": v["description"]}
        for k, v in STYLE_PROMPTS.items()
    ]


async def generate_illustration(text: str, style_prompt: str | None, custom_prompt: str | None) -> bytes:
    """Call Gemini API to generate an image. Returns resized PNG bytes."""
    if custom_prompt:
        prompt = f"{BASE_INSTRUCTION}{custom_prompt}\n\nScene: {text}"
    elif style_prompt and style_prompt in STYLE_PROMPTS:
        prompt = STYLE_PROMPTS[style_prompt]["prompt"].format(text=text)
    else:
        prompt = f"{BASE_INSTRUCTION}Style: A tasteful ink wash illustration suitable for a literary novel.\n\nScene: {text}"

    model = settings.gemini_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                    "imageConfig": {
                        "aspectRatio": "1:1",
                        "imageSize": "1K",
                    },
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()

    for part in data["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            raw_bytes = base64.b64decode(part["inlineData"]["data"])
            return _resize_image(raw_bytes)
        if "inline_data" in part:
            raw_bytes = base64.b64decode(part["inline_data"]["data"])
            return _resize_image(raw_bytes)

    raise ValueError("No image data in Gemini response")


def _resize_image(raw_bytes: bytes, max_size: int = 1024) -> bytes:
    """Resize image to max_size on its longest side, return PNG bytes."""
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert("RGB")
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
