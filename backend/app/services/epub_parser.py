import io
import uuid
from pathlib import Path
from typing import Any

from app.vendor import ebooklib
from app.vendor.ebooklib import epub
from PIL import Image


def parse_epub_metadata(file_path: str) -> dict[str, Any]:
    """Extract metadata from an EPUB file."""
    result = {
        "epub_title": None,
        "epub_authors": None,
        "epub_publisher": None,
        "epub_language": None,
        "epub_isbn": None,
        "epub_description": None,
        "epub_published_date": None,
    }
    try:
        book = epub.read_epub(file_path, options={"ignore_ncx": True})

        title = book.get_metadata("DC", "title")
        if title:
            result["epub_title"] = title[0][0]

        creators = book.get_metadata("DC", "creator")
        if creators:
            result["epub_authors"] = [c[0] for c in creators if c[0]]

        publisher = book.get_metadata("DC", "publisher")
        if publisher:
            result["epub_publisher"] = publisher[0][0]

        language = book.get_metadata("DC", "language")
        if language:
            result["epub_language"] = language[0][0]

        description = book.get_metadata("DC", "description")
        if description:
            result["epub_description"] = description[0][0]

        date = book.get_metadata("DC", "date")
        if date:
            result["epub_published_date"] = date[0][0]

        identifiers = book.get_metadata("DC", "identifier")
        for ident in identifiers:
            value = ident[0]
            attrs = ident[1] if len(ident) > 1 else {}
            scheme = attrs.get("opf:scheme", "").lower()
            if "isbn" in scheme or (value and value.replace("-", "").isdigit() and len(value.replace("-", "")) in (10, 13)):
                result["epub_isbn"] = value.replace("-", "")
                break

    except Exception:
        pass
    return result


def extract_cover(file_path: str, cover_path: str) -> bool:
    """Extract cover image from EPUB. Returns True if successful."""
    try:
        book = epub.read_epub(file_path, options={"ignore_ncx": True})

        # Try to find cover image
        cover_item = None

        # Method 1: look for cover metadata
        cover_meta = book.get_metadata("OPF", "cover")
        if cover_meta:
            cover_id = cover_meta[0][1].get("content")
            if cover_id:
                cover_item = book.get_item_with_id(cover_id)

        # Method 2: EPUB 3 — look for item with properties="cover-image"
        if cover_item is None:
            for item in book.get_items():
                if "cover-image" in (getattr(item, "properties", None) or []):
                    cover_item = item
                    break

        # Method 3: look for item with id containing "cover"
        if cover_item is None:
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_IMAGE and "cover" in (item.get_id() or "").lower():
                    cover_item = item
                    break

        # Method 4: first image
        if cover_item is None:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                cover_item = item
                break

        if cover_item is None:
            return False

        image_data = cover_item.get_content()
        img = Image.open(io.BytesIO(image_data))
        img = img.convert("RGB")

        # Resize to max 400px wide keeping aspect ratio
        max_width = 400
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)

        Path(cover_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(cover_path, "JPEG", quality=85)
        return True

    except Exception:
        return False
