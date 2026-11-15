from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import errors
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
    UpdateUsernameRequest,
)
from app.schemas.user import UserOut
from app.services import login_throttle, sessions
from app.services.auth import (
    create_access_token,
    decode_token,
    derive_kosync_key_hash,
    hash_password,
    issue_tokens,
    verify_password,
)
from app.services.settings import get_setting

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_COOKIE_NAME = "token"
REFRESH_COOKIE_NAME = "refresh_token"
# The refresh cookie goes with every request, pages included: the page
# server is what notices an access token has run out and asks for a new
# one. (It used to be scoped to /api/auth, so the page server never saw
# it — and a browser was signed out whenever its access cookie expired.)
REFRESH_COOKIE_PATH = "/"
# Where older versions set it; cleared alongside, or it would linger.
LEGACY_REFRESH_COOKIE_PATH = "/api/auth"
# As long as a browser will keep a cookie. Each refresh sets it again.
REFRESH_COOKIE_MAX_AGE = 400 * 24 * 60 * 60


def _cookie_secure(request: Request) -> bool:
    # Browsers reject Set-Cookie with Secure over plain http (localhost
    # excepted), so an unconditional Secure flag breaks login entirely for
    # instances reached as http://<lan-ip>:<port>. Follow the scheme of the
    # original request instead — ProxyHeadersMiddleware has already applied
    # X-Forwarded-Proto, which nginx preserves from any TLS-terminating
    # proxy in front of it.
    return request.url.scheme == "https"


def _set_access_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=REFRESH_COOKIE_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response, secure: bool) -> None:
    # (Secure as the cookies were set: over plain http a browser ignores a
    # Set-Cookie that carries the flag — the deletion too.)
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME, httponly=True, secure=secure, samesite="lax", path="/"
    )
    for path in (REFRESH_COOKIE_PATH, LEGACY_REFRESH_COOKIE_PATH):
        response.delete_cookie(
            key=REFRESH_COOKIE_NAME,
            httponly=True,
            secure=secure,
            samesite="lax",
            path=path,
        )


@router.get("/registration-status")
async def registration_status(db: Annotated[AsyncSession, Depends(get_db)]):
    # Demo hint for the login page. Purely informational: the operator
    # created the account and chose to publish its credentials.
    demo = (
        {"username": settings.demo_username, "password": settings.demo_password}
        if settings.demo_mode
        else None
    )
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar()
    if user_count == 0:
        return {"registration_enabled": True, "first_user": True, "demo": demo}
    reg_enabled = await get_setting(db, "registration_enabled")
    return {
        "registration_enabled": reg_enabled == "true",
        "first_user": False,
        "demo": demo,
    }


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # First user becomes admin
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar()
    role = UserRole.admin if user_count == 0 else UserRole.user

    # If not the first user, check if registration is enabled — before
    # anything is said about the name: with registration closed, this
    # must not tell a stranger which usernames exist.
    if user_count > 0:
        reg_enabled = await get_setting(db, "registration_enabled")
        if reg_enabled != "true":
            raise errors.REGISTRATION_CLOSED()

    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise errors.USERNAME_EXISTS(status_code=400)

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        kosync_key_hash=derive_kosync_key_hash(body.password),
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
    if login_throttle.locked(form_data.username):
        raise errors.TOO_MANY_ATTEMPTS()
    invalid = errors.INVALID_CREDENTIALS()
    if login_throttle.refused(form_data.username, form_data.password):
        raise invalid
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.password_hash):
        login_throttle.record_wrong(form_data.username, form_data.password)
        raise invalid
    login_throttle.record_right(form_data.username)
    if not user.is_active:
        raise errors.ACCOUNT_DISABLED()

    # Accounts that predate kosync support get their sync key on first
    # login — the only later moment the plaintext is available.
    if user.kosync_key_hash is None:
        user.kosync_key_hash = derive_kosync_key_hash(form_data.password)
        await db.commit()

    session = await sessions.open_session(
        db, user.id, request.headers.get("User-Agent")
    )
    await db.commit()
    access_token, refresh_token = issue_tokens(user.id, session.id)
    secure = _cookie_secure(request)
    _set_access_cookie(response, access_token, secure)
    _set_refresh_cookie(response, refresh_token, secure)
    return LoginResponse(
        id=str(user.id),
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
        can_download=user.can_download,
        can_upload=user.can_upload,
        is_demo=bool(settings.demo_mode and user.username == settings.demo_username),
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
        _clear_auth_cookies(response, _cookie_secure(request))
        raise invalid

    user_id = payload.get("sub")
    if not user_id:
        _clear_auth_cookies(response, _cookie_secure(request))
        raise invalid

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    session = (
        await sessions.find_session(db, payload.get("sid"), user_id)
        if user is not None and user.is_active
        else None
    )
    if session is None:
        _clear_auth_cookies(response, _cookie_secure(request))
        raise invalid

    # Asking for a new access token is using the login: it now runs out a
    # full idle period from here.
    await sessions.touch(db, session, force=True)
    new_access = create_access_token({"sub": str(user.id), "sid": str(session.id)})
    secure = _cookie_secure(request)
    _set_access_cookie(response, new_access, secure)
    # (The same refresh token, set again so the browser keeps it longer.)
    _set_refresh_cookie(response, raw, secure)
    return RefreshResponse(
        access_token=new_access,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """End this login — on the server, not only on the device: its tokens
    stop working at once, wherever a copy of them may be."""
    auth_header = request.headers.get("Authorization", "")
    candidates = [
        auth_header[7:] if auth_header.startswith("Bearer ") else None,
        request.cookies.get(ACCESS_COOKIE_NAME),
        request.headers.get("X-Refresh-Token"),
        request.cookies.get(REFRESH_COOKIE_NAME),
    ]
    for raw in candidates:
        payload = decode_token(raw) if raw else None
        if payload and payload.get("sid"):
            await sessions.end_session(db, payload["sid"])
            await db.commit()
            break
    _clear_auth_cookies(response, _cookie_secure(request))
    return {"ok": True}


@router.put("/username", response_model=UserOut)
async def update_username(
    body: UpdateUsernameRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Renaming the shared demo account would break the published
    # credentials for everyone until the next data reset (same reasoning
    # as the change-password guard below).
    if settings.demo_mode and current_user.username == settings.demo_username:
        raise HTTPException(
            status_code=403,
            detail="The demo account's username cannot be changed",
        )

    if body.new_username == current_user.username:
        return current_user

    existing = await db.execute(select(User).where(User.username == body.new_username))
    if existing.scalar_one_or_none():
        raise errors.USERNAME_EXISTS(status_code=400)

    current_user.username = body.new_username
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise errors.USERNAME_EXISTS(status_code=400) from None
    await db.refresh(current_user)
    return current_user


@router.put("/change-password")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Change the password and end every login made with the old one —
    except the one doing the changing."""
    # Visitors share the demo account; letting one change the password
    # would lock everyone else out until the next data reset.
    if settings.demo_mode and current_user.username == settings.demo_username:
        raise HTTPException(
            status_code=403, detail="The demo account's password cannot be changed"
        )
    if not verify_password(body.current_password, current_user.password_hash):
        raise errors.WRONG_PASSWORD()
    current_user.password_hash = hash_password(body.new_password)
    current_user.kosync_key_hash = derive_kosync_key_hash(body.new_password)
    await sessions.end_other_sessions(
        db, current_user.id, keep=request.state.session_id
    )
    await db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
