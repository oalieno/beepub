"""MOBI / AZW3 → EPUB, the canonical file everything else reads.

KindleUnpack (the ``mobi`` package) does the format work. A KF8 book
(AZW3, or the KF8 half of a hybrid MOBI) unpacks straight to an EPUB —
KF8 is an EPUB in a Palm database, so that conversion is near lossless.
An old MOBI7 book unpacks to one HTML file plus its images; that HTML is
split on the page breaks and packed into an EPUB here. Print-replica
(PDF-in-a-MOBI) and encrypted books are rejected.
"""

from __future__ import annotations

import contextlib
import io
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from lxml import etree, html
from mobi.kindleunpack import unpackBook, unpackException


class MobiError(ValueError):
    """The file is not a MOBI/AZW3 we can convert."""


class DrmProtectedError(MobiError):
    """The book is encrypted; nothing to convert."""


def convert_mobi_to_epub(src_path: str, out_path: str) -> None:
    """Write the EPUB for the MOBI/AZW3 at ``src_path`` to ``out_path``."""
    tmpdir = tempfile.mkdtemp(prefix="beepub-mobi-")
    try:
        # KindleUnpack narrates on stdout; keep that out of the worker log.
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                unpackBook(src_path, tmpdir, epubver="A")
            except unpackException as exc:
                if "encrypted" in str(exc).lower():
                    raise DrmProtectedError(str(exc)) from exc
                raise MobiError(str(exc)) from exc
            except Exception as exc:
                # KindleUnpack trusts its input: garbage surfaces as
                # struct/index errors rather than its own exception.
                raise MobiError(f"Not a MOBI file: {exc}") from exc
        kf8_dir = os.path.join(tmpdir, "mobi8")
        if os.path.isdir(kf8_dir):
            epubs = [n for n in os.listdir(kf8_dir) if n.endswith(".epub")]
            if epubs:
                _copy_kf8_epub(os.path.join(kf8_dir, epubs[0]), out_path)
                return
        mobi7_dir = os.path.join(tmpdir, "mobi7")
        if os.path.exists(os.path.join(mobi7_dir, "book.html")):
            pack_mobi7(mobi7_dir, out_path)
            return
        raise MobiError("Not a text book (print replica or unknown layout)")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


_MOBI_UID_RE = re.compile(
    r"<dc:identifier(?![^>]*scheme)([^>]*)>\s*\d+\s*</dc:identifier>"
)


def _copy_kf8_epub(src: str, out_path: str) -> None:
    """KindleUnpack's EPUB, with the Kindle uid — a random number that
    the metadata pipeline could mistake for an ISBN — replaced by a UUID
    in the OPF. Everything else is copied entry for entry."""
    uid = f"urn:uuid:{uuid.uuid4()}"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out_path, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith(".opf"):
                data = _MOBI_UID_RE.sub(
                    lambda m: f"<dc:identifier{m.group(1)}>{uid}</dc:identifier>",
                    data.decode("utf-8", errors="replace"),
                ).encode("utf-8")
            zout.writestr(info, data, compress_type=info.compress_type)


# --------------------------------------------------------------------------
# MOBI7: one HTML file → chaptered EPUB
# --------------------------------------------------------------------------

_OPF_NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}
_NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
_PAGEBREAK_ID = "beepub-mobi-pagebreak"
_VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_SELF_CLOSING_RE = re.compile(r"<([A-Za-z][\w:-]*)((?:\s[^<>]*?)?)\s*/>")
_MBP_TAG_RE = re.compile(r"</?mbp:(?!pagebreak)[\w-]+[^<>]*>", re.IGNORECASE)
_MBP_PAGEBREAK_RE = re.compile(r"<mbp:pagebreak\b[^<>]*>(?:</mbp:pagebreak>)?", re.I)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*)</body>", re.IGNORECASE | re.DOTALL)

