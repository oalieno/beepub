"""Simplified-to-Traditional conversion of an EPUB in place, and of the
highlights anchored in it.

The file is rewritten text run by text run: tags, attributes and the
document structure stay byte for byte, so every CFI path into the book
still names the same node. Only characters change — and with phrase
conversion (s2twp) their count, so offsets inside a text node can move.

Conversion depends on context (头发 → 頭髮, but a lone 发 → 發), so text is
never converted in pieces cut at arbitrary points: each document's body
text is converted as one string, and an old→new position map carries
node boundaries and highlight ends across. A highlight's stored quote is
then cut out of the converted text, so it always matches the book; the
reader's anchor check (frontend/src/lib/reader/anchor.ts) re-finds the
ones whose offsets moved.
"""

from __future__ import annotations

import html
import posixpath
import re
import zipfile
from array import array
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from lxml import etree

from app.services.zhconv import convert, convert_name

_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
_XHTML_TYPES = {"application/xhtml+xml", "text/html"}
_NCX_TYPE = "application/x-dtbncx+xml"

# Markup the text scan steps over. Text between these is a text node.
_MARKUP = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<![A-Za-z][^>]*>|<[^>]*>",
    re.S,
)
_TAG_NAME = re.compile(r"<\s*(/?)\s*([A-Za-z_][\w:.-]*)")
_LANG_ATTR = re.compile(r"""(\b(?:xml:)?lang\s*=\s*["'])zh(?:-[A-Za-z0-9]+)*(["'])""")
_ENCODING = re.compile(rb"""<\?xml[^>]*encoding\s*=\s*["']([\w.-]+)["']""")
# Conversion never reaches across punctuation or whitespace, so text is
# converted run by run between them — each run with its full context.
_RUN = re.compile(r"[^\s，。！？；：、「」『』（）《》〈〉【】…—,.!?;:()\[\]\"'“”‘’]+")

# The reader's quote context (BookReader.svelte QUOTE_CONTEXT) and the
# matcher's tie-break window (anchor.ts CONTEXT).
QUOTE_CONTEXT = 48
_MATCH_CONTEXT = 20


@dataclass
class Mapped:
    """A converted string and where each old position landed: ``pos[i]``
    is the new index of old index ``i`` (len(old) + 1 entries)."""

    old: str
    new: str
    pos: array


def convert_mapped(text: str, mode: str) -> Mapped:
    pos = array("l", range(len(text) + 1))
    out: list[str] = []
    last = 0
    shift = 0
    for run in _RUN.finditer(text):
        start, end = run.span()
        out.append(text[last:start])
        for i in range(last, start):
            pos[i] = i + shift
        old = run.group()
        new = convert(old, mode)
        out.append(new)
        base = start + shift
        if len(new) == len(old):
            for i in range(len(old)):
                pos[start + i] = base + i
        else:
            matcher = SequenceMatcher(None, old, new, autojunk=False)
            for _, i1, i2, j1, j2 in matcher.get_opcodes():
                span = i2 - i1
                for k in range(span):
                    pos[start + i1 + k] = base + j1 + (k * (j2 - j1)) // span
            shift += len(new) - len(old)
        last = end
    out.append(text[last:])
    for i in range(last, len(text) + 1):
        pos[i] = i + shift
    return Mapped(text, "".join(out), pos)


@dataclass
class _Text:
    """A text node of the raw document: [raw_start, raw_end) in the file
    text, [flat_start, flat_end) in the decoded body text."""

    raw_start: int
    raw_end: int
    flat_start: int
    flat_end: int


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _retag(tag: str) -> str:
    return _LANG_ATTR.sub(r"\1zh-TW\2", tag)


