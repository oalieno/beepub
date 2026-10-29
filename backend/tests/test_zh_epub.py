"""Simplified-to-Traditional conversion of EPUBs and their highlights."""

import io
import zipfile

from app.services.zh_epub import (
    Quote,
    convert_document,
    convert_epub,
    convert_mapped,
    convert_opf,
    convert_quote,
    locate,
    preview,
    sample_text,
    section_of,
)
from tests.factories.epub import build_epub


def _doc(body: str, lang: str = "zh-CN") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">\n'
        "<head><title>第一章 缆绳</title><style>p::before { content: '软件'; }</style></head>\n"
        f"<body>{body}</body>\n</html>\n"
    )


def test_mapping_follows_a_phrase_that_changes_length():
    mapped = convert_mapped("他用U盘拷视频。", "s2twp")
    assert mapped.new == "他用隨身碟拷影片。"
    # 拷 sits after the replaced phrase: shifted by one.
    assert mapped.new[mapped.pos[4]] == "拷"
    assert mapped.pos[len(mapped.old)] == len(mapped.new)


def test_character_mode_maps_one_to_one():
    mapped = convert_mapped("头发很长", "s2tw")
    assert mapped.new == "頭髮很長"
    assert list(mapped.pos) == [0, 1, 2, 3, 4]


def test_document_keeps_its_markup_and_converts_its_text():
    raw = _doc("<h1>第一章 缆绳</h1><p>他剪了<em>头</em>发，&amp;拷了视频。</p>")
    out, mapped = convert_document(raw, "s2twp")
    # Context reaches across the inline tag: 头|发 is 頭髮, not 頭發.
    assert "<p>他剪了<em>頭</em>髮，&amp;拷了影片。</p>" in out
    assert "<title>第一章 纜繩</title>" in out
    assert "content: '软件'" in out  # style is not text
    assert 'xml:lang="zh-TW" lang="zh-TW"' in out
    assert mapped.old == "第一章 缆绳他剪了头发，&拷了视频。"
    assert mapped.new == "第一章 纜繩他剪了頭髮，&拷了影片。"


def test_untouched_document_comes_back_byte_identical():
    raw = _doc("<p>退潮之後，沙灘上留著昨夜的腳印。</p>", lang="zh-TW")
    out, _ = convert_document(raw, "s2twp")
    assert out == raw.replace("缆绳", "纜繩")


def test_half_a_phrase_highlight_reads_as_the_book_does():
    # The highlight starts on 发 of 头发: alone, 发 would become 發.
    body = "他剪了头发，拷了视频。"
    mapped = convert_mapped(body, "s2twp")
    quote = Quote(text="发，拷了视", prefix="他剪了头", suffix="频。")
    converted = convert_quote(quote, mapped, "s2twp")
    assert converted.text == "髮，拷了影"
    assert converted.prefix == "他剪了頭"
    assert converted.suffix == "片。"
    assert converted.text in mapped.new


def test_ambiguous_quote_falls_back_to_converting_with_its_context():
    body = "头发。头发。"
    mapped = convert_mapped(body, "s2tw")
    assert locate(body, Quote("发", None, None)) is None
    converted = convert_quote(Quote("发", "头", "。"), mapped, "s2tw")
    assert converted.text == "髮"


def test_context_picks_between_repeated_quotes():
    body = "甲说：好的。乙说：好的。"
    found = locate(body, Quote("好的", "乙说：", "。"))
    assert found == (9, 11)


def test_opf_metadata_converts_names_by_character_and_prose_by_mode():
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>软件小子</dc:title><dc:creator>陈默</dc:creator>"
        "<dc:language>zh-CN</dc:language>"
        "<dc:description>一个软件工程师的故事</dc:description>"
        '<meta name="calibre:series" content="雾港系列"/>'
        '<meta property="dcterms:modified">2026-01-01</meta>'
        "</metadata></package>"
    )
    out = convert_opf(opf, "s2twp")
    assert "<dc:title>軟件小子</dc:title>" in out
    assert "<dc:creator>陳默</dc:creator>" in out
    assert "<dc:language>zh-TW</dc:language>" in out
    assert "一個軟體工程師的故事" in out
    assert 'content="霧港系列"' in out


def _simplified_epub() -> bytes:
    return build_epub(
        title="雾港夜航",
        authors=("陈默",),
        language="zh-CN",
        chapters=[
            ("序", ["没有灯的船在雾里等潮。"]),
            ("第一章", ["缆绳解开的时候，软件工程师看着视频。"]),
        ],
    )


