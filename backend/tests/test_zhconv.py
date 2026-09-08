"""Simplified-to-Traditional conversion of TXT books."""

from app.services.txt2epub import Section, TxtBook, apply_zh_conversion
from app.services.zhconv import convert, convert_name


def test_character_mode_keeps_length_and_taiwan_forms():
    assert convert("这个软件里的信息", "s2tw") == "這個軟件裡的信息"
    assert len(convert("这个软件里的信息", "s2tw")) == len("这个软件里的信息")


def test_phrase_mode_rewrites_mainland_usage():
    assert convert("这个软件里的信息", "s2twp") == "這個軟體裡的資訊"


def test_traditional_text_passes_through():
    text = "退潮之後，沙灘上留著昨夜的腳印。"
    assert convert(text, "s2tw") == text
    assert convert(text, "s2twp") == text


def test_names_only_use_the_character_table():
    # A phrase table would turn a name's 软件 into 軟體; names never do.
    assert convert_name("软件小子") == "軟件小子"


def _book() -> TxtBook:
    return TxtBook(
        title="雾港夜航",
        author="陈默",
        language="zh-CN",
        encoding="utf-8",
        sections=[
            Section(
                "第一章 出港", 2, ["缆绳解开的时候，雾还没散。", "软件工程师上了船。"]
            ),
        ],
    )


def test_apply_converts_text_and_marks_the_book_traditional():
    book = apply_zh_conversion(_book(), "s2twp")
    assert book.language == "zh-TW"
    assert book.title == "霧港夜航"
    assert book.author == "陳默"
    assert book.sections[0].title == "第一章 出港"
    assert book.sections[0].paragraphs == [
        "纜繩解開的時候，霧還沒散。",
        "軟體工程師上了船。",
    ]


def test_character_mode_leaves_phrases_alone():
    book = apply_zh_conversion(_book(), "s2tw")
    assert book.sections[0].paragraphs[1] == "軟件工程師上了船。"
