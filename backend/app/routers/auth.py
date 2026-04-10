from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models.user import User, UserRole
from app.rate_limit import limiter
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginResponse,
    RefreshResponse,
    RegisterRequest,
)
from app.schemas.user import UserOut
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.settings import get_setting

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_COOKIE_NAME = "token"
REFRESH_COOKIE_NAME = "refresh_token"
# Refresh cookie is scoped to /api/auth so it's only sent to refresh/logout —
# this is a CSRF defence in depth (it's never attached to normal API calls).
REFRESH_COOKIE_PATH = "/api/auth"


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME, httponly=True, secure=True, samesite="lax", path="/"
    )
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


@router.get("/registration-status")
async def registration_status(db: Annotated[AsyncSession, Depends(get_db)]):
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar()
    if user_count == 0:
        return {"registration_enabled": True, "first_user": True}
    reg_enabled = await get_setting(db, "registration_enabled")
    return {"registration_enabled": reg_enabled == "true", "first_user": False}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Check username uniqueness
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    # First user becomes admin
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar()
    role = UserRole.admin if user_count == 0 else UserRole.user

    # If not the first user, check if registration is enabled
    if user_count > 0:
        reg_enabled = await get_setting(db, "registration_enabled")
        if reg_enabled != "true":
            raise HTTPException(
                status_code=403, detail="Registration is currently closed"
            )

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account is disabled")

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)
    return LoginResponse(
        id=str(user.id),
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Exchange a valid refresh token for a fresh access token.

    Accepts the refresh token from either the HttpOnly `refresh_token` cookie
    (web) or the `X-Refresh-Token` header (Capacitor / native clients, where
    cookies don't reliably cross the capacitor://localhost ↔ https origin gap).
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )

    raw = request.headers.get("X-Refresh-Token") or request.cookies.get(
        REFRESH_COOKIE_NAME
    )
    if not raw:
        raise invalid

    payload = decode_token(raw)
    if payload is None or payload.get("type") != "refresh":
        _clear_auth_cookies(response)
        raise invalid

    user_id = payload.get("sub")
    if not user_id:
        _clear_auth_cookies(response)
        raise invalid

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        _clear_auth_cookies(response)
        raise invalid

    new_access = create_access_token({"sub": str(user.id)})
    _set_access_cookie(response, new_access)
    return RefreshResponse(access_token=new_access)


@router.post("/logout")
async def logout(response: Response):
    _clear_auth_cookies(response)
    return {"ok": True}


@router.put("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