def convert_document(
    raw: str, mode: str, *, body_only: bool = True
) -> tuple[str, Mapped]:
    """Convert the text of one XHTML (or NCX) document.

    Returns the rewritten document and the mapping of its body text (the
    concatenated text nodes inside <body>, decoded — what a DOM walk over
    the body reads). Text outside the body (the <title>) is converted on
    its own; script and style are left alone.
    """
    texts: list[_Text] = []
    decoded: list[str] = []
    outside: list[tuple[int, int, str]] = []
    tags: list[tuple[int, int, str]] = []
    in_body = not body_only
    skip = None
    flat_len = 0
    last = 0

    def text_run(start: int, end: int) -> None:
        nonlocal flat_len
        if start == end or skip:
            return
        value = html.unescape(raw[start:end])
        if in_body:
            texts.append(_Text(start, end, flat_len, flat_len + len(value)))
            decoded.append(value)
            flat_len += len(value)
        else:
            outside.append((start, end, value))

    for markup in _MARKUP.finditer(raw):
        text_run(last, markup.start())
        last = markup.end()
        token = markup.group()
        name = _TAG_NAME.match(token)
        if name:
            tags.append((markup.start(), markup.end(), token))
            closing, tag = name.group(1) == "/", name.group(2).lower().split(":")[-1]
            if tag in ("script", "style"):
                skip = None if closing else (None if token.endswith("/>") else tag)
            elif tag == "body" and body_only:
                in_body = not closing
    text_run(last, len(raw))

    mapped = convert_mapped("".join(decoded), mode)
    edits: list[tuple[int, int, str]] = []
    for node, value in zip(texts, decoded, strict=True):
        new = mapped.new[mapped.pos[node.flat_start] : mapped.pos[node.flat_end]]
        if new != value:
            edits.append((node.raw_start, node.raw_end, _escape(new)))
    for start, end, value in outside:
        new = convert(value, mode)
        if new != value:
            edits.append((start, end, _escape(new)))
    for start, end, token in tags:
        retagged = _retag(token)
        if retagged != token:
            edits.append((start, end, retagged))
    return _apply(raw, edits), mapped


def _apply(raw: str, edits: list[tuple[int, int, str]]) -> str:
    if not edits:
        return raw
    out: list[str] = []
    last = 0
    for start, end, value in sorted(edits):
        out.append(raw[last:start])
        out.append(value)
        last = end
    out.append(raw[last:])
    return "".join(out)


# OPF metadata: names go through the character table only, like TXT
# titles; prose through the chosen mode.
_NAME_FIELDS = {"title", "creator", "contributor", "publisher"}
_PROSE_FIELDS = {"description", "subject"}
_SERIES_META = re.compile(
    r"""(<(?:opf:)?meta\b[^>]*\bname\s*=\s*["']calibre:series["'][^>]*\bcontent\s*=\s*["'])([^"']*)(["'])""",
    re.S,
)


def convert_opf(raw: str, mode: str) -> str:
    edits: list[tuple[int, int, str]] = []
    element = None
    last = 0
    for markup in _MARKUP.finditer(raw):
        if element and markup.start() > last:
            value = html.unescape(raw[last : markup.start()])
            if element == "language":
                if value.strip().lower().startswith("zh") or not value.strip():
                    new = "zh-TW"
                else:
                    new = value
            elif element in _NAME_FIELDS:
                new = convert_name(value)
            elif element in _PROSE_FIELDS:
                new = convert(value, mode)
            elif element == "meta":
                # EPUB 3 series (belongs-to-collection) is a meta with text.
                new = convert_name(value)
            else:
                new = value
            if new != value:
                edits.append((last, markup.start(), _escape(new)))
        last = markup.end()
        name = _TAG_NAME.match(markup.group())
        if name:
            closing = name.group(1) == "/"
            tag = name.group(2).lower().split(":")[-1]
            element = None if closing or markup.group().endswith("/>") else tag
            if tag == "meta" and not closing:
                token = markup.group()
                if "belongs-to-collection" not in token:
                    element = None
                series = _SERIES_META.search(token)
                if series:
                    renamed = convert_name(html.unescape(series.group(2)))
                    edits.append(
                        (
                            markup.start(),
                            markup.end(),
                            token[: series.start(2)]
                            + _escape(renamed).replace('"', "&quot;")
                            + token[series.end(2) :],
                        )
                    )
    return _apply(raw, edits)


def _decode(data: bytes) -> tuple[str, str]:
    match = _ENCODING.search(data[:200])
    encoding = match.group(1).decode() if match else "utf-8"
    try:
        return data.decode(encoding), encoding
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="surrogateescape"), "utf-8"


