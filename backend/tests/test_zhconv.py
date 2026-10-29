"""OpenCC conversion: the two modes, names, and interface text."""

from app.services.zhconv import convert, convert_name, to_simplified


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


def test_interface_text_to_simplified_uses_mainland_terms():
    assert to_simplified("軟體資訊") == "软件信息"


def test_tag_label_overrides_name_real_slugs():
    from app.services.tags import _HANS_OVERRIDES, TAG_LABELS, TAG_LABELS_HANS

    assert set(_HANS_OVERRIDES) <= set(TAG_LABELS)
    assert TAG_LABELS_HANS["cyberpunk"] == "赛博朋克"
    assert set(TAG_LABELS_HANS) == set(TAG_LABELS)
