"""CBZ → pre-paginated EPUB, the canonical file everything else reads.

A comic archive is a zip of page images, optionally with a ComicInfo.xml
(the ComicRack schema most tools write). It is packed here into the same
shape commercial manga EPUBs take: one fixed-layout XHTML page per image
carrying a viewport of the image's true pixel size, and a spine reading
right-to-left when ComicInfo says so. Any reader that handles a bought
image-only EPUB handles this one too.
"""

from __future__ import annotations

import io
import mimetypes
import os
import posixpath
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from lxml import etree
from PIL import Image, UnidentifiedImageError

PAGE_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


class CbzError(ValueError):
    """The file is not a comic archive we can convert."""


@dataclass
class ComicInfo:
    """What a ComicInfo.xml tells us, all optional."""

    title: str | None = None
    series: str | None = None
    number: float | None = None
    writers: list[str] = field(default_factory=list)
    publisher: str | None = None
    summary: str | None = None
    published: str | None = None
    language: str | None = None
    genres: list[str] = field(default_factory=list)
    rtl: bool = False


def _split_list(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def read_comic_info(data: bytes) -> ComicInfo:
    """Parse a ComicInfo.xml; unreadable XML is treated as absent."""
    try:
        root = etree.fromstring(data, etree.XMLParser(recover=True))
    except etree.XMLSyntaxError:
        return ComicInfo()
    if root is None:
        return ComicInfo()

    def text(tag: str) -> str | None:
        node = root.find(tag)
        if node is None or not (node.text or "").strip():
            return None
        return node.text.strip()

    info = ComicInfo(
        title=text("Title"),
        series=text("Series"),
        writers=_split_list(text("Writer")),
        publisher=text("Publisher"),
        summary=text("Summary"),
        language=text("LanguageISO"),
        genres=_split_list(text("Genre")),
        rtl=(text("Manga") or "").lower() == "yesandrighttoleft",
    )
    number = text("Number")
    if number:
        try:
            info.number = float(number)
        except ValueError:
            pass
    year, month, day = text("Year"), text("Month"), text("Day")
    if year and year.isdigit():
        info.published = year
        if month and month.isdigit():
            info.published += f"-{int(month):02d}"
            if day and day.isdigit():
                info.published += f"-{int(day):02d}"
    return info


_NUMBER_RE = re.compile(r"(\d+)")


def natural_key(name: str) -> list[object]:
    """Sort key so page 2 comes before page 10 whatever the zero padding."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in _NUMBER_RE.split(name)
        if part
    ]


def list_pages(zf: zipfile.ZipFile) -> list[str]:
    """The archive's page images in reading order."""
    pages = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        parts = name.split("/")
        if any(p.startswith(".") or p == "__MACOSX" for p in parts):
            continue
        if posixpath.splitext(name)[1].lower() in PAGE_IMAGE_EXTS:
            pages.append(name)
    return sorted(pages, key=natural_key)


def image_size(data: bytes) -> tuple[int, int] | None:
    """Pixel size from the image header, or None when Pillow can't read it."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except (UnidentifiedImageError, OSError, ValueError):
        return None


_CONTAINER = """\
<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _page_xhtml(title: str, lang: str, image_href: str, w: int, h: int) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xml:lang="{lang}">\n<head>\n<meta charset="utf-8"/>\n'
        f"<title>{title}</title>\n"
        f'<meta name="viewport" content="width={w}, height={h}"/>\n'
        "<style>\n"
        f"html, body {{ margin: 0; padding: 0; width: {w}px; height: {h}px; }}\n"
        "img { display: block; width: 100%; height: 100%; }\n"
        "</style>\n</head>\n<body>\n"
        f'<img src="{image_href}" width="{w}" height="{h}" alt=""/>\n'
        "</body>\n</html>\n"
    )