def _encode(text: str, encoding: str) -> bytes:
    try:
        return text.encode(encoding, errors="surrogateescape")
    except UnicodeEncodeError:
        return text.encode(encoding, errors="xmlcharrefreplace")


def _resolve(base: str, target: str) -> str:
    target = target.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


@dataclass
class _Package:
    opf_path: str
    # Document paths in spine order. Indexed like foliate's sections: an
    # itemref naming no file keeps its place, as None.
    spine: list[str | None]
    documents: list[str]  # every XHTML in the manifest
    ncx: list[str]


def _read_package(zf: zipfile.ZipFile) -> _Package:
    names = {n.lower(): n for n in zf.namelist()}

    def real(path: str) -> str | None:
        return names.get(path.lower())

    container = etree.fromstring(zf.read(real("META-INF/container.xml") or ""))
    rootfile = container.find(".//c:rootfile", _CONTAINER_NS)
    if rootfile is None:
        raise ValueError("No rootfile in container.xml")
    opf_path = real(rootfile.get("full-path", "")) or rootfile.get("full-path", "")
    opf = etree.fromstring(zf.read(opf_path))
    items: dict[str, tuple[str, str]] = {}
    documents: list[str] = []
    ncx: list[str] = []
    for item in opf.iterfind(".//opf:manifest/opf:item", _OPF_NS):
        path = real(_resolve(opf_path, item.get("href", "")))
        if path is None:
            continue
        media_type = item.get("media-type", "")
        items[item.get("id", "")] = (path, media_type)
        if media_type in _XHTML_TYPES:
            documents.append(path)
        elif media_type == _NCX_TYPE:
            ncx.append(path)
    spine = [
        items[ref.get("idref", "")][0] if ref.get("idref", "") in items else None
        for ref in opf.iterfind(".//opf:spine/opf:itemref", _OPF_NS)
    ]
    return _Package(opf_path, spine, documents, ncx)


@dataclass
class ConvertedBook:
    """Per spine index, the body text before and after; changed when any
    text did (a book already Traditional comes back unchanged)."""

    sections: dict[int, Mapped] = field(default_factory=dict)
    changed: bool = False


def convert_epub(src: str, dst: str, mode: str) -> ConvertedBook:
    """Write a Traditional copy of the EPUB at ``src`` to ``dst``. Every
    other entry is copied as is, in the original order (mimetype first,
    stored)."""
    result = ConvertedBook()
    with zipfile.ZipFile(src) as zf:
        package = _read_package(zf)
        spine_index: dict[str, list[int]] = {}
        for index, path in enumerate(package.spine):
            if path is not None:
                spine_index.setdefault(path, []).append(index)
        rewritten: dict[str, bytes] = {}
        for path in dict.fromkeys(package.documents + package.ncx):
            data = zf.read(path)
            raw, encoding = _decode(data)
            new_raw, mapped = convert_document(
                raw, mode, body_only=path not in package.ncx
            )
            for index in spine_index.get(path, []):
                result.sections[index] = mapped
            if new_raw != raw:
                rewritten[path] = _encode(new_raw, encoding)
            # Language tags alone don't make a Traditional book need it.
            if mapped.new != mapped.old:
                result.changed = True
        raw, encoding = _decode(zf.read(package.opf_path))
        new_opf = convert_opf(raw, mode)
        if new_opf != raw:
            rewritten[package.opf_path] = _encode(new_opf, encoding)
        with zipfile.ZipFile(dst, "w") as out:
            for info in zf.infolist():
                data = rewritten.get(info.filename)
                out.writestr(info, data if data is not None else zf.read(info))
    return result


@dataclass
class Segment:
    """A piece of a sentence: as written, with characters converted
    (s2tw), and with Mainland wording rewritten too (s2twp)."""

    before: str
    chars: str
    phrases: str


