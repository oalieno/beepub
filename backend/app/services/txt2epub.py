"""TXT → EPUB conversion.

A plain-text novel (the Chinese web-novel ``.txt`` is the common case)
becomes a chaptered EPUB at upload time, and that EPUB is what the rest
of BeePub sees: the reader, text extraction, spine weights, the kosync
digest, OPDS and the app's local library all keep working on an EPUB.
The original ``.txt`` is kept next to it for download only.

The rules in this module are the single source of truth for TXT
splitting. ``tests/fixtures/txt_chapter_vectors.json`` pins them so a
client-side (TypeScript) port for the serverless app can run the same
vectors.
"""

from __future__ import annotations

import codecs
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------

# UTF-32 first: its little-endian BOM starts with the UTF-16 one.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# Tried in this order when the file is not strict UTF-8; the best-scoring
# candidate wins, earlier ones win ties. utf-8 stays in the list so a
# UTF-8 file with a few stray bytes is still read as UTF-8 rather than
# as legacy double-byte garbage.
_CANDIDATES = ("utf-8", "gb18030", "cp950", "big5hkscs", "cp1252")
_SAMPLE_BYTES = 256 * 1024

# The most frequent hanzi in running prose, both scripts. A correct
# decode of Chinese text is dense in these; a wrong double-byte decode
# of the same bytes yields valid-but-rare characters instead.
_COMMON = frozenset(
    "的一是不了在人有我他這这中大來来上國国個个到說说們们為为子和你地出道也"
    "時时年得就那要下以生會会自著着去之過过家學学對对可她里後后小麼么心多天而"
    "能好都然沒没日於于起還还發发成事只作當当想看文無无開开手十用主行方又如前"
    "所本見见經经頭头面公同三已老從从動动兩两長长知民樣样現现分將将外但身些與与"
    "高意進进把法此實实回二理美點点月明其種种聲声全工己話话兒儿者向情性"
)


def _plausibility(text: str) -> float:
    if not text:
        return float("-inf")
    good = 0
    bad = 0
    for ch in text:
        if ch == "\ufffd":
            bad += 1
        elif ch.isascii() or ch in _COMMON:
            good += 1
    return (good - 8 * bad) / len(text)


