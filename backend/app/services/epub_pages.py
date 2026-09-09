"""The page manifest of an EPUB: its spine, one entry per page, with the
image each page shows. This is what an image pager reads instead of
laying the XHTML out — a comic packed from a CBZ and a bought image-only
manga EPUB both come out as the same list.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import asdict, dataclass

from lxml import etree
from PIL import Image

_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
_IMG_RE = re.compile(r"<img\b[^>]*?\ssrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_SVG_IMAGE_RE = re.compile(
    r"<(?:svg:)?image\b[^>]*?\s(?:xlink:)?href=[\"']([^\"']+)[\"']", re.IGNORECASE
)
_VIEWPORT_RE = re.compile(
    r"<meta\b[^>]*?\bname=[\"']viewport[\"'][^>]*?\bcontent=[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"(width|height)\s*=\s*(\d+)")
_XHTML_TYPES = {"application/xhtml+xml", "text/html"}


@dataclass
class Page:
    index: int
    href: str
    image: str | None
    width: int | None
    height: int | None
    spread: str | None
    linear: bool


@dataclass
class PageManifest:
    layout: str
    direction: str
    pages: list[Page]

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve(base: str, target: str) -> str:
    target = target.split("#", 1)[0].split("?", 1)[0]
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def _viewport(text: str) -> tuple[int, int] | None:
    match = _VIEWPORT_RE.search(text)
    if not match:
        return None
    found = {k.lower(): int(v) for k, v in _SIZE_RE.findall(match.group(1))}
    if "width" in found and "height" in found:
        return found["width"], found["height"]
    return None


def _spread(properties: str) -> str | None:
    for prop in properties.split():
        if prop.endswith("page-spread-left"):
            return "left"
        if prop.endswith("page-spread-right"):
            return "right"
        if prop.endswith("page-spread-center"):
            return "center"
    return None


def read_page_manifest(file_path: str) -> PageManifest:
    """Read the spine of the EPUB at ``file_path`` as a list of pages."""
    with zipfile.ZipFile(file_path) as zf:
        container = etree.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", _CONTAINER_NS)
        if rootfile is None:
            raise ValueError("No rootfile in container.xml")
        opf_path = rootfile.get("full-path", "")
        opf = etree.fromstring(zf.read(opf_path))

        layout = "reflowable"
        for meta in opf.iterfind(".//opf:metadata/opf:meta", _OPF_NS):
            if meta.get("property") == "rendition:layout":
                layout = (meta.text or "").strip() or layout
            elif (
                meta.get("name") == "fixed-layout"
                and (meta.get("content") or "").lower() == "true"
            ):
                layout = "pre-paginated"

        items = {
            item.get("id"): (
                item.get("href", ""),
                item.get("media-type", ""),
                item.get("properties", ""),
            )
            for item in opf.iterfind(".//opf:manifest/opf:item", _OPF_NS)
        }
        spine = opf.find(".//opf:spine", _OPF_NS)
        direction = "default"
        if spine is not None:
            direction = spine.get("page-progression-direction") or "default"

        names = set(zf.namelist())
        pages: list[Page] = []
        for itemref in [] if spine is None else spine.iterfind("opf:itemref", _OPF_NS):
            item = items.get(itemref.get("idref"))
            if item is None:
                continue
            href, media_type, item_props = item
            page_path = _resolve(opf_path, href)
            image = None
            size = None
            if media_type in _XHTML_TYPES and page_path in names:
                text = zf.read(page_path).decode("utf-8", errors="replace")
                match = _IMG_RE.search(text) or _SVG_IMAGE_RE.search(text)
                if match:
                    candidate = _resolve(page_path, match.group(1))
                    if candidate in names:
                        image = candidate
                size = _viewport(text)
            elif media_type.startswith("image/") and page_path in names:
                image = page_path
            if size is None and image is not None:
                try:
                    with Image.open(io.BytesIO(zf.read(image))) as im:
                        size = im.size
                except Exception:
                    size = None
            spread = _spread(itemref.get("properties", "")) or _spread(item_props)
            pages.append(
                Page(
                    index=len(pages),
                    href=page_path,
                    image=image,
                    width=size[0] if size else None,
                    height=size[1] if size else None,
                    spread=spread,
                    linear=(itemref.get("linear") or "yes").lower() != "no",
                )
            )
    return PageManifest(layout=layout, direction=direction, pages=pages)
