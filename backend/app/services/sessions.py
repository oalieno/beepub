"""Logins (models/session.py): opening, finding, extending, ending."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.session import UserSession

# How stale `last_used_at` may get before a request bothers to move it:
# one write an hour per login, not one per request.
_TOUCH_EVERY = timedelta(hours=1)


def _idle_period() -> timedelta:
    return timedelta(days=settings.session_idle_days)


async def open_session(
    db: AsyncSession, user_id: uuid.UUID, user_agent: str | None
) -> UserSession:
    """A new login for this user (the caller commits). The user's logins
    that have run out are cleared away on the same occasion."""
    now = datetime.now(UTC)
    await db.execute(
        delete(UserSession).where(
            UserSession.user_id == user_id, UserSession.expires_at <= now
        )
    )
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user_id,
        last_used_at=now,
        expires_at=now + _idle_period(),
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    return session


async def find_session(
    db: AsyncSession, session_id: str | None, user_id: str | None
) -> UserSession | None:
    """The login a token names, if it is this user's, still exists and
    has not run out."""
    try:
        sid = uuid.UUID(str(session_id))
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return None
    session = await db.scalar(
        select(UserSession).where(UserSession.id == sid, UserSession.user_id == uid)
    )
    if session is None or session.expires_at <= datetime.now(UTC):
        return None
    return session


async def touch(db: AsyncSession, session: UserSession, *, force: bool = False) -> None:
    """The login was just used: it now runs out a full idle period from
    here. Written at most once an hour unless forced, and committed at
    once — it is not part of whatever the request goes on to do."""
    now = datetime.now(UTC)
    if not force and now - session.last_used_at < _TOUCH_EVERY:
        return
    session.last_used_at = now
    session.expires_at = now + _idle_period()
    await db.commit()


async def end_session(db: AsyncSession, session_id: str | None) -> None:
    """End one login (the caller commits). Unknown ids are ignored."""
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        return
    await db.execute(delete(UserSession).where(UserSession.id == sid))


async def end_other_sessions(
    db: AsyncSession, user_id: uuid.UUID, keep: str | None = None
) -> None:
    """End every login of this user except `keep` (the caller commits)."""
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep:
        try:
            stmt = stmt.where(UserSession.id != uuid.UUID(str(keep)))
        except ValueError:
            pass
    await db.execute(stmt)
