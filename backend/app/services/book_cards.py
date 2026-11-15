"""A book as a list shows it: the book, and what this reader has to do
with it.

Every list — the library, a series, "my books", the discover page — puts
the same card on screen, so they all get its data from here. (Each used
to assemble its own, and they had drifted: the same book showed a rating
in the library and none on the discover page.)

What the card says about the reader:

- status and favourite are the work's: the furthest any edition of it
  has got, and a favourite on any of them (``work_propagation``);
- rating and progress are this edition's own — a percentage through one
  translation says nothing about another;
- how many editions the work has, when it has more than this one.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.reading import ReadingStatus, UserBookInteraction
from app.schemas.book import BookWithInteractionOut
from app.services.work_propagation import (
    get_edition_count_map,
    get_work_propagated_interactions,
)


async def book_cards(
    db: AsyncSession, user_id: uuid.UUID, books: Sequence[Book]
) -> list[BookWithInteractionOut]:
    """The cards for these books, in the order given."""
    if not books:
        return []
    ids = [b.id for b in books]
    edition_counts = await get_edition_count_map(db, ids)
    propagated = await get_work_propagated_interactions(db, ids, user_id)
    own = {
        row.book_id: row
        for row in (
            await db.execute(
                select(
                    UserBookInteraction.book_id,
                    UserBookInteraction.rating,
                    UserBookInteraction.reading_progress,
                ).where(
                    UserBookInteraction.user_id == user_id,
                    UserBookInteraction.book_id.in_(ids),
                )
            )
        ).all()
    }

    cards = []
    for book in books:
        card = BookWithInteractionOut.model_validate(book)
        card.edition_count = edition_counts.get(book.id)
        shared = propagated.get(book.id)
        if shared:
            status = shared["reading_status"]
            card.reading_status = ReadingStatus(status) if status else None
            card.is_favorite = shared["is_favorite"]
        mine = own.get(book.id)
        if mine:
            card.user_rating = mine.rating
            progress = mine.reading_progress or {}
            card.reading_percentage = progress.get("percentage")
            card.last_read_at = progress.get("last_read_at")
        cards.append(card)
    return cards
