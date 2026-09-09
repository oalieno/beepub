"""MOBI/AZW3 → EPUB: KF8 unpacks to an EPUB (uid scrubbed), MOBI7 is
split on page breaks and packed, and the pipeline reads the result."""

import zipfile
from pathlib import Path

import pytest

from app.services.epub_parser import extract_cover, parse_epub_metadata
from app.services.epub_text import extract_full_text
from app.services.mobi2epub import MobiError, convert_mobi_to_epub, split_chapters

FIXTURES = Path(__file__).parent / "fixtures"
AZW3 = FIXTURES / "windmill_postman.azw3"
MOBI7 = FIXTURES / "ferry_last_boat.mobi"


def _convert(src: Path, tmp_path: Path) -> Path:
    out = tmp_path / "book.epub"
    convert_mobi_to_epub(str(src), str(out))
    return out


def test_azw3_unpacks_to_an_epub_the_pipeline_reads(tmp_path):
    out = _convert(AZW3, tmp_path)
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist()[0] == "mimetype"
        assert zf.read("mimetype") == b"application/epub+zip"
        opf = zf.read("OEBPS/content.opf").decode()
    # The Kindle uid (a random number) is not an identifier of any scheme.
    assert "urn:uuid:" in opf
    metadata = parse_epub_metadata(str(out))
    assert metadata["epub_title"] == "風車島郵差"
    assert metadata["epub_authors"] == ["林秋水"]
    assert metadata["epub_isbn"] is None
    assert extract_cover(str(out), str(tmp_path / "cover.jpg"))

    chunks = extract_full_text(str(out))
    titles = [c.section_title for c in chunks]
    assert "第二章 沒有地址的信" in titles
    assert any("郵差把信放進口袋" in c.text for c in chunks)


def test_mobi7_is_split_on_page_breaks_and_packed(tmp_path):
    out = _convert(MOBI7, tmp_path)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        texts = sorted(n for n in names if n.startswith("OEBPS/text"))
        # Three chapters plus calibre's own table-of-contents page.
        assert len(texts) == 4
        assert "OEBPS/nav.xhtml" in names
        assert "OEBPS/Images/cover00006.jpeg" in names
        nav = zf.read("OEBPS/nav.xhtml").decode()
        ncx = zf.read("OEBPS/toc.ncx").decode()
        chapter2 = zf.read("OEBPS/text0002.xhtml").decode()
        toc_page = zf.read("OEBPS/text0004.xhtml").decode()
        opf = zf.read("OEBPS/content.opf").decode()

    # TOC targets and in-book links point into the split files.
    assert 'href="text0002.xhtml#filepos392">第二章 竹籃' in nav
    assert 'src="text0003.xhtml#filepos772"' in ncx
    assert 'href="text0001.xhtml#filepos109"' in toc_page
    # Well-formed XHTML: the anchor is closed, the image self-closes.
    assert '<a id="filepos392"/>' in chapter2
    assert 'src="Images/cover00006.jpeg"' in chapter2 and "</img>" not in chapter2
    assert 'properties="cover-image"' in opf

    metadata = parse_epub_metadata(str(out))
    assert metadata["epub_title"] == "渡口的最後一班船"
    assert metadata["epub_authors"] == ["周硯"]
    assert extract_cover(str(out), str(tmp_path / "cover.jpg"))

    chunks = extract_full_text(str(out))
    assert chunks[0].section_title == "第一章 末班船"
    assert chunks[1].text.split("\n")[:2] == [
        "第二章 竹籃",
        "竹籃裡是一疊信，每一封都貼著同一枚舊郵票。",
    ]


def test_split_chapters_smooths_mobipocket_markup():
    raw = (
        "<html><head><guide><reference type='toc' filepos=0000000010 /></guide></head>"
        '<body><a id="filepos1" /><p>One<mbp:nu>x</mbp:nu></p><mbp:pagebreak/>'
        '<a id="filepos2" /><p>Two &amp; a half</p><br/>'
        "<mbp:pagebreak /><p>Three</p></body></html>"
    )
    chunks = split_chapters(raw)
    assert len(chunks) == 3
    # The self-closing anchor did not swallow the paragraph after it.
    assert chunks[0].startswith('<a id="filepos1"/>\n<p>Onex</p>')
    assert "mbp:" not in "".join(chunks)
    assert "Two &amp; a half" in chunks[1] and "<br/>" in chunks[1]
    assert chunks[2].strip() == "<p>Three</p>"


def test_not_a_mobi_is_rejected(tmp_path):
    src = tmp_path / "book.mobi"
    src.write_bytes(b"this is not a palm database at all" * 10)
    with pytest.raises(MobiError):
        convert_mobi_to_epub(str(src), str(tmp_path / "out.epub"))
    assert not (tmp_path / "out.epub").exists()