_CONTAINER = """\
<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


@dataclass
class _Meta:
    title: str
    authors: list[str]
    language: str
    cover_href: str | None


def _read_opf(path: str) -> _Meta:
    """Title, creators, language and cover image from KindleUnpack's OPF."""
    meta = _Meta(title="Untitled", authors=[], language="en", cover_href=None)
    if not os.path.exists(path):
        return meta
    root = etree.parse(path).getroot()
    title = root.findtext(".//dc:title", namespaces=_OPF_NS)
    if title and title.strip():
        meta.title = title.strip()
    meta.authors = [
        c.text.strip()
        for c in root.findall(".//dc:creator", namespaces=_OPF_NS)
        if c.text and c.text.strip()
    ]
    language = root.findtext(".//dc:language", namespaces=_OPF_NS)
    if language and language.strip():
        meta.language = language.strip()
    cover_id = None
    for m in root.iter(f"{{{_OPF_NS['opf']}}}meta"):
        if (m.get("name") or "").lower() == "cover":
            cover_id = m.get("content")
    if cover_id:
        for item in root.iter(f"{{{_OPF_NS['opf']}}}item"):
            if item.get("id") == cover_id:
                meta.cover_href = item.get("href")
    return meta


def _read_ncx(path: str) -> list[tuple[str, str]]:
    """(label, fragment) per navPoint, in document order."""
    if not os.path.exists(path):
        return []
    root = etree.parse(path).getroot()
    points = []
    for np in root.iter(f"{{{_NCX_NS['ncx']}}}navPoint"):
        label = np.findtext("ncx:navLabel/ncx:text", namespaces=_NCX_NS) or ""
        content = np.find("ncx:content", namespaces=_NCX_NS)
        src = content.get("src") if content is not None else ""
        fragment = src.split("#", 1)[1] if src and "#" in src else ""
        if label.strip():
            points.append((label.strip(), fragment))
    return points


def _close_self_closing(match: re.Match[str]) -> str:
    tag, attrs = match.group(1), match.group(2)
    if tag.lower() in _VOID_TAGS:
        return match.group(0)
    return f"<{tag}{attrs}></{tag}>"


def _prepare_html(raw: str) -> str:
    """The body's inner HTML, with Mobipocket's non-HTML smoothed out so
    the HTML parser reads it the way Kindle did: page breaks become <hr>
    markers, other mbp: tags vanish, and `<a id="..."/>` — which an HTML
    parser would otherwise leave open — is closed."""
    body = _BODY_RE.search(raw)
    inner = body.group(1) if body else raw
    inner = _MBP_PAGEBREAK_RE.sub(f'<hr id="{_PAGEBREAK_ID}"/>', inner)
    inner = _MBP_TAG_RE.sub("", inner)
    return _SELF_CLOSING_RE.sub(_close_self_closing, inner)


def split_chapters(raw: str) -> list[str]:
    """Split MOBI7 HTML on its page breaks into XHTML body fragments."""
    root = html.fragment_fromstring(_prepare_html(raw), create_parent="div")
    chunks: list[list[str]] = [[]]
    if root.text and root.text.strip():
        chunks[-1].append(escape(root.text))
    for el in root:
        if el.tag == "hr" and el.get("id") == _PAGEBREAK_ID:
            chunks.append([])
            if el.tail and el.tail.strip():
                chunks[-1].append(escape(el.tail))
            continue
        # One element per line: the text extractor reads paragraph breaks
        # from newlines, and Mobipocket HTML has none.
        chunks[-1].append(html.tostring(el, method="xml", encoding="unicode") + "\n")
    return ["".join(c) for c in chunks if "".join(c).strip()]


_ID_RE = re.compile(r'\sid="([^"]+)"')
_HREF_RE = re.compile(r'href="#([^"]+)"')