def decode_text(data: bytes) -> tuple[str, str]:
    """Decode a text file of unknown encoding. Returns (text, encoding)."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            if enc == "utf-8-sig":
                return data.decode(enc, errors="replace"), enc
            return data[len(bom) :].decode(enc, errors="replace"), enc
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    sample = data[:_SAMPLE_BYTES]
    best_enc = "utf-8"
    best = float("-inf")
    for enc in _CANDIDATES:
        score = _plausibility(sample.decode(enc, errors="replace"))
        if score > best:
            best, best_enc = score, enc
    return data.decode(best_enc, errors="replace"), best_enc


# --------------------------------------------------------------------------
# Headings
# --------------------------------------------------------------------------

_NUM = "[0-9０-９零〇一二三四五六七八九十百千两兩壹貳參肆伍陸柒捌玖拾佰仟]+"
_OPEN = r"[【\[（(]?\s*"
_CLOSE = r"\s*[】\]）)]?"
# Optional subtitle: "第一章 潮聲", "第一章：潮聲", "第一章潮聲" all count.
_REST = r"(?:[\s:：、.．\-—–]*\S.*)?"

_VOLUME_RE = re.compile(rf"^{_OPEN}第\s*{_NUM}\s*[卷部集篇]{_CLOSE}{_REST}$")
_CHAPTER_RE = re.compile(rf"^{_OPEN}第\s*{_NUM}\s*[章回節节話话幕折]{_CLOSE}{_REST}$")
_SPECIAL_RE = re.compile(
    rf"^{_OPEN}(?:序章|序言|序幕|楔子|引子|前言|自序|代序|尾聲|尾声|終章|终章|"
    rf"後記|后记|番外(?:篇)?|外傳|外传|特別篇|特别篇|附錄|附录){_CLOSE}{_REST}$"
)
_EN_VOLUME_RE = re.compile(
    r"^(?:part|book|volume)\s+(?:\d+|[ivxlc]+|[a-z]+)\b.*$", re.IGNORECASE
)
_EN_CHAPTER_RE = re.compile(
    r"^(?:chapter\s+(?:\d+|[ivxlc]+|[a-z]+)\b.*|prologue\b.*|epilogue\b.*|"
    r"interlude\b.*)$",
    re.IGNORECASE,
)

_MAX_HEADING_CHARS = 60
# A line that carries a sentence is body text however it starts.
_NOT_A_TITLE_END = ("、", "；", "：", ";", ":")

LEVEL_PART = 1
LEVEL_CHAPTER = 2


def classify_heading(line: str) -> tuple[int, str] | None:
    """(level, title) when the line is a heading, else None."""
    s = " ".join(line.split())
    if not s or len(s) > _MAX_HEADING_CHARS:
        return None
    # A sentence mark anywhere ("第三章的開頭寫道，他來了。") or a clause
    # ending is body text however the line starts. Titles with a comma
    # exist but are rare; a false split is the worse error.
    if "。" in s or "，" in s or "," in s or s.endswith(_NOT_A_TITLE_END):
        return None
    if _VOLUME_RE.match(s) or _EN_VOLUME_RE.match(s):
        return LEVEL_PART, s
    if _CHAPTER_RE.match(s) or _SPECIAL_RE.match(s) or _EN_CHAPTER_RE.match(s):
        return LEVEL_CHAPTER, s
    return None


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


@dataclass
class Section:
    title: str
    level: int
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class TxtBook:
    title: str
    author: str | None
    language: str
    encoding: str
    sections: list[Section]


class EmptyTextError(ValueError):
    """The file decoded to no text at all."""


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff\ufffe\uffff]")
_TITLE_LINE_RE = re.compile(
    r"^(?:书名|書名|标题|標題|题名|題名|作品名)\s*[:：]\s*(.+)$"
)
_AUTHOR_LINE_RE = re.compile(
    r"^(?:作者|著者|作\s*者|author)\s*[:：]\s*(.+)$", re.IGNORECASE
)
_BRACKET_TITLE_RE = re.compile(
    r"^《(.+?)》(?:\s*(?:作者|by)?\s*[:：]?\s*(\S.*))?$", re.IGNORECASE
)
_LISTING_WORDS = frozenset(
    {"目录", "目錄", "正文", "内容简介", "內容簡介", "简介", "簡介"}
)
_METADATA_SCAN = 20

# Size-based fallback when a file has no recognisable headings: about
# three to five screens per section keeps the paginator's layout work per
# section bounded without turning the TOC into confetti.
FALLBACK_CHARS = 6000
_PREVIEW_CHARS = 20


def _paragraph(line: str) -> str:
    return line.strip(" \t　\xa0")


def _lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text).split("\n")


def _preview(paragraph: str) -> str:
    if len(paragraph) <= _PREVIEW_CHARS:
        return paragraph
    return paragraph[:_PREVIEW_CHARS].rstrip() + "…"


def _extract_metadata(
    paragraphs: list[str],
) -> tuple[str | None, str | None, list[str]]:
    """Pull `書名：` / `作者：` / `《書名》` lines out of the opening
    paragraphs. Returns (title, author, remaining paragraphs)."""
    title = author = None
    kept: list[str] = []
    for i, p in enumerate(paragraphs):
        if i >= _METADATA_SCAN:
            kept.extend(paragraphs[i:])
            break
        if p in _LISTING_WORDS:
            continue
        m = _TITLE_LINE_RE.match(p)
        if m and title is None:
            title = m.group(1).strip("《》 ")
            continue
        m = _AUTHOR_LINE_RE.match(p)
        if m and author is None:
            author = m.group(1).strip()
            continue
        m = _BRACKET_TITLE_RE.match(p)
        if m and title is None:
            title = m.group(1).strip()
            if m.group(2) and author is None:
                author = _AUTHOR_LINE_RE.sub(lambda a: a.group(1), m.group(2)).strip()
            continue
        kept.append(p)
    return title, author, kept


def _drop_empty(sections: list[Section]) -> list[Section]:
    """A chapter heading with nothing under it is a table-of-contents
    listing (files often open with one), not a chapter — except a bare
    trailing heading, which is kept for its title. A part with neither
    text nor chapters goes the same way."""
    out: list[Section] = []
    last = len(sections) - 1
    for i, sec in enumerate(sections):
        if sec.level == LEVEL_CHAPTER and not sec.paragraphs and i < last:
            continue
        out.append(sec)
    result: list[Section] = []
    for i, sec in enumerate(out):
        if sec.level == LEVEL_PART and not sec.paragraphs:
            has_child = i + 1 < len(out) and out[i + 1].level == LEVEL_CHAPTER
            if not has_child:
                continue
        result.append(sec)
    return result


def _chunk(paragraphs: list[str], title: str) -> list[Section]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for p in paragraphs:
        if current and size + len(p) > FALLBACK_CHARS:
            groups.append(current)
            current, size = [], 0
        current.append(p)
        size += len(p)
    if current:
        groups.append(current)
    if len(groups) <= 1:
        return [Section(title, LEVEL_CHAPTER, paragraphs)]
    return [Section(_preview(g[0]), LEVEL_CHAPTER, g) for g in groups]


def split_sections(text: str, title_hint: str) -> tuple[str, str | None, list[Section]]:
    """Split decoded text into sections. Returns (title, author, sections)."""
    preamble: list[str] = []
    sections: list[Section] = []
    for line in _lines(text):
        heading = classify_heading(line)
        if heading:
            level, title = heading
            sections.append(Section(title, level))
            continue
        p = _paragraph(line)
        if not p:
            continue
        (sections[-1].paragraphs if sections else preamble).append(p)

    found_title, author, preamble = _extract_metadata(preamble)
    title = found_title or title_hint.strip() or "Untitled"

    sections = _drop_empty(sections)
    if sections and not any(s.level == LEVEL_CHAPTER for s in sections):
        # Only "第一集"-style headings: they are the chapters.
        for s in sections:
            s.level = LEVEL_CHAPTER

    if not sections:
        if not preamble:
            raise EmptyTextError("no text")
        return title, author, _chunk(preamble, title)
    if preamble:
        sections.insert(0, Section(title, LEVEL_CHAPTER, preamble))
    return title, author, sections


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------

_TRAD = "們這說國個來為時會學對麼沒發開見經頭動兩長從樣現將進實點種聲話兒無"
_SIMP = "们这说国个来为时会学对么没发开见经头动两长从样现将进实点种声话儿无"
_LANG_SAMPLE = 50_000


def detect_language(text: str, encoding: str) -> str:
    sample = text[:_LANG_SAMPLE]
    letters = cjk = kana = trad = simp = 0
    for ch in sample:
        if not ch.isalpha():
            continue
        letters += 1
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
            if ch in _TRAD:
                trad += 1
            elif ch in _SIMP:
                simp += 1
        elif "\u3040" <= ch <= "\u30ff":
            kana += 1
    if letters == 0:
        return "en"
    if kana / letters > 0.05:
        return "ja"
    if cjk / letters < 0.3:
        return "en"
    if encoding in ("cp950", "big5hkscs"):
        return "zh-TW"
    if encoding == "gb18030":
        return "zh-CN"
    if trad > simp * 2:
        return "zh-TW"
    if simp > trad * 2:
        return "zh-CN"
    return "zh"


# --------------------------------------------------------------------------
# EPUB
# --------------------------------------------------------------------------

_CSS = """\
body { margin: 0; padding: 0; }
h1, h2 { font-weight: 600; text-align: center; margin: 1.5em 0 1em; line-height: 1.3; }
h1 { font-size: 1.4em; }
h2 { font-size: 1.2em; }
p { margin: 0 0 0.6em; text-indent: 2em; }
"""

_CONTAINER = """\
<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


