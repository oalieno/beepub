"""The image-book rule: at least 80% of a book's linear spine items are
picture pages — pages whose body says nothing once whitespace, digits,
punctuation and symbols are gone. Built as real EPUBs, read through the
same parser the extraction uses."""

import zipfile

import pytest

from app.services.epub_text import (
    classify_image_book,
    extract_book_text,
    is_picture_text,
)

PICTURE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Page {n}</title>
<style>p {{ color: red; }}</style></head>
<body><div><img src="../images/{n:04d}.jpg" alt=""/></div><ploc>{n}</ploc></body></html>"""

PROSE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1>{title}</h1><p>{body}</p></body></html>"""

CAPTIONED = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Page {n}</title></head>
<body><img src="../images/{n:04d}.jpg" alt=""/><p>The fox hid under page {n}.</p></body></html>"""


def make_epub(path, pages: list[tuple[str, str, bool]], layout: str | None = None):
    """pages: (id, xhtml, linear)."""
    manifest = "".join(
        f'<item id="{pid}" href="text/{pid}.xhtml" media-type="application/xhtml+xml"/>'
        for pid, _, _ in pages
    )
    spine = "".join(
        f'<itemref idref="{pid}"{"" if linear else ' linear="no"'}/>'
        for pid, _, linear in pages
    )
    rendition = f'<meta property="rendition:layout">{layout}</meta>' if layout else ""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="uid">urn:uuid:image-book-rule</dc:identifier>
<dc:title>Rule</dc:title><dc:language>en</dc:language>{rendition}
</metadata>
<manifest>{manifest}</manifest>
<spine>{spine}</spine>
</package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        zf.writestr("OEBPS/content.opf", opf)
        for pid, xhtml, _ in pages:
            zf.writestr(f"OEBPS/text/{pid}.xhtml", xhtml)
    return str(path)


def pictures(count: int, start: int = 1):
    return [
        (f"p{n:04d}", PICTURE.format(n=n), True) for n in range(start, start + count)
    ]


def prose(pid: str, title: str, body: str, linear: bool = True):
    return (pid, PROSE.format(title=title, body=body), linear)


STORY = " ".join(["The lighthouse keeper wrote another letter home."] * 57)


class TestPictureText:
    @pytest.mark.parametrize(
        "text", ["", "  \n ", "12", "- 12 -", "１２", "…", "★☆", "(３)", "　"]
    )
    def test_nothing_left_is_a_picture(self, text):
        assert is_picture_text(text)

    @pytest.mark.parametrize("text", ["The cat sat.", "ねこ", "第1巻", "a"])
    def test_any_letter_is_text(self, text):
        assert not is_picture_text(text)


class TestImageBookRule:
    def test_580_numbered_pages_are_an_image_book(self, tmp_path):
        path = make_epub(tmp_path / "manga.epub", pictures(580))
        assert classify_image_book(path) is True

    def test_147_pictures_with_toc_nav_authors_colophon_are_an_image_book(
        self, tmp_path
    ):
        pages = [
            prose("toc", "目次", "第一話 始まりの駅 第二話 夜汽車 第三話 終点"),
            prose("nav", "Contents", "Chapter one, Chapter two, Chapter three"),
            *pictures(147),
            prose("authors", "著者紹介", "作者は東京生まれの漫画家。代表作は多数。"),
            prose(
                "colophon", "奥付", "発行日 2024年1月1日 発行者 某出版社 印刷所 某印刷"
            ),
        ]
        path = make_epub(tmp_path / "manga.epub", pages)
        assert classify_image_book(path) is True

    def test_fixed_layout_picture_book_with_a_sentence_a_page_is_text(self, tmp_path):
        pages = [(f"p{n:02d}", CAPTIONED.format(n=n), True) for n in range(1, 25)]
        path = make_epub(tmp_path / "picture.epub", pages, layout="pre-paginated")
        assert classify_image_book(path) is False

    def test_one_section_400_word_story_is_text(self, tmp_path):
        assert len(STORY.split()) < 500
        path = make_epub(tmp_path / "story.epub", [prose("c1", "Story", STORY)])
        assert classify_image_book(path) is False

    def test_non_linear_items_are_not_counted(self, tmp_path):
        # 8 pictures and 2 prose pages in the spine: 80%, an image book —
        # however much non-linear text rides along.
        pages = [
            *pictures(8),
            prose("credits", "Credits", "Drawn by someone, lettered by another"),
            prose("about", "About", "A short note about the series"),
            *[prose(f"extra{n}", "Extra", STORY, linear=False) for n in range(10)],
        ]
        path = make_epub(tmp_path / "manga.epub", pages)
        assert classify_image_book(path) is True
        # One prose page more in the spine and it is under 80%: text.
        pages.insert(0, prose("intro", "Intro", "A word before we begin"))
        path = make_epub(tmp_path / "manga2.epub", pages)
        assert classify_image_book(path) is False

    def test_head_text_is_not_the_page(self, tmp_path):
        # Every picture page has a <title> and a <style>; only the body
        # counts. The chunks keep the page numbers as their text.
        path = make_epub(tmp_path / "manga.epub", pictures(3))
        extracted = extract_book_text(path)
        assert extracted.pictures.linear == 3
        assert extracted.pictures.pictures == 3
        assert extracted.pictures.is_image_book
        assert [c.text for c in extracted.chunks] == ["1", "2", "3"]

    def test_classification_sees_past_the_chunk_limit(self, tmp_path):
        pages = [prose("c1", "Story", STORY), *pictures(10)]
        path = make_epub(tmp_path / "late.epub", pages)
        extracted = extract_book_text(path, max_chars=100)
        assert extracted.pictures.linear == 11
        assert extracted.pictures.pictures == 10