def pack_mobi7(src_dir: str, out_path: str) -> None:
    meta = _read_opf(os.path.join(src_dir, "content.opf"))
    points = _read_ncx(os.path.join(src_dir, "toc.ncx"))
    raw = open(os.path.join(src_dir, "book.html"), encoding="utf-8").read()
    chapters = split_chapters(raw)
    if not chapters:
        raise MobiError("The book has no text")

    hrefs = [f"text{i + 1:04d}.xhtml" for i in range(len(chapters))]
    anchor_file: dict[str, str] = {}
    for href, body in zip(hrefs, chapters, strict=True):
        for anchor in _ID_RE.findall(body):
            anchor_file.setdefault(anchor, href)

    def relink(m: re.Match[str]) -> str:
        target = anchor_file.get(m.group(1))
        return f'href="{target}#{m.group(1)}"' if target else m.group(0)

    lang = escape(meta.language)
    title = escape(meta.title)
    files = []
    for href, body in zip(hrefs, chapters, strict=True):
        files.append(
            (
                href,
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml" '
                f'xml:lang="{lang}">\n<head>\n<meta charset="utf-8"/>\n'
                f"<title>{title}</title>\n</head>\n<body>\n"
                f"{_HREF_RE.sub(relink, body)}\n</body>\n</html>\n",
            )
        )

    # TOC entries whose anchor we can place; a book with none gets a
    # single entry so the nav is never empty.
    toc = []
    for label, frag in points:
        file = anchor_file.get(frag)
        if file:
            toc.append((label, f"{file}#{frag}"))
    if not toc:
        toc = [(meta.title, hrefs[0])]

    images = []
    image_dir = os.path.join(src_dir, "Images")
    if os.path.isdir(image_dir):
        for name in sorted(os.listdir(image_dir)):
            mime = mimetypes.guess_type(name)[0]
            if mime and mime.startswith("image/"):
                images.append((f"Images/{name}", mime))

    uid = f"urn:uuid:{uuid.uuid4()}"
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
    ]
    spine = []
    for i, (href, _) in enumerate(files, start=1):
        manifest.append(
            f'<item id="s{i:04d}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="s{i:04d}"/>')
    cover_meta = ""
    for i, (href, mime) in enumerate(images, start=1):
        is_cover = href == meta.cover_href
        item_id = "cover-image" if is_cover else f"img{i:04d}"
        props = ' properties="cover-image"' if is_cover else ""
        manifest.append(
            f'<item id="{item_id}" href="{href}" media-type="{mime}"{props}/>'
        )
        if is_cover:
            cover_meta = '    <meta name="cover" content="cover-image"/>\n'
    creators = "".join(
        f"    <dc:creator>{escape(a)}</dc:creator>\n" for a in meta.authors
    )
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="uid" xml:lang="{lang}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
        f"    <dc:title>{title}</dc:title>\n"
        f"{creators}"
        f"    <dc:language>{lang}</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        f"{cover_meta}"
        "  </metadata>\n"
        "  <manifest>\n    " + "\n    ".join(manifest) + "\n  </manifest>\n"
        '  <spine toc="ncx">\n    ' + "\n    ".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )
    nav_items = "".join(
        f'<li><a href="{href}">{escape(label)}</a></li>\n' for label, href in toc
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{title}</title>\n</head>\n<body>\n'
        '<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n<ol>\n'
        f"{nav_items}</ol>\n</nav>\n</body>\n</html>\n"
    )
    nav_points = "".join(
        f'    <navPoint id="np{i}" playOrder="{i}"><navLabel><text>{escape(label)}'
        f'</text></navLabel><content src="{href}"/></navPoint>\n'
        for i, (label, href) in enumerate(toc, start=1)
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="{uid}"/>\n'
        '    <meta name="dtb:depth" content="1"/>\n'
        '    <meta name="dtb:totalPageCount" content="0"/>\n'
        '    <meta name="dtb:maxPageNumber" content="0"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{title}</text></docTitle>\n"
        "  <navMap>\n"
        f"{nav_points}"
        "  </navMap>\n"
        "</ncx>\n"
    )

    with zipfile.ZipFile(out_path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        for name, data in (
            ("META-INF/container.xml", _CONTAINER),
            ("OEBPS/content.opf", opf),
            ("OEBPS/nav.xhtml", nav),
            ("OEBPS/toc.ncx", ncx),
        ):
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        for href, xhtml in files:
            zf.writestr(f"OEBPS/{href}", xhtml, compress_type=zipfile.ZIP_DEFLATED)
        for href, _ in images:
            zf.write(os.path.join(src_dir, href), f"OEBPS/{href}")
