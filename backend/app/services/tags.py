"""Curated tag vocabulary, synonym mapping, and AI auto-tagging."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import BookTag, TagSource

logger = logging.getLogger(__name__)

# ── Curated vocabulary: English slug → Chinese label, by category ──
# Ref: BISAC Subject Headings, THEMA, StoryGraph, BookTok, TV Tropes, 起點/晉江
CURATED_TAGS_WITH_LABELS: dict[str, dict[str, str]] = {
    "genre": {
        # Broad classification, 1-2 per book (ref: BISAC top-level FIC codes)
        "science fiction": "科幻",
        "fantasy": "奇幻",
        "mystery": "推理",
        "thriller": "驚悚",
        "romance": "愛情",
        "horror": "恐怖",
        "literary fiction": "文學小說",
        "historical fiction": "歷史小說",
        "crime": "犯罪",
        "adventure": "冒險",
        "comedy": "喜劇",
        "satire": "諷刺",
        "drama": "劇情",
        "biography": "傳記",
        "memoir": "回憶錄",
        "poetry": "詩",
        "essay": "散文",
        "graphic novel": "圖像小說",
        "young adult": "青少年",
        "children": "兒童",
    },
    "subgenre": {
        # Specific flavor, 1-3 per book (ref: BISAC subcategories + BookTok)
        # Sci-fi
        "hard sci-fi": "硬科幻",
        "space opera": "太空歌劇",
        "cyberpunk": "賽博龐克",
        "post-apocalyptic": "末日後",
        "military sci-fi": "軍事科幻",
        "solarpunk": "太陽龐克",
        "dystopian": "反烏托邦",
        # Fantasy
        "high fantasy": "史詩奇幻",
        "urban fantasy": "都市奇幻",
        "dark fantasy": "黑暗奇幻",
        "grimdark": "殘酷奇幻",
        "cozy fantasy": "舒適奇幻",
        "sword and sorcery": "劍與魔法",
        "romantasy": "浪漫奇幻",
        "magical realism": "魔幻寫實",
        # Mystery/Crime
        "cozy mystery": "舒適推理",
        "noir": "黑色",
        "police procedural": "警察程序",
        "detective": "偵探",
        "true crime": "真實犯罪",
        # Thriller
        "psychological thriller": "心理驚悚",
        "domestic thriller": "家庭驚悚",
        "legal thriller": "法律驚悚",
        # Horror
        "gothic horror": "哥德恐怖",
        "cosmic horror": "宇宙恐怖",
        # Romance
        "contemporary romance": "現代愛情",
        "historical romance": "歷史愛情",
        "paranormal romance": "超自然愛情",
        "dark romance": "黑暗愛情",
        "romantic comedy": "浪漫喜劇",
        # CJK-specific
        "wuxia": "武俠",
        "xianxia": "仙俠",
        "xuanhuan": "玄幻",
        "danmei": "耽美",
        "cultivation": "修真",
        "light novel": "輕小說",
        "isekai": "異世界",
        # Non-fiction
        "self-help": "自我成長",
        "popular science": "科普",
        "travel writing": "旅行文學",
        "journalism": "新聞",
        "philosophy": "哲學",
        "psychology": "心理學",
        "business": "商業",
        "economics": "經濟",
        "history": "歷史",
        "sociology": "社會學",
        "education": "教育",
        "health": "健康",
        "cooking": "料理",
        "art": "藝術",
        "music": "音樂",
        "sports": "運動",
        "religion": "宗教",
        "politics": "政治",
        "technology": "科技",
        "slice of life": "日常系",
        "dark academia": "黑暗學院",
        "classics": "經典文學",
    },
    "mood": {
        # Emotional texture, 2-3 per book (ref: StoryGraph + Hardcover moods)
        "dark": "黑暗",
        "lighthearted": "輕鬆",
        "emotional": "感人",
        "suspenseful": "懸疑",
        "whimsical": "奇趣",
        "melancholic": "憂鬱",
        "uplifting": "振奮",
        "atmospheric": "氛圍感",
        "cozy": "溫馨",
        "tense": "緊張",
        "contemplative": "沉思",
        "heartwarming": "暖心",
        "eerie": "詭異",
        "nostalgic": "懷舊",
        "humorous": "幽默",
        "inspiring": "勵志",
        "romantic": "浪漫",
        "thought-provoking": "發人深省",
        "action-packed": "動作",
        "philosophical": "哲思",
        "bittersweet": "苦甜",
        "gritty": "粗獷",
    },
    "theme": {
        # Abstract ideas explored, 2-4 per book (renamed from topic)
        "identity": "身分認同",
        "mortality": "死亡",
        "love": "愛情",
        "family": "家庭",
        "friendship": "友情",
        "power": "權力",
        "freedom": "自由",
        "loneliness": "孤獨",
        "betrayal": "背叛",
        "redemption": "救贖",
        "war": "戰爭",
        "nature": "自然",
        "technology": "科技",
        "mental health": "心理健康",
        "social justice": "社會正義",
        "class struggle": "階級鬥爭",
        "colonialism": "殖民",
        "feminism": "女性主義",
        "environmentalism": "環保",
        "corruption": "腐敗",
        "grief": "悲傷",
        "immigration": "移民",
        "rebellion": "反抗",
        "survival": "生存",
        "ambition": "野心",
        "obsession": "執念",
        "justice": "正義",
        "memory": "記憶",
        "faith": "信仰",
        "trauma": "創傷",
        "belonging": "歸屬",
        "duty": "責任",
        "consciousness": "意識",
        "cultural clash": "文化衝突",
        "sacrifice": "犧牲",
        "space exploration": "太空探索",
    },
    "trope": {
        # Concrete narrative patterns, 2-4 per book (ref: TV Tropes + BookTok)
        # General
        "unreliable narrator": "不可靠敘述者",
        "found family": "非血緣家人",
        "chosen one": "天選之人",
        "reluctant hero": "不情願英雄",
        "mentor figure": "師父",
        "time loop": "時間迴圈",
        "parallel worlds": "平行世界",
        "tournament arc": "比武大會",
        "heist": "盜竊行動",
        "locked room": "密室",
        "multiple timelines": "多重時間線",
        "slow burn": "慢熱",
        "fish out of water": "格格不入",
        "underdog story": "弱者逆襲",
        "prophecy": "預言",
        "redemption arc": "救贖弧",
        "secret society": "秘密組織",
        # Romance (ref: Scribophile/BookTok tropes)
        "enemies to lovers": "仇人變情人",
        "friends to lovers": "朋友變情人",
        "forbidden love": "禁忌之愛",
        "second chance romance": "舊情復燃",
        "fake relationship": "假戀愛",
        "forced proximity": "強制接近",
        "fated mates": "命定之人",
        "love triangle": "三角關係",
        "arranged marriage": "包辦婚姻",
        # CJK-specific (ref: 起點/晉江 web novel tags)
        "jianghu": "江湖",
        "reincarnation": "轉生",
        "sect politics": "宗門鬥爭",
        "martial arts tournament": "武鬥",
        "imperial court intrigue": "宮廷權謀",
        "cultivation system": "修煉體系",
        "spirit beasts": "靈獸",
        "face-slapping": "打臉",
        "system": "系統流",
        # Sci-fi
        "first contact": "第一次接觸",
        "ai uprising": "AI 叛變",
        "generation ship": "世代飛船",
        "virtual reality": "虛擬實境",
        # Fantasy
        "portal fantasy": "穿越",
        "magical school": "魔法學校",
        "dark lord": "魔王",
        "hidden world": "隱藏世界",
    },
}

# Flat lists (used in prompt building)
CURATED_TAGS: dict[str, list[str]] = {
    cat: list(tags.keys()) for cat, tags in CURATED_TAGS_WITH_LABELS.items()
}

# Flat lookups
_TAG_TO_CATEGORY: dict[str, str] = {}
TAG_LABELS: dict[str, str] = {}
for _cat, _tag_map in CURATED_TAGS_WITH_LABELS.items():
    for _slug, _label in _tag_map.items():
        _TAG_TO_CATEGORY[_slug] = _cat
        TAG_LABELS[_slug] = _label

SYSTEM_PROMPT = """\
You are a book tagger. Given a book's metadata, select appropriate tags from ONLY the provided vocabulary.
Return a JSON array of objects. Each object must have: "tag" (string), "category" (string), "confidence" (float 0.0-1.0).

