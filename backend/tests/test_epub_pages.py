"""The page manifest reads any EPUB's spine: a text book has pages without
images, a bought manga's SVG-wrapped pages resolve to their image and keep
their spread hints, and a cover page marked linear=no says so."""

import io
import zipfile

from app.services.epub_pages import read_page_manifest
from tests.factories.cbz import LANDSCAPE, PORTRAIT, page_image
from tests.factories.epub import build_epub

_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="item/standard.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


def _svg_page(image: str, w: int, h: int) -> str:
    """The page shape BookWalker/Kobo manga EPUBs use: an SVG viewBox
    wrapping the image, with no viewport meta."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        "<head><title>p</title></head><body>\n"
        '<div class="main"><svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {w} {h}">'
        f'<image width="{w}" height="{h}" xlink:href="../image/{image}"/></svg></div>\n'
        "</body></html>\n"
    )


def _commercial_manga(tmp_path) -> str:
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"
  prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:1</dc:identifier><dc:title>m</dc:title><dc:language>ja</dc:language>
    <meta property="rendition:layout">pre-paginated</meta>
  </metadata>
  <manifest>
    <item id="cover" href="xhtml/p-cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="p1" href="xhtml/p-001.xhtml" media-type="application/xhtml+xml"/>
    <item id="p2" href="xhtml/p-002.xhtml" media-type="application/xhtml+xml"/>
    <item id="p3" href="xhtml/p-003.xhtml" media-type="application/xhtml+xml"/>
    <item id="i0" href="image/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="i1" href="image/001.jpg" media-type="image/jpeg"/>
    <item id="i2" href="image/002.jpg" media-type="image/jpeg"/>
    <item id="i3" href="image/003.jpg" media-type="image/jpeg"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine page-progression-direction="rtl">
    <itemref idref="cover" linear="no" properties="rendition:page-spread-center"/>
    <itemref idref="p1" properties="page-spread-left"/>
    <itemref idref="p2" properties="page-spread-right"/>
    <itemref idref="p3" properties="page-spread-left"/>
  </spine>
</package>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", _CONTAINER)
        zf.writestr("item/standard.opf", opf)
        zf.writestr("item/nav.xhtml", "<html/>")
        for name, img, size in [
            ("p-cover", "cover.jpg", PORTRAIT),
            ("p-001", "001.jpg", PORTRAIT),
            ("p-002", "002.jpg", PORTRAIT),
            ("p-003", "003.jpg", LANDSCAPE),
        ]:
            zf.writestr(f"item/xhtml/{name}.xhtml", _svg_page(img, *size))
            zf.writestr(f"item/image/{img}", page_image(1, size))
    path = tmp_path / "manga.epub"
    path.write_bytes(buf.getvalue())
    return str(path)


def test_text_book_pages_have_no_image(tmp_path):
    path = tmp_path / "text.epub"
    path.write_bytes(build_epub())
    manifest = read_page_manifest(str(path))
    assert manifest.layout == "reflowable"
    assert manifest.direction == "default"
    assert len(manifest.pages) >= 2
    assert all(p.image is None and p.linear for p in manifest.pages)


def test_commercial_manga_pages_resolve_svg_images_and_spreads(tmp_path):
    manifest = read_page_manifest(_commercial_manga(tmp_path))
    assert manifest.layout == "pre-paginated"
    assert manifest.direction == "rtl"
    assert [p.href for p in manifest.pages] == [
        "item/xhtml/p-cover.xhtml",
        "item/xhtml/p-001.xhtml",
        "item/xhtml/p-002.xhtml",
        "item/xhtml/p-003.xhtml",
    ]
    assert [p.image for p in manifest.pages] == [
        "item/image/cover.jpg",
        "item/image/001.jpg",
        "item/image/002.jpg",
        "item/image/003.jpg",
    ]
    assert [p.spread for p in manifest.pages] == ["center", "left", "right", "left"]
    assert [p.linear for p in manifest.pages] == [False, True, True, True]
    # No viewport meta: sizes come from the image headers.
    assert (manifest.pages[3].width, manifest.pages[3].height) == LANDSCAPE
    assert manifest.to_dict()["pages"][0]["index"] == 0
