"""Build small comic archives in memory: numbered page images and an
optional ComicInfo.xml, the way CBZ tools write them."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

PORTRAIT = (800, 1200)
LANDSCAPE = (1600, 1200)


def page_image(number: int, size: tuple[int, int] = PORTRAIT, fmt="JPEG") -> bytes:
    """A flat page with its number drawn large, so a screenshot tells
    pages apart. Colours cycle so neighbouring pages differ."""
    palette = ["#f2d7a4", "#a4c8f2", "#b7e3b0", "#f2a4b8", "#d9c9f2", "#f2eaa4"]
    im = Image.new("RGB", size, palette[(number - 1) % len(palette)])
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=size[1] // 3)
    text = str(number)
    box = draw.textbbox((0, 0), text, font=font)
    x = (size[0] - (box[2] - box[0])) / 2 - box[0]
    y = (size[1] - (box[3] - box[1])) / 2 - box[1]
    draw.text((x, y), text, fill="#222222", font=font)
    buf = io.BytesIO()
    im.save(buf, fmt, quality=60)
    return buf.getvalue()


def comic_info_xml(
    *,
    title: str | None = None,
    series: str | None = None,
    number: str | None = None,
    writer: str | None = None,
    publisher: str | None = None,
    summary: str | None = None,
    year: str | None = None,
    language: str | None = None,
    genre: str | None = None,
    manga: str | None = None,
) -> bytes:
    fields = {
        "Title": title,
        "Series": series,
        "Number": number,
        "Writer": writer,
        "Publisher": publisher,
        "Summary": summary,
        "Year": year,
        "LanguageISO": language,
        "Genre": genre,
        "Manga": manga,
    }
    body = "".join(
        f"  <{tag}>{escape(value)}</{tag}>\n" for tag, value in fields.items() if value
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"{body}</ComicInfo>\n"
    ).encode()


def build_cbz(
    pages: list[tuple[int, int]] | int = 5,
    *,
    comic_info: bytes | None = None,
    names: list[str] | None = None,
    extra: dict[str, bytes] | None = None,
) -> bytes:
    """A CBZ with ``pages`` numbered images (a count, or one size per page).
    ``names`` overrides the entry names, e.g. to test ordering."""
    sizes = [PORTRAIT] * pages if isinstance(pages, int) else pages
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if comic_info is not None:
            zf.writestr("ComicInfo.xml", comic_info)
        for i, size in enumerate(sizes, start=1):
            name = names[i - 1] if names else f"pages/{i:03d}.jpg"
            zf.writestr(name, page_image(i, size))
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()