# Block elements end a line of text; inline ones (<em>, <ruby>) do not.
_BLOCK_TAG = re.compile(
    r"</?(?:p|div|h[1-6]|li|br|tr|td|section|blockquote|dt|dd)\b[^>]*>", re.I
)
# A sentence of the body: whole (from a line or sentence start to its
# closing mark), long enough to read as prose — a contents page or a
# colophon line has no closing mark, or is too short.
_SENTENCE = re.compile(
    r"(?:^|(?<=[。！？]))[^\S\n]*([^。！？\n]{12,80}[。！？」”]*)", re.M
)
_PREVIEW_SCAN = 300_000


def _lines(raw: str) -> str:
    body = re.search(r"<body\b.*?>(.*)</body>", raw, re.S | re.I)
    text = _BLOCK_TAG.sub("\n", body.group(1) if body else "")
    return html.unescape(_MARKUP.sub("", text))


def _segments(sentence: str) -> list[Segment]:
    chars = convert(sentence, "s2tw")
    phrases = convert(sentence, "s2twp")
    if len(chars) != len(sentence):
        return [Segment(sentence, chars, phrases)]
    pieces: list[Segment] = []
    matcher = SequenceMatcher(None, chars, phrases, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pieces += [Segment(sentence[k], chars[k], chars[k]) for k in range(i1, i2)]
        else:
            pieces.append(Segment(sentence[i1:i2], chars[i1:i2], phrases[j1:j2]))
    # A rewritten word is shown whole. The aligner can split one (软件 →
    # 軟體 aligns 軟 with itself), so a wording piece takes in neighbours
    # until it converts to its own rewriting on its own — and no further,
    # or a separate word next to it (看着视频's 着) would join it.
    i = 0
    while i < len(pieces):
        piece = pieces[i]
        for _ in range(4):
            if (
                _kind(piece) != "phrase"
                or convert(piece.before, "s2twp") == piece.phrases
            ):
                break
            if i > 0 and _kind(pieces[i - 1]) != "phrase":
                i -= 1
                piece = _join(pieces[i], piece)
                del pieces[i + 1]
            elif i + 1 < len(pieces) and _kind(pieces[i + 1]) != "phrase":
                piece = _join(piece, pieces[i + 1])
                del pieces[i + 1]
            else:
                break
            pieces[i] = piece
        i += 1
    merged: list[Segment] = []
    for piece in pieces:
        kind = _kind(piece)
        if merged and _kind(merged[-1]) == kind:
            merged[-1] = _join(merged[-1], piece)
        else:
            merged.append(piece)
    return merged


def _join(a: Segment, b: Segment) -> Segment:
    return Segment(a.before + b.before, a.chars + b.chars, a.phrases + b.phrases)


def _kind(segment: Segment) -> str:
    if segment.phrases != segment.chars:
        return "phrase"
    return "char" if segment.chars != segment.before else "same"


def preview(src: str) -> list[Segment] | None:
    """A sentence of the book's body text, piece by piece — preferably one
    whose wording the phrase option changes too, so its effect shows, and
    else the first that changes at all. None when nothing would change.
    Mode-free: each piece carries both conversions."""
    sentence_fallback = None
    line_fallback = None
    scanned = 0
    with zipfile.ZipFile(src) as zf:
        package = _read_package(zf)
        for path in filter(None, package.spine):
            if path not in package.documents:
                continue
            text = _lines(_decode(zf.read(path))[0])
            for match in _SENTENCE.finditer(text):
                sentence = match.group(1).strip()
                chars = convert(sentence, "s2tw")
                if convert(sentence, "s2twp") != chars:
                    return _segments(sentence)
                if sentence_fallback is None and chars != sentence:
                    sentence_fallback = sentence
            if line_fallback is None:
                # No prose that changes: any line that does (a book of
                # headings and verse still has something to show).
                line_fallback = next(
                    (
                        line[:80]
                        for line in map(str.strip, text.splitlines())
                        if line and convert(line[:80], "s2tw") != line[:80]
                    ),
                    None,
                )
            scanned += len(text)
            if scanned > _PREVIEW_SCAN:
                break
    fallback = sentence_fallback or line_fallback
    return _segments(fallback) if fallback else None


def sample_text(src: str, limit: int = 20_000) -> str:
    """The first ``limit`` characters of the book's body text."""
    parts: list[str] = []
    size = 0
    with zipfile.ZipFile(src) as zf:
        package = _read_package(zf)
        for path in filter(None, package.spine):
            if path not in package.documents:
                continue
            raw, _ = _decode(zf.read(path))
            body = re.search(r"<body\b.*?>(.*)</body>", raw, re.S | re.I)
            text = html.unescape(_MARKUP.sub("", body.group(1) if body else ""))
            parts.append(text)
            size += len(text)
            if size >= limit:
                break
    return "".join(parts)[:limit]


# --- Highlights ------------------------------------------------------------


@dataclass
class Quote:
    text: str
    prefix: str | None
    suffix: str | None


def _collapsed(text: str) -> tuple[str, list[int]]:
    """Whitespace runs to one space, leading whitespace dropped, with each
    kept character's raw index — the flattening anchor.ts findQuote does."""
    out: list[str] = []
    index: list[int] = []
    last_space = True
    for i, ch in enumerate(text):
        if ch.isspace():
            if last_space:
                continue
            out.append(" ")
            last_space = True
        else:
            out.append(ch)
            last_space = False
        index.append(i)
    return "".join(out), index


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def locate(body: str, quote: Quote) -> tuple[int, int] | None:
    """Where the quote sits in a document's body text, as a raw [start,
    end) — only when unambiguous, by the same rules as findQuote."""
    needle = _normalize(quote.text)
    if not needle:
        return None
    flat, index = _collapsed(body)
    hits = []
    at = flat.find(needle)
    while at >= 0:
        hits.append(at)
        at = flat.find(needle, at + 1)
    if not hits:
        return None
    if len(hits) == 1:
        pick = hits[0]
    else:
        tail = _normalize(quote.prefix or "")[-_MATCH_CONTEXT:].lower()
        head = _normalize(quote.suffix or "")[:_MATCH_CONTEXT].lower()
        window = 3 * _MATCH_CONTEXT
        scored = []
        for hit in hits:
            before = flat[max(0, hit - window) : hit].lower()
            after = flat[hit + len(needle) : hit + len(needle) + window].lower()
            score = (bool(tail) and tail in before) + (bool(head) and head in after)
            scored.append((score, hit))
        top = max(score for score, _ in scored)
        best = [hit for score, hit in scored if score == top]
        if top == 0 or len(best) != 1:
            return None
        pick = best[0]
    return index[pick], index[pick + len(needle) - 1] + 1


def convert_quote(quote: Quote, section: Mapped | None, mode: str) -> Quote:
    """The highlight's quote as the converted book reads it. Found in its
    section, it is cut from the converted text; otherwise its text and
    context are converted together, so the context still informs it."""
    found = locate(section.old, quote) if section else None
    if section and found:
        start, end = section.pos[found[0]], section.pos[found[1]]
        new = section.new
        return Quote(
            text=new[start:end],
            prefix=new[max(0, start - QUOTE_CONTEXT) : start]
            if quote.prefix is not None
            else None,
            suffix=new[end : end + QUOTE_CONTEXT] if quote.suffix is not None else None,
        )
    prefix, suffix = quote.prefix or "", quote.suffix or ""
    joined = convert_mapped(prefix + quote.text + suffix, mode)
    a = joined.pos[len(prefix)]
    b = joined.pos[len(prefix) + len(quote.text)]
    return Quote(
        text=joined.new[a:b],
        prefix=joined.new[:a] if quote.prefix is not None else None,
        suffix=joined.new[b:] if quote.suffix is not None else None,
    )


def convert_highlight(
    quote: Quote, book: ConvertedBook, home: int | None, mode: str
) -> Quote:
    """A highlight's quote for the converted book: looked for in its own
    section, then across the spine (as the reader's heal does)."""
    order = sorted(book.sections, key=lambda index: index != home)
    for index in order:
        section = book.sections[index]
        if locate(section.old, quote):
            return convert_quote(quote, section, mode)
    return convert_quote(quote, None, mode)


_SPINE_STEP = re.compile(r"epubcfi\(/6/(\d+)")


def section_of(cfi: str, section_index: int | None) -> int | None:
    if section_index is not None:
        return section_index
    match = _SPINE_STEP.match(cfi or "")
    return int(match.group(1)) // 2 - 1 if match else None
