"""TXT → EPUB: decoding, chapter splitting (shared vectors) and the EPUB
the rest of the pipeline consumes."""

import json
import zipfile
from pathlib import Path

import pytest

from app.services.epub_parser import parse_epub_metadata
from app.services.epub_text import extract_full_text
from app.services.txt2epub import (
    FALLBACK_CHARS,
    EmptyTextError,
    classify_heading,
    decode_text,
    detect_language,
    parse_txt,
    split_sections,
    write_epub,
)

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "txt_chapter_vectors.json").read_text(
        encoding="utf-8"
    )
)["cases"]


# --- decoding ---------------------------------------------------------------


@pytest.mark.parametrize(
    "encoding,text",
    [
        ("utf-8", "第一章 測試\n他們說這個國家。"),
        ("utf-8-sig", "第一章 測試\n他們說這個國家。"),
        ("utf-16", "第一章 測試\n他們說這個國家。"),
        ("cp950", "第一章 測試\n他們說這個國家，來的時候就會學到。"),
        ("gb18030", "第一章 测试\n他们说这个国家，来的时候就会学到。"),
        ("cp1252", "Chapter 1\nShe said “hello” — and left."),
    ],
)
def test_decode_round_trips(encoding, text):
    decoded, found = decode_text(text.encode(encoding))
    assert decoded == text
    expected = {"utf-16": ("utf-16-le", "utf-16-be")}.get(encoding, (encoding,))
    assert found in expected


def test_mostly_utf8_with_a_stray_byte_stays_utf8():
    data = "第一章 測試\n他們說這個國家。\n".encode() + b"\xff" + "再來一段。".encode()
    decoded, found = decode_text(data)
    assert found == "utf-8"
    assert "他們說這個國家" in decoded and "再來一段" in decoded


@pytest.mark.parametrize(
    "text,encoding,language",
    [
        ("他們說這個國家來了", "utf-8", "zh-TW"),
        ("他们说这个国家来了", "utf-8", "zh-CN"),
        ("他們說這個國家來了", "cp950", "zh-TW"),
        ("他们说这个国家来了", "gb18030", "zh-CN"),
        ("The cook kept a ledger.", "utf-8", "en"),
        ("彼女は灯台を見た。それから帰った。", "utf-8", "ja"),
    ],
)
def test_detect_language(text, encoding, language):
    assert detect_language(text, encoding) == language


# --- headings ---------------------------------------------------------------


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_chapter_vectors(case):
    title, author, sections = split_sections(case["text"], case["title_hint"])
    assert title == case["expect"]["title"]
    assert author == case["expect"]["author"]
    assert [
        {"title": s.title, "level": s.level, "paragraphs": len(s.paragraphs)}
        for s in sections
    ] == case["expect"]["sections"]


@pytest.mark.parametrize(
    "line",
    [
        "第三章的開頭寫道，他來了。",
        "第二章，她說",
        "第一章" + "很長的標題" * 20,
        "",
        "退潮之後，沙灘上留著昨夜的腳印",
        "chapters are not headings",
    ],
)
def test_lines_that_are_not_headings(line):
    assert classify_heading(line) is None


def test_no_headings_fall_back_to_size_chunks_with_preview_titles():
    para = "退潮之後沙灘上留著昨夜的腳印她把鐘樓的鑰匙放回口袋" * 60  # 1500 chars
    text = "\n\n".join([para] * 9)  # 13.5k chars → three chunks of ≤ 6000
    title, _author, sections = split_sections(text, "無章節")
    assert title == "無章節"
    assert len(sections) == 3
    assert all(sum(map(len, s.paragraphs)) <= FALLBACK_CHARS for s in sections)
    assert sections[0].title == para[:20] + "…"


def test_short_text_without_headings_is_one_section_named_after_the_book():
    _title, _author, sections = split_sections("只有一行。", "短篇")
    assert [(s.title, s.paragraphs) for s in sections] == [("短篇", ["只有一行。"])]


def test_empty_file_is_rejected():
    with pytest.raises(EmptyTextError):
        parse_txt(b"\n\n  \n", "x")


# --- epub -------------------------------------------------------------------


def _build(tmp_path, text: str, title_hint: str = "book") -> str:
    out = str(tmp_path / "out.epub")
    write_epub(parse_txt(text.encode(), title_hint), out)
    return out


def test_epub_is_a_valid_container_the_pipeline_can_read(tmp_path):
    text = VECTORS[2]["text"]  # 《潮汐鐘樓手記》 with parts, author, TOC dump
    out = _build(tmp_path, text)

    with zipfile.ZipFile(out) as zf:
        assert zf.namelist()[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        nav = zf.read("OEBPS/nav.xhtml").decode()
    # The part is a nested node pointing at its first chapter.
    assert nav.index("第一卷 潮聲") < nav.index("第一章 退潮")
    assert nav.count("<ol>") == 2

    meta = parse_epub_metadata(out)
    assert meta["epub_title"] == "潮汐鐘樓手記"
    assert meta["epub_authors"] == ["林未晞"]
    assert meta["epub_language"] == "zh-TW"

    chunks = extract_full_text(out)
    assert [c.section_title for c in chunks] == ["第一章 退潮", "第二章 鐘擺"]
    assert "退潮。" in chunks[0].text


def test_markup_in_the_text_is_escaped(tmp_path):
    out = _build(tmp_path, "第一章 <b>&amp; x\n1 < 2 && 3 > 2 <script>x</script>\n")
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("OEBPS/text/0001.xhtml").decode()
    assert "<script>" not in xhtml
    assert "&lt;script&gt;" in xhtml
    assert "<h2>第一章 &lt;b&gt;&amp;amp; x</h2>" in xhtml
    assert [c.text.strip() for c in extract_full_text(out)][0].endswith(
        "1 < 2 && 3 > 2 <script>x</script>"
    )