def convert_cbz_to_epub(src_path: str, out_path: str) -> None:
    """Write the pre-paginated EPUB for the CBZ at ``src_path`` to ``out_path``."""
    try:
        zin = zipfile.ZipFile(src_path)
    except zipfile.BadZipFile as exc:
        raise CbzError("Not a CBZ file") from exc
    with zin:
        info = ComicInfo()
        for name in zin.namelist():
            if posixpath.basename(name).lower() == "comicinfo.xml":
                info = read_comic_info(zin.read(name))
                break
        pages = list_pages(zin)
        if not pages:
            raise CbzError("The archive has no images")

        title = (
            info.title or info.series or os.path.splitext(os.path.basename(src_path))[0]
        )
        if info.series and info.number is not None and not info.title:
            number = int(info.number) if info.number.is_integer() else info.number
            title = f"{info.series} {number}"
        lang = escape(info.language or "und")
        title_x = escape(title)
        uid = f"urn:uuid:{uuid.uuid4()}"

        manifest = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        ]
        spine = []
        entries: list[tuple[str, bytes, int]] = []  # zip name, data, compression
        for name in pages:
            try:
                data = zin.read(name)
            except RuntimeError as exc:  # encrypted entry
                raise CbzError("The archive is encrypted") from exc
            size = image_size(data)
            if size is None:
                continue
            w, h = size
            i = len(spine) + 1
            ext = posixpath.splitext(name)[1].lower()
            if ext == ".jpeg":
                ext = ".jpg"
            image_href = f"images/{i:04d}{ext}"
            page_href = f"page{i:04d}.xhtml"
            mime = mimetypes.guess_type(image_href)[0] or "image/jpeg"
            is_cover = not entries
            props = ' properties="cover-image"' if is_cover else ""
            manifest.append(
                f'<item id="{"cover-image" if is_cover else f"img{i:04d}"}" '
                f'href="{image_href}" media-type="{mime}"{props}/>'
            )
            manifest.append(
                f'<item id="p{i:04d}" href="{page_href}" media-type="application/xhtml+xml"/>'
            )
            spine.append(f'<itemref idref="p{i:04d}"/>')
            entries.append((f"OEBPS/{image_href}", data, zipfile.ZIP_STORED))
            entries.append(
                (
                    f"OEBPS/{page_href}",
                    _page_xhtml(title_x, lang, image_href, w, h).encode(),
                    zipfile.ZIP_DEFLATED,
                )
            )
        if not entries:
            raise CbzError("The archive has no images")

    creators = "".join(
        f"    <dc:creator>{escape(a)}</dc:creator>\n" for a in info.writers
    )
    optional = ""
    if info.publisher:
        optional += f"    <dc:publisher>{escape(info.publisher)}</dc:publisher>\n"
    if info.summary:
        optional += f"    <dc:description>{escape(info.summary)}</dc:description>\n"
    if info.published:
        optional += f"    <dc:date>{escape(info.published)}</dc:date>\n"
    for genre in info.genres:
        optional += f"    <dc:subject>{escape(genre)}</dc:subject>\n"
    if info.series:
        optional += f'    <meta name="calibre:series" content="{escape(info.series, {chr(34): "&quot;"})}"/>\n'
        if info.number is not None:
            optional += (
                f'    <meta name="calibre:series_index" content="{info.number:g}"/>\n'
            )
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    direction = ' page-progression-direction="rtl"' if info.rtl else ""
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'prefix="rendition: http://www.idpf.org/vocab/rendition/#" '
        f'unique-identifier="uid" xml:lang="{lang}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
        f"    <dc:title>{title_x}</dc:title>\n"
        f"{creators}"
        f"    <dc:language>{lang}</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        '    <meta property="rendition:layout">pre-paginated</meta>\n'
        '    <meta property="rendition:orientation">auto</meta>\n'
        '    <meta property="rendition:spread">auto</meta>\n'
        '    <meta name="cover" content="cover-image"/>\n'
        f"{optional}"
        "  </metadata>\n"
        "  <manifest>\n    " + "\n    ".join(manifest) + "\n  </manifest>\n"
        f"  <spine{direction}>\n    " + "\n    ".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{title_x}</title>\n</head>\n<body>\n'
        '<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n'
        f'<li><a href="page0001.xhtml">{title_x}</a></li>\n'
        "</ol>\n</nav>\n</body>\n</html>\n"
    )

    with zipfile.ZipFile(out_path, "w") as zf:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        zf.writestr(mimetype, "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
        for name, data, compression in entries:
            zf.writestr(name, data, compression)