Rules:
- Select 8-14 tags that best describe the book.
- ONLY use tags from the vocabulary below. Do NOT invent new tags.
- Do NOT use broad parent tags when a more specific child tag applies. Use "hard sci-fi" not just "science fiction". Use "wuxia" not just "fantasy".
- Prefer tags that distinguish THIS book from other books in its genre.
- For Chinese-language books, prefer CJK-specific tags (wuxia, xianxia, cultivation, jianghu) over Western equivalents.
- Select 1-2 genre, 1-3 subgenre, 2-3 mood, 2-4 theme, 2-4 trope tags.
- Confidence should reflect how certain you are (1.0 = very certain, 0.5 = uncertain).
- Only include tags you are reasonably confident about (confidence >= 0.7). Do NOT pad with low-confidence guesses.
- Return ONLY the JSON array, no other text.

Vocabulary:

Genre: {genres}

Subgenre: {subgenres}

Mood: {moods}

Theme: {themes}

Trope: {tropes}
"""


def _build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(
        genres=", ".join(CURATED_TAGS["genre"]),
        subgenres=", ".join(CURATED_TAGS["subgenre"]),
        moods=", ".join(CURATED_TAGS["mood"]),
        themes=", ".join(CURATED_TAGS["theme"]),
        tropes=", ".join(CURATED_TAGS["trope"]),
    )


def _build_user_prompt(
    title: str,
    authors: list[str] | None,
    description: str | None,
    language: str | None,
    reviews: list[dict] | None,
) -> str:
    parts = [f"Title: {title}"]
    if authors:
        parts.append(f"Authors: {', '.join(authors)}")
    if language:
        parts.append(f"Language: {language}")
    if description:
        parts.append(f"Description: {description[:2000]}")
    if reviews:
        snippets = []
        for r in reviews[:3]:
            text = r.get("text", r.get("content", ""))
            if text:
                snippets.append(text[:500])
        if snippets:
            parts.append("Reviews:\n" + "\n---\n".join(snippets))
    return "\n\n".join(parts)


def _parse_tags_response(text: str) -> list[dict]:
    """Parse LLM response and validate tags against vocabulary."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI tags response as JSON: %s", text[:200])
        return []

    if not isinstance(data, list):
        logger.warning("AI tags response is not a list")
        return []

    valid_tags = []
    seen_tags: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag", "").strip().lower()
        if tag not in _TAG_TO_CATEGORY:
            logger.debug("Skipping unknown tag: %s", tag)
            continue
        if tag in seen_tags:
            continue
        seen_tags.add(tag)
        confidence = item.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        if confidence < 0.7:
            logger.debug("Skipping low-confidence tag: %s (%.2f)", tag, confidence)
            continue
        valid_tags.append(
            {
                "tag": tag,
                "category": _TAG_TO_CATEGORY[tag],
                "confidence": confidence,
            }
        )

    return valid_tags


