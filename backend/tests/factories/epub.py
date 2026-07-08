"""Build small, structurally valid EPUBs in memory.

Tests that exercise the real upload/parse pipeline need actual EPUB bytes,
not mocks. The books produced here are EPUB 3 with EPUB 2 fallbacks (an NCX
table of contents and a ``<meta name="cover">`` entry) so both generations
of parser code find the same data.
"""

import io
import zipfile

from PIL import Image

_CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_HORIZONTAL_CSS = "body { font-family: serif; }\n"

_VERTICAL_CSS = """html {
  writing-mode: vertical-rl;
  -epub-writing-mode: vertical-rl;
  -webkit-writing-mode: vertical-rl;
}
"""

DEFAULT_CHAPTERS = [
    ("Chapter 1", ["The quick brown fox jumps over the lazy dog. " * 10]),
    ("Chapter 2", ["A second chapter with enough text to count. " * 10]),
]


def _chapter_xhtml(title: str, paragraphs: list[str]) -> str:
    body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>
"""


def _nav_xhtml(chapter_titles: list[str]) -> str:
    items = "\n".join(
        f'      <li><a href="chapter{i + 1}.xhtml">{t}</a></li>'
        for i, t in enumerate(chapter_titles)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc">
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""


def _toc_ncx(identifier: str, title: str, chapter_titles: list[str]) -> str:
    points = "\n".join(
        f"""    <navPoint id="np{i + 1}" playOrder="{i + 1}">
      <navLabel><text>{t}</text></navLabel>
      <content src="chapter{i + 1}.xhtml"/>
    </navPoint>"""
        for i, t in enumerate(chapter_titles)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{identifier}"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
{points}
  </navMap>
</ncx>
"""


def _content_opf(
    *,
    title: str,
    authors: tuple[str, ...],
    language: str,
    identifier: str,
    chapter_count: int,
    vertical: bool,
    cover: bool,
) -> str:
    creators = "\n".join(
        f'    <dc:creator id="creator{i}">{a}</dc:creator>'
        for i, a in enumerate(authors)
    )
    cover_meta = '    <meta name="cover" content="cover-image"/>\n' if cover else ""
    cover_item = (
        '    <item id="cover-image" href="cover.jpg" media-type="image/jpeg"'
        ' properties="cover-image"/>\n'
        if cover
        else ""
    )
    chapter_items = "\n".join(
        f'    <item id="chapter{i + 1}" href="chapter{i + 1}.xhtml"'
        ' media-type="application/xhtml+xml"/>'
        for i in range(chapter_count)
    )
    spine_refs = "\n".join(
        f'    <itemref idref="chapter{i + 1}"/>' for i in range(chapter_count)
    )
    ppd = ' page-progression-direction="rtl"' if vertical else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">{identifier}</dc:identifier>
    <dc:title>{title}</dc:title>
{creators}
    <dc:language>{language}</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
{cover_meta}  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
{cover_item}{chapter_items}
  </manifest>
  <spine toc="ncx"{ppd}>
{spine_refs}
  </spine>
</package>
"""


def _cover_jpeg() -> bytes:
    image = Image.new("RGB", (60, 90), (216, 148, 51))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def build_epub(
    *,
    title: str = "Test Book",
    authors: tuple[str, ...] = ("Test Author",),
    language: str = "en",
    identifier: str = "urn:uuid:00000000-0000-4000-8000-000000000001",
    chapters: list[tuple[str, list[str]]] | None = None,
    vertical: bool = False,
    cover: bool = True,
) -> bytes:
    """Return the bytes of a small valid EPUB.

    ``chapters`` is a list of ``(title, paragraphs)``. ``vertical=True``
    produces a vertical-rl book with right-to-left page progression.
    """
    if chapters is None:
        chapters = DEFAULT_CHAPTERS
    chapter_titles = [t for t, _ in chapters]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # The mimetype entry must come first and be stored uncompressed.
        zf.writestr(
            "mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr(
            "OEBPS/content.opf",
            _content_opf(
                title=title,
                authors=authors,
                language=language,
                identifier=identifier,
                chapter_count=len(chapters),
                vertical=vertical,
                cover=cover,
            ),
        )
        zf.writestr("OEBPS/nav.xhtml", _nav_xhtml(chapter_titles))
        zf.writestr("OEBPS/toc.ncx", _toc_ncx(identifier, title, chapter_titles))
        zf.writestr("OEBPS/style.css", _VERTICAL_CSS if vertical else _HORIZONTAL_CSS)
        if cover:
            zf.writestr("OEBPS/cover.jpg", _cover_jpeg())
        for i, (chapter_title, paragraphs) in enumerate(chapters):
            zf.writestr(
                f"OEBPS/chapter{i + 1}.xhtml",
                _chapter_xhtml(chapter_title, paragraphs),
            )
    return buffer.getvalue()
