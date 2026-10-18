"""Books other readers open must not be refused here: an OPF that names a
file in another letter case than the zip holds it, or lists a file the zip
does not hold at all (Calibre opens both)."""

import io
import zipfile

from PIL import Image

from app.routers.books import _read_epub_entry
from app.services.epub_parser import extract_cover, parse_epub_metadata
from app.services.epub_text import extract_full_text

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:5b0c4a2e-0000-4000-8000-000000000001</dc:identifier>
    <dc:title>燈塔守夜人的信</dc:title>
    <dc:creator>測試作者</dc:creator>
    <dc:language>zh-TW</dc:language>
    <meta name="cover" content="cover"/>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style/main.css" media-type="text/css"/>
    <item id="cover" href="Images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="cover-image-file" href="Images/cover.jpeg" media-type="image/jpeg"/>
    <item id="lost" href="Images/lost-plate.jpg" media-type="image/jpeg"/>
    <item id="cover-page" href="Text/cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="c1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="cover-page"/>
    <itemref idref="c1"/>
  </spine>
</package>"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目錄</title></head>
<body><nav epub:type="toc"><ol><li><a href="Text/chapter1.xhtml">第一章</a></li></ol></nav></body>
</html>"""

COVER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>封面</title></head>
<body><img src="../Images/cover.jpeg" alt=""/></body></html>"""

CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title>
<link rel="stylesheet" type="text/css" href="../Style/main.css"/></head>
<body><h1>第一章</h1><p>守夜人每晚點亮燈塔，寫一封寄不出去的信。</p></body></html>"""


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 90), (20, 40, 80)).save(out, "JPEG")
    return out.getvalue()


def make_book(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/nav.xhtml", NAV)
        # The OPF says style/, text/ and cover.jpg; the zip has Style/,
        # Text/ and the cover only as cover.jpeg (listed too, under another
        # id); lost-plate.jpg is nowhere.
        zf.writestr("OEBPS/Style/main.css", "p { color: rgb(1, 2, 3); }")
        zf.writestr("OEBPS/Images/cover.jpeg", jpeg())
        zf.writestr("OEBPS/Text/cover.xhtml", COVER)
        zf.writestr("OEBPS/Text/chapter1.xhtml", CHAPTER)
    return path


def test_metadata_is_read_despite_case_and_missing_files(tmp_path):
    book = make_book(tmp_path / "book.epub")
    metadata = parse_epub_metadata(str(book))
    assert metadata["epub_title"] == "燈塔守夜人的信"
    assert metadata["epub_authors"] == ["測試作者"]


def test_cover_comes_from_the_cover_page_when_the_named_file_is_missing(
    tmp_path,
):
    book = make_book(tmp_path / "book.epub")
    out = tmp_path / "cover.jpg"
    assert extract_cover(str(book), str(out))
    assert out.exists() and out.stat().st_size > 0


def test_text_of_a_chapter_named_in_another_case_is_extracted(tmp_path):
    book = make_book(tmp_path / "book.epub")
    text = " ".join(chunk.text for chunk in extract_full_text(str(book)))
    assert "守夜人每晚點亮燈塔" in text


def test_content_endpoint_finds_a_file_named_in_another_case(tmp_path):
    book = make_book(tmp_path / "book.epub")
    assert b"rgb(1, 2, 3)" in _read_epub_entry(str(book), "OEBPS/style/main.css")
    assert b"rgb(1, 2, 3)" in _read_epub_entry(str(book), "OEBPS/Style/main.css")
