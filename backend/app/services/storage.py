import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.plugins.metadata import registry as metadata_registry

# Hard cap for any uploaded file. Image-heavy manga epubs are legitimately
# large, so this is set generously. Must match nginx `client_max_body_size`.
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB

# Server-side cover fetches only ever target hosts the metadata plugins
# declare (cover_hosts) — an allowlist, not a validation, because the
# URL is user-supplied and the request originates from the backend
# (SSRF surface). Derived from the registry so drop-in plugins extend
# it without touching this file.
COVER_URL_ALLOWED_HOSTS = frozenset(metadata_registry.cover_allowed_hosts())
MAX_COVER_DOWNLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


def cover_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname in COVER_URL_ALLOWED_HOSTS


async def download_cover(url: str, dest_path: str) -> bool:
    """Fetch a cover image from an allowlisted metadata host. Best-effort:
    any failure returns False and leaves no file behind. The bytes are
    re-encoded through Pillow — sources serve mixed formats (webp/png)
    while cover_path is served as JPEG, and a decode doubles as proof the
    payload really is an image."""
    if not cover_url_allowed(url):
        return False
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BeePub/1.0)"},
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return False
                content_type = resp.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    return False
                size = 0
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > MAX_COVER_DOWNLOAD_SIZE:
                        return False
                    chunks.append(chunk)
        if size == 0:
            return False

        import io

        from PIL import Image

        with Image.open(io.BytesIO(b"".join(chunks))) as img:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            img.convert("RGB").save(dest_path, "JPEG", quality=88)
        return True
    except Exception:
        delete_file(dest_path)
        return False


def get_book_path(book_id: uuid.UUID, filename: str) -> str:
    ext = Path(filename).suffix
    return str(Path(settings.books_dir) / f"{book_id}{ext}")


def get_cover_path(book_id: uuid.UUID) -> str:
    return str(Path(settings.covers_dir) / f"{book_id}.jpg")


def get_illustration_path(illustration_id: uuid.UUID) -> str:
    return str(Path(settings.illustrations_dir) / f"{illustration_id}.png")


async def save_upload_file(upload_file: UploadFile, dest_path: str) -> int:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    size = 0
    try:
        with open(dest_path, "wb") as f:
            while chunk := await upload_file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            f"File exceeds maximum upload size of "
                            f"{MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
                        ),
                    )
                f.write(chunk)
    except HTTPException:
        # Don't leave a half-written file on disk if the upload was rejected.
        try:
            os.remove(dest_path)
        except FileNotFoundError:
            pass
        raise
    return size


def delete_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
