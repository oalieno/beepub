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


# Every stored cover is at most this wide, as JPEG at this quality —
# enough for a retina grid card, and a Calibre library's full-size
# covers otherwise run to tens of GB.
COVER_MAX_WIDTH = 800
COVER_JPEG_QUALITY = 85


def encode_cover(data: bytes) -> bytes:
    """Arbitrary image bytes as the canonical cover JPEG: upright, RGB
    (transparency flattened onto white), at most COVER_MAX_WIDTH wide —
    never upscaled. Raises on anything Pillow can't decode."""
    import io

    from PIL import Image, ImageFile, ImageOps

    # A file cut a few bytes short (no end marker) still shows in every
    # browser; take it as they do rather than call the cover broken.
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "PA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, "white")
            img.paste(rgba, mask=rgba.getchannel("A"))
        else:
            # CMYK, grayscale, palette: Pillow's own conversion is right.
            img = img.convert("RGB")
        if img.width > COVER_MAX_WIDTH:
            height = max(1, round(img.height * COVER_MAX_WIDTH / img.width))
            img = img.resize((COVER_MAX_WIDTH, height), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=COVER_JPEG_QUALITY)
        return out.getvalue()


# Beside each cover, a small one for the lists: a grid card is a few
# hundred device pixels wide, and a page of sixty full covers is some
# 11 MB against 2. WebP, which every browser the app runs in reads.
THUMBNAIL_WIDTH = 480
THUMBNAIL_QUALITY = 75


def cover_thumbnail_path(cover_path: str) -> str:
    """Where a cover's thumbnail is kept: `thumb/<cover's file name>.webp`
    beside it — served as `/covers/thumb/<id>.jpg.webp`."""
    path = Path(cover_path)
    return str(path.parent / "thumb" / f"{path.name}.webp")


def encode_cover_thumbnail(cover: bytes) -> bytes:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(cover)) as img:
        img = img.convert("RGB")
        if img.width > THUMBNAIL_WIDTH:
            height = max(1, round(img.height * THUMBNAIL_WIDTH / img.width))
            img = img.resize((THUMBNAIL_WIDTH, height), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "WEBP", quality=THUMBNAIL_QUALITY, method=4)
        return out.getvalue()


def write_cover_thumbnail(cover_path: str) -> bool:
    """Make (or remake) the thumbnail of the cover at this path. Best
    effort: a cover without one is shown full-size where the small one
    is asked for. Via a temp file, so a reader never gets half of one."""
    dest = cover_thumbnail_path(cover_path)
    tmp = f"{dest}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        with open(cover_path, "rb") as f:
            encoded = encode_cover_thumbnail(f.read())
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(encoded)
        os.replace(tmp, dest)
        return True
    except Exception:
        delete_file(tmp)
        return False


def is_cover_file(path: str) -> bool:
    """A cover in its place (`<id>.jpg`), not one on its way there (the
    temp files a replacement is written to first)."""
    return path.endswith(".jpg")


def place_cover(tmp_path: str, dest_path: str) -> None:
    """Put a cover written to a temp file in its place, its thumbnail
    remade with it."""
    os.replace(tmp_path, dest_path)
    write_cover_thumbnail(dest_path)


def save_cover_bytes(data: bytes, dest_path: str) -> bool:
    """Decode-and-re-encode arbitrary image bytes into the canonical
    JPEG cover. The decode is the validation — non-image payloads
    return False and leave no file behind."""
    try:
        encoded = encode_cover(data)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(encoded)
        if is_cover_file(dest_path):
            write_cover_thumbnail(dest_path)
        return True
    except Exception:
        delete_file(dest_path)
        return False


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
        return save_cover_bytes(b"".join(chunks), dest_path)
    except Exception:
        delete_file(dest_path)
        return False


def get_book_path(book_id: uuid.UUID, filename: str) -> str:
    ext = Path(filename).suffix
    return str(Path(settings.books_dir) / f"{book_id}{ext}")


def get_kept_epub_path(book_id: uuid.UUID) -> str:
    """An EPUB upload as it was, kept when the book's file is rewritten."""
    return str(Path(settings.books_dir) / f"{book_id}.original.epub")


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


def delete_file(path: str | None) -> None:
    """Remove a file, if it is there — and, with a cover, its thumbnail."""
    if not path:
        return
    for target in [path, cover_thumbnail_path(path)] if is_cover_file(path) else [path]:
        try:
            os.remove(target)
        except FileNotFoundError:
            pass
