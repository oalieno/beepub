"""Deterministic tag mapping: external raw tags → curated vocabulary.

Maps tags from Goodreads shelves, Readmoo categories, Google Books categories,
Hardcover genres/moods/tags, and epub/calibre tags to our curated vocabulary
using a synonym lookup table. Zero LLM cost.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import BookTag, TagSource

logger = logging.getLogger(__name__)

# ── Synonym map: normalized input → (category, curated_slug) ──
# Keys should be lowercase, stripped. Add entries as we discover raw tag formats.
SYNONYM_MAP: dict[str, tuple[str, str]] = {
    # ── Genre mappings ──
    "science fiction": ("genre", "science fiction"),
    "sci-fi": ("genre", "science fiction"),
    "scifi": ("genre", "science fiction"),
    "sf": ("genre", "science fiction"),
    "fantasy": ("genre", "fantasy"),
    "mystery": ("genre", "mystery"),
    "mysteries": ("genre", "mystery"),
    "thriller": ("genre", "thriller"),
    "thrillers": ("genre", "thriller"),
    "romance": ("genre", "romance"),
    "horror": ("genre", "horror"),
    "literary fiction": ("genre", "literary fiction"),
    "literary": ("genre", "literary fiction"),
    "general fiction": ("genre", "literary fiction"),
    "historical fiction": ("genre", "historical fiction"),
    "historical": ("genre", "historical fiction"),
    "crime": ("genre", "crime"),
    "crime fiction": ("genre", "crime"),
    "adventure": ("genre", "adventure"),
    "comedy": ("genre", "comedy"),
    "humor": ("genre", "comedy"),
    "humour": ("genre", "comedy"),
    "satire": ("genre", "satire"),
    "drama": ("genre", "drama"),
    "biography": ("genre", "biography"),
    "biographies": ("genre", "biography"),
    "memoir": ("genre", "memoir"),
    "memoirs": ("genre", "memoir"),
    "autobiography": ("genre", "memoir"),
    "poetry": ("genre", "poetry"),
    "poems": ("genre", "poetry"),
    "essay": ("genre", "essay"),
    "essays": ("genre", "essay"),
    "graphic novel": ("genre", "graphic novel"),
    "graphic novels": ("genre", "graphic novel"),
    "comics": ("genre", "graphic novel"),
    "manga": ("genre", "graphic novel"),
    "young adult": ("genre", "young adult"),
    "ya": ("genre", "young adult"),
    "young-adult": ("genre", "young adult"),
    "children": ("genre", "children"),
    "childrens": ("genre", "children"),
    "children's": ("genre", "children"),
    "juvenile fiction": ("genre", "children"),
    # ── Subgenre mappings ──
    "hard science fiction": ("subgenre", "hard sci-fi"),
    "hard sci-fi": ("subgenre", "hard sci-fi"),
    "hard sf": ("subgenre", "hard sci-fi"),
    "space opera": ("subgenre", "space opera"),
    "cyberpunk": ("subgenre", "cyberpunk"),
    "post-apocalyptic": ("subgenre", "post-apocalyptic"),
    "post apocalyptic": ("subgenre", "post-apocalyptic"),
    "apocalyptic": ("subgenre", "post-apocalyptic"),
    "military science fiction": ("subgenre", "military sci-fi"),
    "military sci-fi": ("subgenre", "military sci-fi"),
    "military sf": ("subgenre", "military sci-fi"),
    "solarpunk": ("subgenre", "solarpunk"),
    "dystopia": ("subgenre", "dystopian"),
    "dystopian": ("subgenre", "dystopian"),
    "high fantasy": ("subgenre", "high fantasy"),
    "epic fantasy": ("subgenre", "high fantasy"),
    "urban fantasy": ("subgenre", "urban fantasy"),
    "dark fantasy": ("subgenre", "dark fantasy"),
    "grimdark": ("subgenre", "grimdark"),
    "cozy fantasy": ("subgenre", "cozy fantasy"),
    "sword and sorcery": ("subgenre", "sword and sorcery"),
    "romantasy": ("subgenre", "romantasy"),
    "magical realism": ("subgenre", "magical realism"),
    "magic realism": ("subgenre", "magical realism"),
    "cozy mystery": ("subgenre", "cozy mystery"),
    "cozy mysteries": ("subgenre", "cozy mystery"),
    "noir": ("subgenre", "noir"),
    "police procedural": ("subgenre", "police procedural"),
    "true crime": ("subgenre", "true crime"),
    "psychological thriller": ("subgenre", "psychological thriller"),
    "psychological": ("subgenre", "psychological thriller"),
    "domestic thriller": ("subgenre", "domestic thriller"),
    "legal thriller": ("subgenre", "legal thriller"),
    "gothic": ("subgenre", "gothic horror"),
    "gothic horror": ("subgenre", "gothic horror"),
    "cosmic horror": ("subgenre", "cosmic horror"),
    "lovecraftian": ("subgenre", "cosmic horror"),
    "contemporary romance": ("subgenre", "contemporary romance"),
    "historical romance": ("subgenre", "historical romance"),
    "paranormal romance": ("subgenre", "paranormal romance"),
    "dark romance": ("subgenre", "dark romance"),
    "romantic comedy": ("subgenre", "romantic comedy"),
    "rom-com": ("subgenre", "romantic comedy"),
    "romcom": ("subgenre", "romantic comedy"),
    # CJK subgenres
    "wuxia": ("subgenre", "wuxia"),
    "武俠": ("subgenre", "wuxia"),
    "武俠小說": ("subgenre", "wuxia"),
    "xianxia": ("subgenre", "xianxia"),
    "仙俠": ("subgenre", "xianxia"),
    "xuanhuan": ("subgenre", "xuanhuan"),
    "玄幻": ("subgenre", "xuanhuan"),
    "danmei": ("subgenre", "danmei"),
    "耽美": ("subgenre", "danmei"),
    "bl": ("subgenre", "danmei"),
    "boys love": ("subgenre", "danmei"),
    "cultivation": ("subgenre", "cultivation"),
    "修真": ("subgenre", "cultivation"),
    "修仙": ("subgenre", "cultivation"),
    "light novel": ("subgenre", "light novel"),
    "light novels": ("subgenre", "light novel"),
    "輕小說": ("subgenre", "light novel"),
    "isekai": ("subgenre", "isekai"),
    "異世界": ("subgenre", "isekai"),
    # Non-fiction subgenres
    "self-help": ("subgenre", "self-help"),
    "self help": ("subgenre", "self-help"),
    "自我成長": ("subgenre", "self-help"),
    "popular science": ("subgenre", "popular science"),
    "science": ("subgenre", "popular science"),
    "travel": ("subgenre", "travel writing"),
    "travel writing": ("subgenre", "travel writing"),
    "journalism": ("subgenre", "journalism"),
    "philosophy": ("subgenre", "philosophy"),
    "哲學": ("subgenre", "philosophy"),
    "psychology": ("subgenre", "psychology"),
    "心理學": ("subgenre", "psychology"),
    "business": ("subgenre", "business"),
    "商業": ("subgenre", "business"),
    "economics": ("subgenre", "economics"),
    "經濟": ("subgenre", "economics"),
    "history": ("subgenre", "history"),
    "歷史": ("subgenre", "history"),
    "sociology": ("subgenre", "sociology"),
    "education": ("subgenre", "education"),
    "health": ("subgenre", "health"),
    "cooking": ("subgenre", "cooking"),
    "料理": ("subgenre", "cooking"),
    "art": ("subgenre", "art"),
    "music": ("subgenre", "music"),
    "sports": ("subgenre", "sports"),
    "religion": ("subgenre", "religion"),
    "politics": ("subgenre", "politics"),
    "technology": ("subgenre", "technology"),
    "slice of life": ("subgenre", "slice of life"),
    "日常": ("subgenre", "slice of life"),
    "dark academia": ("subgenre", "dark academia"),
    # ── Mood mappings ──
    "dark": ("mood", "dark"),
    "黑暗": ("mood", "dark"),
    "lighthearted": ("mood", "lighthearted"),
    "輕鬆": ("mood", "lighthearted"),
    "funny": ("mood", "humorous"),
    "emotional": ("mood", "emotional"),
    "suspenseful": ("mood", "suspenseful"),
    "atmospheric": ("mood", "atmospheric"),
    "cozy": ("mood", "cozy"),
    "tense": ("mood", "tense"),
    "contemplative": ("mood", "contemplative"),
    "reflective": ("mood", "contemplative"),
    "heartwarming": ("mood", "heartwarming"),
    "eerie": ("mood", "eerie"),
    "nostalgic": ("mood", "nostalgic"),
    "humorous": ("mood", "humorous"),
    "inspiring": ("mood", "inspiring"),
    "hopeful": ("mood", "uplifting"),
    "romantic": ("mood", "romantic"),
    "thought-provoking": ("mood", "thought-provoking"),
    "challenging": ("mood", "thought-provoking"),
    "action-packed": ("mood", "action-packed"),
    "adventurous": ("mood", "action-packed"),
    "philosophical": ("mood", "philosophical"),
    "mysterious": ("mood", "suspenseful"),
    "relaxing": ("mood", "cozy"),
    "informative": ("mood", "thought-provoking"),
    "bittersweet": ("mood", "bittersweet"),
    "gritty": ("mood", "gritty"),
    # ── Genre-level ignores (too generic, map to nothing) ──
    # "fiction", "novels", "fiction & literature", "audiobook" — intentionally unmapped
    # ── Additional subgenre synonyms ──
    "speculative fiction": ("genre", "science fiction"),
    "space": ("subgenre", "space opera"),
    # ── Additional mood synonyms ──
    "sad": ("mood", "melancholic"),
    # ── Additional trope/theme synonyms ──
    "alien contact": ("trope", "first contact"),
    "space exploration": ("theme", "space exploration"),
    "genetic engineering": ("theme", "technology"),
    # ── Additional genre/subgenre synonyms ──
    "detective": ("subgenre", "detective"),
    "detective fiction": ("subgenre", "detective"),
    "mystery & detective": ("subgenre", "detective"),
    "japanese literature": ("genre", "literary fiction"),
    "classics": ("subgenre", "classics"),
    "classic": ("subgenre", "classics"),
    "classic literature": ("subgenre", "classics"),
    "世界經典文學": ("subgenre", "classics"),
    "經典文學": ("subgenre", "classics"),
    "political": ("subgenre", "politics"),
    # ── Chinese synonyms (Readmoo / epub / calibre) ──
    "推理": ("genre", "mystery"),
    "推理小說": ("genre", "mystery"),
    "犯罪小說": ("genre", "crime"),
    "犯罪": ("genre", "crime"),
    "文學小說": ("genre", "literary fiction"),
    "文學": ("genre", "literary fiction"),
    "歷史小說": ("genre", "historical fiction"),
    "驚悚": ("genre", "thriller"),
    "驚悚小說": ("genre", "thriller"),
    "恐怖": ("genre", "horror"),
    "恐怖小說": ("genre", "horror"),
    "愛情": ("genre", "romance"),
    "愛情小說": ("genre", "romance"),
    "喜劇": ("genre", "comedy"),
    "詩": ("genre", "poetry"),
    "散文": ("genre", "essay"),
    "傳記": ("genre", "biography"),
    "回憶錄": ("genre", "memoir"),
    "冒險": ("genre", "adventure"),
    "冒險小說": ("genre", "adventure"),
    "科幻": ("genre", "science fiction"),
    "科幻小說": ("genre", "science fiction"),
    "奇幻": ("genre", "fantasy"),
    "奇幻小說": ("genre", "fantasy"),
    "奇幻科幻小說": ("genre", "science fiction"),
    # ── Readmoo category synonyms (high frequency) ──
    "社會科學": ("subgenre", "sociology"),
    "商業理財": ("subgenre", "business"),
    "勵志成長": ("subgenre", "self-help"),
    "個人成長": ("subgenre", "self-help"),
    "勵志故事": ("subgenre", "self-help"),
    "成功法": ("subgenre", "self-help"),
    "人文歷史": ("subgenre", "history"),
    "中國史地": ("subgenre", "history"),
    "世界史地": ("subgenre", "history"),
    "醫療保健": ("subgenre", "health"),
    "健康養生": ("subgenre", "health"),
    "疾病": ("subgenre", "health"),
    "藝術設計": ("subgenre", "art"),
    "繪畫": ("subgenre", "art"),
    "自然科普": ("subgenre", "popular science"),
    "投資理財": ("subgenre", "economics"),
    "旅遊觀光": ("subgenre", "travel writing"),
    "台灣旅遊": ("subgenre", "travel writing"),
    "羅曼史": ("genre", "romance"),
    "言情小說": ("genre", "romance"),
    "古典言情": ("genre", "romance"),
    "食譜": ("subgenre", "cooking"),
    "青少年與兒童": ("genre", "children"),
    "繪本": ("genre", "children"),
    "職場工作": ("subgenre", "business"),
    "領導管理": ("subgenre", "business"),
    "人際關係": ("subgenre", "psychology"),
    "社會議題": ("subgenre", "sociology"),
    "美容美體": ("subgenre", "health"),
    "攝影": ("subgenre", "art"),
    "運動": ("subgenre", "sports"),
    "生活風格": ("subgenre", "self-help"),
    # ── Hardcover genre synonyms ──
    "business & economics": ("subgenre", "business"),
    "finance": ("subgenre", "economics"),
    "lgbtq": ("theme", "identity"),
    "social science": ("subgenre", "sociology"),
    "health & fitness": ("subgenre", "health"),
    "body, mind & spirit": ("subgenre", "self-help"),
    "family & relationships": ("theme", "family"),
    "technology & engineering": ("subgenre", "technology"),
    "computers": ("subgenre", "technology"),
    "biography & autobiography": ("genre", "biography"),
    "literary collections": ("genre", "literary fiction"),
    "nature": ("theme", "nature"),
    "nonfiction": ("genre", "literary fiction"),
    "young adult nonfiction": ("genre", "young adult"),
    "shoujo": ("subgenre", "light novel"),
    # ── Calibre / epub tag synonyms ──
    "漫畫": ("genre", "graphic novel"),
    "輕小說": ("subgenre", "light novel"),
    "財經": ("subgenre", "economics"),
    "寫作": ("genre", "essay"),
    # ── Theme mappings ──
    "identity": ("theme", "identity"),
    "death": ("theme", "mortality"),
    "mortality": ("theme", "mortality"),
    "love": ("theme", "love"),
    "family": ("theme", "family"),
    "friendship": ("theme", "friendship"),
    "power": ("theme", "power"),
    "freedom": ("theme", "freedom"),
    "war": ("theme", "war"),
    "warfare": ("theme", "war"),
    "survival": ("theme", "survival"),
    "mental health": ("theme", "mental health"),
    "grief": ("theme", "grief"),
    "betrayal": ("theme", "betrayal"),
    "redemption": ("theme", "redemption"),
    "rebellion": ("theme", "rebellion"),
    "justice": ("theme", "justice"),
    "trauma": ("theme", "trauma"),
    # ── Trope mappings ──
    "found family": ("trope", "found family"),
    "enemies to lovers": ("trope", "enemies to lovers"),
    "enemies-to-lovers": ("trope", "enemies to lovers"),
    "friends to lovers": ("trope", "friends to lovers"),
    "friends-to-lovers": ("trope", "friends to lovers"),
    "slow burn": ("trope", "slow burn"),
    "slow-burn": ("trope", "slow burn"),
    "chosen one": ("trope", "chosen one"),
    "the chosen one": ("trope", "chosen one"),
    "time loop": ("trope", "time loop"),
    "time travel": ("trope", "time loop"),
    "forced proximity": ("trope", "forced proximity"),
    "love triangle": ("trope", "love triangle"),
    "unreliable narrator": ("trope", "unreliable narrator"),
    "fake relationship": ("trope", "fake relationship"),
    "fake dating": ("trope", "fake relationship"),
    "fated mates": ("trope", "fated mates"),
    "forbidden love": ("trope", "forbidden love"),
    "forbidden romance": ("trope", "forbidden love"),
    "second chance": ("trope", "second chance romance"),
    "second chance romance": ("trope", "second chance romance"),
    "arranged marriage": ("trope", "arranged marriage"),
    "portal fantasy": ("trope", "portal fantasy"),
    "穿越": ("trope", "portal fantasy"),
    "江湖": ("trope", "jianghu"),
    "轉生": ("trope", "reincarnation"),
    "重生": ("trope", "reincarnation"),
    "宮廷": ("trope", "imperial court intrigue"),
    "宗門": ("trope", "sect politics"),
}


def _normalize(tag: str) -> str:
    """Normalize a raw tag for synonym lookup."""
    tag = tag.strip().lower()
    # Remove common prefixes from Google Books hierarchical categories
    # e.g., "fiction / science fiction / hard science fiction" → "hard science fiction"
    if " / " in tag:
        tag = tag.rsplit(" / ", 1)[-1]
    # Remove common noise
    tag = re.sub(r"[_\-]+", " ", tag)
    tag = re.sub(r"\s+", " ", tag).strip()
    return tag


def _split_raw_tags(raw_tags: list[str]) -> list[str]:
    """Split compound tags (e.g. Readmoo's '推理\\\\犯罪小說') into individual tags."""
    result: list[str] = []
    for tag in raw_tags:
        # Split on backslash, slash, or Chinese separator
        parts = re.split(r"[\\／/]", tag)
        for part in parts:
            part = part.strip()
            if part:
                result.append(part)
    return result


MAX_PER_CATEGORY: dict[str, int] = {
    "genre": 2,
    "subgenre": 3,
    "mood": 3,
    "theme": 4,
    "trope": 4,
}


def map_raw_tags(
    raw_tags: list[str],
) -> list[tuple[str, str]]:
    """Map a list of raw tag strings to (category, curated_slug) pairs.

    Returns only matched tags, capped per category to avoid noise.
    Unmatched tags are silently dropped.
    """
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    category_counts: dict[str, int] = {}

    for raw in raw_tags:
        normalized = _normalize(raw)
        if not normalized:
            continue

        match = SYNONYM_MAP.get(normalized)
        if not match or match[1] in seen:
            continue

        category = match[0]
        count = category_counts.get(category, 0)
        if count >= MAX_PER_CATEGORY.get(category, 3):
            continue

        results.append(match)
        seen.add(match[1])
        category_counts[category] = count + 1

    return results


def collect_raw_tags_from_metadata(
    external_metadata: list[dict],
    epub_tags: list[str] | None = None,
) -> list[str]:
    """Collect all raw tags from external metadata sources and epub tags.

    Args:
        external_metadata: List of dicts with 'source' and 'raw_data' keys
        epub_tags: Tags from EPUB metadata / Calibre
    """
    raw_tags: list[str] = []

    for meta in external_metadata:
        raw_data = meta.get("raw_data") or {}
        source = meta.get("source", "")

        if source == "goodreads":
            raw_tags.extend(raw_data.get("genres", []))
            raw_tags.extend(raw_data.get("shelves", []))

        elif source == "readmoo":
            raw_tags.extend(raw_data.get("categories", []))

        elif source == "google_books":
            # Hierarchical strings like "Fiction / Science Fiction"
            for cat in raw_data.get("categories", []):
                raw_tags.append(cat)
                # Also add each level separately
                for part in cat.split(" / "):
                    part = part.strip()
                    if part:
                        raw_tags.append(part)
            if raw_data.get("mainCategory"):
                raw_tags.append(raw_data["mainCategory"])

        elif source == "hardcover":
            raw_tags.extend(raw_data.get("genres", []))
            raw_tags.extend(raw_data.get("moods", []))
            raw_tags.extend(raw_data.get("tags", []))

    if epub_tags:
        raw_tags.extend(epub_tags)

    return _split_raw_tags(raw_tags)


async def generate_tags_from_metadata(
    db: AsyncSession,
    book_id: uuid.UUID,
) -> int:
    """Generate curated tags for a book from its external metadata + epub tags.

    Deterministic: no LLM calls. Uses synonym mapping only.
    """
    # Fetch external metadata
    result = await db.execute(
        text("SELECT source, raw_data FROM external_metadata WHERE book_id = :book_id"),
        {"book_id": str(book_id)},
    )
    external_metadata = [
        {"source": row[0], "raw_data": row[1]} for row in result.fetchall()
    ]

    # Fetch epub_tags
    result = await db.execute(
        text("SELECT epub_tags FROM books WHERE id = :book_id"),
        {"book_id": str(book_id)},
    )
    row = result.one_or_none()
    epub_tags = row[0] if row and row[0] else None

    # Collect and map
    raw_tags = collect_raw_tags_from_metadata(external_metadata, epub_tags)
    mapped = map_raw_tags(raw_tags)

    if not mapped:
        return []

    # Delete existing external tags for this book, then insert with ON CONFLICT
    await db.execute(
        delete(BookTag).where(
            BookTag.book_id == book_id, BookTag.source == TagSource.external
        )
    )

    count = 0
    for category, tag_slug in mapped:
        await db.execute(
            text("""
                INSERT INTO book_tags (id, book_id, tag, category, source, confidence)
                VALUES (gen_random_uuid(), :book_id, :tag, :category, :source, :confidence)
                ON CONFLICT (book_id, tag) DO NOTHING
            """),
            {
                "book_id": str(book_id),
                "tag": tag_slug,
                "category": category,
                "source": "external",
                "confidence": 1.0,
            },
        )
        count += 1

    await db.flush()
    return count