@dataclass
class _Entry:
    section: Section
    href: str | None
    children: list[_Entry] = field(default_factory=list)

    @property
    def target(self) -> str | None:
        if self.href:
            return self.href
        return self.children[0].target if self.children else None


def _xhtml(section: Section, lang: str) -> str:
    tag = "h1" if section.level == LEVEL_PART else "h2"
    kind = "part" if section.level == LEVEL_PART else "chapter"
    title = escape(section.title)
    body = "\n".join(f"<p>{escape(p)}</p>" for p in section.paragraphs)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{lang}" lang="{lang}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{title}</title>\n'
        '<link rel="stylesheet" type="text/css" href="../style.css"/>\n'
        "</head>\n<body>\n"
        f'<section epub:type="{kind}">\n<{tag}>{title}</{tag}>\n{body}\n</section>\n'
        "</body>\n</html>\n"
    )


def _nav_list(entries: list[_Entry], depth: int) -> str:
    pad = "  " * depth
    items = []
    for e in entries:
        target = e.target
        if not target:
            continue
        inner = f'<a href="{target}">{escape(e.section.title)}</a>'
        if e.children:
            inner += "\n" + _nav_list(e.children, depth + 1) + pad + "  "
        items.append(f"{pad}  <li>{inner}</li>\n")
    return f"{pad}<ol>\n{''.join(items)}{pad}</ol>\n"


