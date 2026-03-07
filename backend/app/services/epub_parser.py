import io
import posixpath
import re
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

    def _is_image_item(item: Any) -> bool:
        media_type = (getattr(item, "media_type", "") or "").lower()
        if media_type.startswith("image/"):
            return True
        item_type = item.get_type()
        return item_type in (ebooklib.ITEM_IMAGE, ebooklib.ITEM_COVER)

    def _first_img_src_from_html(content: bytes) -> str | None:
        text = content.decode("utf-8", errors="ignore")
        # Try <img src="...">
        match = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", text, re.IGNORECASE)
        if match:
            return match.group(1)
        # Try SVG <image xlink:href="..."> or <image href="...">
        match = re.search(r"<image[^>]+(?:xlink:)?href=[\"']([^\"']+)[\"']", text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _normalize_href(base_href: str, target_href: str) -> str:
        target = (target_href or "").split("#", 1)[0].split("?", 1)[0]
        if not target:
            return ""
        if target.startswith("/"):
            return target.lstrip("/")
        base_dir = posixpath.dirname(base_href)
        return posixpath.normpath(posixpath.join(base_dir, target))

    def _resolve_image_from_document(doc_href: str) -> Any | None:
        doc_item = book.get_item_with_href(doc_href)
        if not doc_item:
            return None

        src = _first_img_src_from_html(doc_item.get_content())
        if not src:
            return None

        img_href = _normalize_href(doc_href, src)
        if not img_href:
            return None
        img_item = book.get_item_with_href(img_href)
        if img_item and _is_image_item(img_item):
            return img_item
        return None

    try:
        book = epub.read_epub(file_path, options={"ignore_ncx": True})

        # Try to find cover image
        cover_item = None
        cover_id = None

        # Method 1: look for cover metadata
        cover_meta = book.get_metadata("OPF", "cover")
        if cover_meta:
            cover_id = cover_meta[0][1].get("content")

        # OPF2 meta tags are often stored as OPF/meta with attrs {name, content}
        if not cover_id:
            opf_meta = book.get_metadata("OPF", "meta")
            for _value, attrs in opf_meta:
                if ((attrs or {}).get("name") or "").lower() == "cover":
                    cover_id = (attrs or {}).get("content")
                    if cover_id:
                        break

        if cover_id:
            candidate = book.get_item_with_id(cover_id)
            if candidate and _is_image_item(candidate):
                cover_item = candidate

        # Method 1b: guide reference type="cover" may point to cover HTML
        if cover_item is None:
            for ref in getattr(book, "guide", []) or []:
                if (ref.get("type") or "").lower() != "cover":
                    continue
                href = (ref.get("href") or "").split("#", 1)[0]
                if not href:
                    continue
                candidate = book.get_item_with_href(href)
                if candidate and _is_image_item(candidate):
                    cover_item = candidate
                    break
                candidate = _resolve_image_from_document(href)
                if candidate is not None:
                    cover_item = candidate
                    break

        # Method 2: EPUB 3 — look for item with properties="cover-image"
        if cover_item is None:
            for item in book.get_items():
                if "cover-image" in (getattr(item, "properties", None) or []):
                    if _is_image_item(item):
                        cover_item = item
                    break

        # Method 3: look for item with id containing "cover"
        if cover_item is None:
            for item in book.get_items():
                if _is_image_item(item) and "cover" in (item.get_id() or "").lower():
                    cover_item = item
                    break

        # Method 3b: look for cover html doc by id/href then resolve first <img>
        if cover_item is None:
            for item in book.get_items():
                item_id = (item.get_id() or "").lower()
                item_name = (item.get_name() or "").lower()
                if "cover" in item_id or "cover" in item_name:
                    candidate = _resolve_image_from_document(item.get_name())
                    if candidate is not None:
                        cover_item = candidate
                        break

        # Method 4: first image
        if cover_item is None:
            for item in book.get_items():
                if _is_image_item(item):
                    cover_item = item
                    break

        # Method 5: fallback from first spine document image
        if cover_item is None:
            for spine_item in getattr(book, "spine", []) or []:
                if not spine_item:
                    continue
                item_id = spine_item[0] if isinstance(spine_item, tuple) else spine_item
                doc_item = book.get_item_with_id(item_id)
                if not doc_item:
                    continue
                candidate = _resolve_image_from_document(doc_item.get_name())
                if candidate is not None:
                    cover_item = candidate
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