def test_epub_is_rewritten_entry_for_entry(tmp_path):
    src = tmp_path / "in.epub"
    dst = tmp_path / "out.epub"
    src.write_bytes(_simplified_epub())
    result = convert_epub(str(src), str(dst), "s2twp")
    assert result.changed
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        assert [i.filename for i in a.infolist()] == [i.filename for i in b.infolist()]
        assert b.infolist()[0].filename == "mimetype"
        assert b.infolist()[0].compress_type == zipfile.ZIP_STORED
        chapter = b.read("OEBPS/chapter2.xhtml").decode()
        assert "纜繩解開的時候，軟體工程師看著影片。" in chapter
        assert b.read("OEBPS/cover.jpg") == a.read("OEBPS/cover.jpg")
        assert "霧港夜航" in b.read("OEBPS/toc.ncx").decode()
        assert (
            "<dc:language>zh-TW</dc:language>" in b.read("OEBPS/content.opf").decode()
        )
    # Spine order: nav is not in the factory's spine, chapters are 0 and 1.
    assert "缆绳" in result.sections[1].old
    assert "纜繩" in result.sections[1].new


def test_preview_picks_a_sentence_the_phrase_option_changes(tmp_path):
    src = tmp_path / "in.epub"
    src.write_bytes(_simplified_epub())
    segments = preview(str(src))
    # Chapter one's first sentence, not the synopsis: only it has wording
    # that s2twp rewrites.
    assert "".join(s.before for s in segments) == "缆绳解开的时候，软件工程师看着视频。"
    assert "".join(s.chars for s in segments) == "纜繩解開的時候，軟件工程師看著視頻。"
    assert (
        "".join(s.phrases for s in segments) == "纜繩解開的時候，軟體工程師看著影片。"
    )
    # Pieces come apart where the kind of change does: unchanged, a
    # character change, a wording change.
    phrases = [(s.chars, s.phrases) for s in segments if s.chars != s.phrases]
    assert phrases == [("軟件", "軟體"), ("視頻", "影片")]
    assert ("的", "的", "的") in [(s.before, s.chars, s.phrases) for s in segments]
    assert "缆绳" in sample_text(str(src))


def test_preview_skips_contents_lines_and_unchanged_text(tmp_path):
    src = tmp_path / "toc.epub"
    src.write_bytes(
        build_epub(
            language="zh-CN",
            chapters=[
                ("目录", ["关于本书", "第一章 出走", "第二章 归来"]),
                ("第一章", ["他在码头等了很久，直到天色暗了下来。"]),
            ],
        )
    )
    segments = preview(str(src))
    assert "".join(s.before for s in segments) == "他在码头等了很久，直到天色暗了下来。"

    traditional = tmp_path / "tw.epub"
    traditional.write_bytes(
        build_epub(language="zh-TW", chapters=[("一", ["退潮之後，沙灘上留著腳印。"])])
    )
    assert preview(str(traditional)) is None


def test_section_comes_from_the_cfi_when_not_stored():
    assert section_of("epubcfi(/6/4!/4/2,/1:0,/1:3)", None) == 1
    assert section_of("epubcfi(/6/4!/4/2,/1:0,/1:3)", 7) == 7
    assert section_of("garbage", None) is None


def test_factory_epub_is_readable():
    assert zipfile.ZipFile(io.BytesIO(_simplified_epub())).testzip() is None


def _book_file(tmp_path, language: str, paragraph: str) -> str:
    path = tmp_path / f"{language or 'none'}.epub"
    path.write_bytes(build_epub(language=language, chapters=[("一", [paragraph * 20])]))
    return str(path)


def test_language_follows_plainly_chinese_text(tmp_path):
    from app.services.epub_parser import book_language

    simplified = "没有灯的船在雾里等潮，缆绳解开的时候。"
    traditional = "退潮之後，沙灘上留著昨夜的腳印與鐘聲。"
    # calibre's default "en" on a Traditional book; "en" listed before "zh".
    path = _book_file(tmp_path, "en", traditional)
    assert book_language(["en"], path) == "zh-TW"
    path = _book_file(tmp_path, "en", simplified)
    assert book_language(["en", "zh"], path) == "zh-CN"
    # A declared language that agrees with the text is kept as written.
    assert book_language(["en", "zh-Hans"], path) == "zh-Hans"
    assert book_language(["zh-SG"], path) == "zh-SG"
    # English text: the package is trusted, first value first.
    path = _book_file(tmp_path, "fr", "Le bateau attend la marée. ")
    assert book_language(["fr", "en"], path) == "fr"
    assert book_language([], path) is None