def _ncx_points(entries: list[_Entry], counter: list[int], depth: int) -> str:
    pad = "  " * depth
    out = []
    for e in entries:
        target = e.target
        if not target:
            continue
        counter[0] += 1
        n = counter[0]
        out.append(
            f'{pad}<navPoint id="np{n}" playOrder="{n}">\n'
            f"{pad}  <navLabel><text>{escape(e.section.title)}</text></navLabel>\n"
            f'{pad}  <content src="{target}"/>\n'
            f"{_ncx_points(e.children, counter, depth + 1)}"
            f"{pad}</navPoint>\n"
        )
    return "".join(out)


def write_epub(book: TxtBook, out_path: str) -> None:
    lang = book.language
    uid = f"urn:uuid:{uuid.uuid4()}"
    title = escape(book.title)

    # Files: every section with text gets one; a part heading with no
    # text of its own is a TOC node pointing at its first chapter.
    entries: list[_Entry] = []
    files: list[tuple[str, str]] = []  # (href, xhtml)
    parent: _Entry | None = None
    for sec in book.sections:
        href = None
        if sec.paragraphs or sec.level == LEVEL_CHAPTER:
            href = f"text/{len(files) + 1:04d}.xhtml"
            files.append((href, _xhtml(sec, lang)))
        entry = _Entry(sec, href)
        if sec.level == LEVEL_PART:
            entries.append(entry)
            parent = entry
        elif parent is not None:
            parent.children.append(entry)
        else:
            entries.append(entry)

    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    for i, (href, _) in enumerate(files, start=1):
        manifest.append(
            f'<item id="s{i:04d}" href="{href}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="s{i:04d}"/>')
    creator = (
        f"    <dc:creator>{escape(book.author)}</dc:creator>\n" if book.author else ""
    )
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="uid" xml:lang="{lang}">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
        f"    <dc:title>{title}</dc:title>\n"
        f"{creator}"
        f"    <dc:language>{lang}</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n    " + "\n    ".join(manifest) + "\n  </manifest>\n"
        '  <spine toc="ncx">\n    ' + "\n    ".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}">\n'
        f'<head>\n<meta charset="utf-8"/>\n<title>{title}</title>\n</head>\n<body>\n'
        '<nav epub:type="toc" id="toc">\n<h1>Contents</h1>\n'
        f"{_nav_list(entries, 0)}"
        "</nav>\n</body>\n</html>\n"
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="{uid}"/>\n'
        '    <meta name="dtb:depth" content="2"/>\n'
        '    <meta name="dtb:totalPageCount" content="0"/>\n'
        '    <meta name="dtb:maxPageNumber" content="0"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{title}</text></docTitle>\n"
        "  <navMap>\n"
        f"{_ncx_points(entries, [0], 2)}"
        "  </navMap>\n"
        "</ncx>\n"
    )

    with zipfile.ZipFile(out_path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        for name, data in (
            ("META-INF/container.xml", _CONTAINER),
            ("OEBPS/content.opf", opf),
            ("OEBPS/nav.xhtml", nav),
            ("OEBPS/toc.ncx", ncx),
            ("OEBPS/style.css", _CSS),
        ):
            zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        for href, xhtml in files:
            zf.writestr(f"OEBPS/{href}", xhtml, compress_type=zipfile.ZIP_DEFLATED)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def parse_txt(data: bytes, title_hint: str) -> TxtBook:
    text, encoding = decode_text(data)
    title, author, sections = split_sections(text, title_hint)
    return TxtBook(
        title=title,
        author=author,
        language=detect_language(text, encoding),
        encoding=encoding,
        sections=sections,
    )


def convert_txt_to_epub(src_path: str, out_path: str, title_hint: str) -> TxtBook:
    """Read a .txt, write the EPUB next to it. Raises EmptyTextError for a
    file with no text."""
    with open(src_path, "rb") as f:
        data = f.read()
    book = parse_txt(data, title_hint)
    write_epub(book, out_path)
    return book
