"""Simplified-to-Traditional Chinese conversion (OpenCC).

Two configurations are offered: "s2tw" converts characters to the Taiwan
standard and keeps every string the same length, "s2twp" also rewrites
Mainland phrases as Taiwan usage (軟件→軟體), which changes lengths.
Names always go through the character-level table: a phrase table would
rewrite proper nouns.
"""

from functools import cache

MODES = ("s2tw", "s2twp")
NAME_MODE = "s2tw"


@cache
def _converter(mode: str):
    import opencc

    return opencc.OpenCC(mode)


def convert(text: str, mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"unknown conversion {mode!r}")
    return _converter(mode).convert(text)


def convert_name(text: str) -> str:
    return _converter(NAME_MODE).convert(text)
