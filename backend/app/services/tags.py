"""Curated tag vocabulary and AI auto-tagging via Gemini."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import AiBookTag, TagCategory

logger = logging.getLogger(__name__)

# English slug -> Chinese label, organized by category
CURATED_TAGS_WITH_LABELS: dict[str, dict[str, str]] = {
    "genre": {
        "fiction": "小說",
        "non-fiction": "非小說",
        "science fiction": "科幻",
        "fantasy": "奇幻",
        "mystery": "推理",
        "thriller": "驚悚",
        "romance": "愛情",
        "horror": "恐怖",
        "literary fiction": "文學小說",
        "historical fiction": "歷史小說",
        "crime": "犯罪",
        "dystopian": "反烏托邦",
        "adventure": "冒險",
        "comedy": "喜劇",
        "satire": "諷刺",
        "drama": "劇情",
        "young adult": "青少年",
        "children": "兒童",
        "graphic novel": "圖像小說",
        "light novel": "輕小說",
        "wuxia": "武俠",
        "xianxia": "仙俠",
        "isekai": "異世界",
        "biography": "傳記",
        "memoir": "回憶錄",
        "self-help": "自我成長",
        "philosophy": "哲學",
        "poetry": "詩",
        "essay": "散文",
        "science": "科學",
        "technology": "科技",
        "history": "歷史",
        "psychology": "心理學",
        "economics": "經濟",
        "business": "商業",
        "travel": "旅行",
        "cooking": "料理",
        "art": "藝術",
        "music": "音樂",
        "sports": "運動",
        "religion": "宗教",
        "politics": "政治",
        "sociology": "社會學",
        "education": "教育",
        "health": "健康",
        "true crime": "真實犯罪",
        "journalism": "新聞",
    },
    "mood": {
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
    },
    "topic": {
        "coming of age": "成長",
        "war": "戰爭",
        "love": "愛情",
        "family": "家庭",
        "friendship": "友情",
        "politics": "政治",
        "technology": "科技",
        "nature": "自然",
        "death": "死亡",
        "identity": "身分認同",
        "revenge": "復仇",
        "survival": "生存",
        "magic": "魔法",
        "time travel": "時間旅行",
        "artificial intelligence": "人工智慧",
        "space exploration": "太空探索",
        "mental health": "心理健康",
        "social justice": "社會正義",
        "religion": "宗教",
        "education": "教育",
        "power": "權力",
        "freedom": "自由",
        "loneliness": "孤獨",
        "betrayal": "背叛",
        "redemption": "救贖",
        "class struggle": "階級鬥爭",
        "colonialism": "殖民",
        "feminism": "女性主義",
        "environmentalism": "環保",
        "corruption": "腐敗",
        "addiction": "成癮",
        "grief": "悲傷",
        "immigration": "移民",
        "dystopia": "反烏托邦",
        "rebellion": "反抗",
    },
}

# Flat lists for backward compat (used in prompt building)
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
- Select 5-15 tags that best describe the book.
- ONLY use tags from the vocabulary below. Do NOT invent new tags.
- Confidence should reflect how certain you are (1.0 = very certain, 0.5 = uncertain).
- Only include tags you are reasonably confident about (confidence >= 0.7). Do NOT pad with low-confidence guesses.
- Consider the book's language and cultural context when tagging.
- Return ONLY the JSON array, no other text.

Vocabulary:

Genre: {genres}

Mood: {moods}

Topic: {topics}
"""


def _build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(
        genres=", ".join(CURATED_TAGS["genre"]),
        moods=", ".join(CURATED_TAGS["mood"]),
        topics=", ".join(CURATED_TAGS["topic"]),
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
    for item in data:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag", "").strip().lower()
        if tag not in _TAG_TO_CATEGORY:
            logger.debug("Skipping unknown tag: %s", tag)
            continue
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
) -> list[dict]:
    """Call LLM to generate tags for a book. Returns list of {tag, category, confidence}."""
    from app.services.llm import get_tag_provider

    provider = get_tag_provider(db_settings)
    system = _build_system_prompt()
    user_prompt = _build_user_prompt(title, authors, description, language, reviews)

    response = await provider.generate(user_prompt, system=system)
    return _parse_tags_response(response)


async def save_ai_tags(
    db: AsyncSession,
    book_id: uuid.UUID,
    tags: list[dict],
) -> list[AiBookTag]:
    """Delete existing AI tags for book and insert new ones."""
    await db.execute(delete(AiBookTag).where(AiBookTag.book_id == book_id))

    new_tags = []
    for t in tags:
        ai_tag = AiBookTag(
            book_id=book_id,
            tag=t["tag"],
            category=TagCategory(t["category"]),
            confidence=t["confidence"],
        )
        db.add(ai_tag)
        new_tags.append(ai_tag)

    await db.flush()
    return new_tags
