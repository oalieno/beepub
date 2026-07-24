"""Personal API tokens — management (cookie auth) + bearer verification.

Management endpoints require a normal web login: a stolen token must not
be able to mint more tokens. get_api_token_user is the ONLY dependency
that accepts these bearer tokens — the web API stays cookie/JWT-only,
so a token is scoped to the surfaces that explicitly opt in (MCP,
/api/tokens/verify) instead of becoming a full-power credential.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.api_token import ApiToken
from app.models.user import User
from app.schemas.api_token import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenOut,
    ApiTokenVerifyOut,
)

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

# 192-bit — ample for a bearer secret, and the resulting 36-char token
# fits on one line in the show-once dialog on a phone.
TOKEN_BYTES = 24
TOKEN_PREFIX = "bpk_"
# last_used_at is display metadata; throttle writes so busy MCP clients
# don't turn every request into an UPDATE.
LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def user_for_bearer_token(db: AsyncSession, authorization: str) -> User | None:
    """Resolve an ``Authorization: Bearer bpk_…`` header to its user.

    Returns None for anything invalid. Shared by the FastAPI dependency
    below and the MCP mount's ASGI gate.
    """
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token.startswith(TOKEN_PREFIX):
        return None

    result = await db.execute(
        select(ApiToken, User)
        .join(User, User.id == ApiToken.user_id)
        .where(ApiToken.token_hash == _hash(token))
    )
    row = result.one_or_none()
    if row is None:
        return None
    api_token, user = row
    if not user.is_active:
        return None

    now = datetime.now(UTC)
    if (
        api_token.last_used_at is None
        or now - api_token.last_used_at > LAST_USED_WRITE_INTERVAL
    ):
        await db.execute(
            update(ApiToken)
            .where(ApiToken.id == api_token.id)
            .values(last_used_at=now)
        )
        await db.commit()
    return user


async def get_api_token_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Authenticate a bearer API token (bpk_…) — machine surfaces only."""
    user = await user_for_bearer_token(db, request.headers.get("Authorization", ""))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("", response_model=list[ApiTokenOut])
async def list_tokens(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == current_user.id)
        .order_by(ApiToken.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    name = body.name.strip()
    # Names are how users tell tokens apart when revoking — duplicates
    # would make that a guessing game.
    existing = await db.scalar(
        select(ApiToken.id).where(
            ApiToken.user_id == current_user.id, ApiToken.name == name
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="A token with this name already exists"
        )

    token = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)
    row = ApiToken(
        user_id=current_user.id,
        name=name,
        token_hash=_hash(token),
        token_prefix=token[:12],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    # The plaintext leaves the server exactly once, right here.
    return ApiTokenCreated(
        id=row.id,
        name=row.name,
        token_prefix=row.token_prefix,
        created_at=row.created_at,
        last_used_at=None,
        token=token,
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(ApiToken).where(
            ApiToken.id == token_id, ApiToken.user_id == current_user.id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Token not found")
    await db.delete(row)
    await db.commit()


@router.get("/verify", response_model=ApiTokenVerifyOut)
async def verify_token(
    user: Annotated[User, Depends(get_api_token_user)],
):
    """Bearer-token probe so users (and tests) can check their setup."""
    return ApiTokenVerifyOut(username=user.username)
