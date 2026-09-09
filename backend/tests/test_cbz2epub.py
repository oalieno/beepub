"""CBZ → pre-paginated EPUB: pages in natural order, ComicInfo into the
OPF, first page as cover, and a page manifest the pager can read."""

import zipfile
from pathlib import Path

import pytest

from app.services.cbz2epub import (
    CbzError,
    convert_cbz_to_epub,
    natural_key,
    read_comic_info,
)
from app.services.epub_pages import read_page_manifest
from app.services.epub_parser import extract_cover, parse_epub_metadata
from app.services.epub_text import extract_full_text
from tests.factories.cbz import LANDSCAPE, PORTRAIT, build_cbz, comic_info_xml


def _convert(data: bytes, tmp_path: Path, name="book.cbz") -> Path:
    src = tmp_path / name
    src.write_bytes(data)
    out = tmp_path / "book.epub"
    convert_cbz_to_epub(str(src), str(out))
    return out


def test_manga_cbz_becomes_a_right_to_left_fixed_layout_epub(tmp_path):
    info = comic_info_xml(
        title="月台小提琴手 第1話",
        series="月台小提琴手",
        number="1",
        writer="周霜, 小野寺",
        publisher="夜行社",
        summary="末班車之後，月台上還有琴聲。",
        year="2024",
        language="zh",
        genre="Drama, Slice of Life",
        manga="YesAndRightToLeft",
    )
    pages = [PORTRAIT, PORTRAIT, LANDSCAPE, PORTRAIT]
    out = _convert(build_cbz(pages, comic_info=info), tmp_path)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        opf = zf.read("OEBPS/content.opf").decode()
        page3 = zf.read("OEBPS/page0003.xhtml").decode()
        # Page images are stored, not deflated twice.
        assert zf.getinfo("OEBPS/images/0001.jpg").compress_type == zipfile.ZIP_STORED
    assert sum(n.startswith("OEBPS/page") for n in names) == 4
    assert '<meta property="rendition:layout">pre-paginated</meta>' in opf
    assert '<spine page-progression-direction="rtl">' in opf
    assert 'properties="cover-image"' in opf
    assert '<meta name="calibre:series" content="月台小提琴手"/>' in opf
    assert '<meta name="calibre:series_index" content="1"/>' in opf
    assert "<dc:subject>Slice of Life</dc:subject>" in opf
    # The wide page carries its true size.
    assert '<meta name="viewport" content="width=1600, height=1200"/>' in page3
    assert 'src="images/0003.jpg"' in page3

    metadata = parse_epub_metadata(str(out))
    assert metadata["epub_title"] == "月台小提琴手 第1話"
    assert metadata["epub_authors"] == ["周霜", "小野寺"]
    assert metadata["epub_publisher"] == "夜行社"
    assert metadata["epub_series"] == "月台小提琴手"
    assert metadata["epub_series_index"] == 1.0
    assert metadata["epub_language"] == "zh"
    assert metadata["epub_published_date"] == "2024"
    assert metadata["epub_tags"] == ["Drama", "Slice of Life"]
    assert extract_cover(str(out), str(tmp_path / "cover.jpg"))
    # No text for the pipeline: an image book by construction.
    assert extract_full_text(str(out)) == []

    manifest = read_page_manifest(str(out))
    assert manifest.layout == "pre-paginated"
    assert manifest.direction == "rtl"
    assert [p.image for p in manifest.pages] == [
        f"OEBPS/images/{i:04d}.jpg" for i in range(1, 5)
    ]
    assert [(p.width, p.height) for p in manifest.pages] == pages
    assert all(p.linear and p.spread is None for p in manifest.pages)


def test_pages_sort_naturally_and_junk_entries_are_skipped(tmp_path):
    names = ["10.jpg", "2.jpg", "1.jpg", "vol1/3.png", "vol1/11.jpg"]
    data = build_cbz(
        [PORTRAIT] * 5,
        names=names,
        extra={
            "__MACOSX/._1.jpg": b"resource fork",
            ".hidden.jpg": b"not a page",
            "notes.txt": b"ignored",
            "broken.jpg": b"not really an image",
        },
    )
    out = _convert(data, tmp_path, "月台小提琴手.cbz")
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("OEBPS/content.opf").decode()
        images = sorted(n for n in zf.namelist() if n.startswith("OEBPS/images/"))
    # The order is 1, 2, 3, 10, 11 — broken.jpg (unreadable) is dropped.
    assert images == [
        "OEBPS/images/0001.jpg",
        "OEBPS/images/0002.jpg",
        "OEBPS/images/0003.jpg",
        "OEBPS/images/0004.png",
        "OEBPS/images/0005.jpg",
    ]
    # Without ComicInfo the title is the file name.
    assert "<dc:title>月台小提琴手</dc:title>" in opf
    assert "<dc:language>und</dc:language>" in opf
    assert "page-progression-direction" not in opf
    assert read_page_manifest(str(out)).direction == "default"


def test_series_and_number_name_an_untitled_issue():
    info = read_comic_info(
        comic_info_xml(series="霧港夜航", number="2.5", manga="Yes", year="abcd")
    )
    assert info.series == "霧港夜航"
    assert info.number == 2.5
    assert info.rtl is False
    assert info.published is None
    assert read_comic_info(b"<not xml").title is None


def test_natural_key_orders_numbers_by_value():
    names = ["p10.jpg", "p2.jpg", "p1.jpg", "P3.jpg"]
    assert sorted(names, key=natural_key) == ["p1.jpg", "p2.jpg", "P3.jpg", "p10.jpg"]


def test_bad_archives_are_rejected_and_leave_no_output(tmp_path):
    for name, data in [
        ("garbage.cbz", b"not a zip at all"),
        ("empty.cbz", build_cbz(0)),
        ("text-only.cbz", build_cbz(0, extra={"readme.txt": b"hi"})),
    ]:
        with pytest.raises(CbzError):
            _convert(data, tmp_path, name)
        assert not (tmp_path / "book.epub").exists()