async def generate_ai_tags(
    title: str,
    authors: list[str] | None,
    description: str | None,
    language: str | None,
    reviews: list[dict] | None,
    db_settings: dict[str, str] | None = None,
    book_id: uuid.UUID | None = None,
    session_factory=None,
) -> list[dict]:
    """Call LLM to generate tags for a book. Returns list of {tag, category, confidence}."""
    from app.services.llm import get_tag_provider

    settings = db_settings or {}
    provider = get_tag_provider(settings)
    system = _build_system_prompt()
    user_prompt = _build_user_prompt(title, authors, description, language, reviews)

    result = await provider.generate(user_prompt, system=system)

    # Log usage (fire-and-forget)
    from app.services.llm_usage import log_llm_usage

    await log_llm_usage(
        feature="auto_tag",
        provider=settings.get("tag_provider", ""),
        model=settings.get("tag_model", ""),
        usage=result.usage,
        book_id=book_id,
        session_factory=session_factory,
    )

    return _parse_tags_response(result.text)


async def save_ai_tags(
    db: AsyncSession,
    book_id: uuid.UUID,
    tags: list[dict],
) -> int:
    """Delete existing AI tags for book and insert new ones.

    Uses raw SQL with ON CONFLICT to skip tags that already exist
    from other sources (epub, external, manual).
    """
    from sqlalchemy import text

    await db.execute(
        delete(BookTag).where(
            BookTag.book_id == book_id, BookTag.source == TagSource.ai
        )
    )

    count = 0
    for t in tags:
        await db.execute(
            text("""
                INSERT INTO book_tags (id, book_id, tag, category, source, confidence)
                VALUES (gen_random_uuid(), :book_id, :tag, :category, :source, :confidence)
                ON CONFLICT (book_id, tag) DO NOTHING
            """),
            {
                "book_id": str(book_id),
                "tag": t["tag"],
                "category": t["category"],
                "source": "ai",
                "confidence": t["confidence"],
            },
        )
        count += 1

    await db.flush()
    return count
