from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Session, User, as_utc, utcnow
from .oidc import unsign_sid
from .settings import get_settings

DbSession = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Authenticated:
    user: User
    session: Session


async def load_session(request: Request, db: AsyncSession) -> Session | None:
    settings = get_settings()
    raw = request.cookies.get(settings.SID_COOKIE)
    if not raw:
        return None
    sid = unsign_sid(raw)
    if not sid:
        return None
    session = await db.get(Session, sid)
    if session is None or session.user_id is None:
        return None
    expires_at = as_utc(session.expires_at)
    if expires_at is None or expires_at <= utcnow():
        return None
    return session


async def require_auth(request: Request, db: DbSession) -> Authenticated:
    # API fetchers get a JSON 401, never a redirect to the issuer: a redirect
    # here would turn every SPA fetch into a navigation.
    session = await load_session(request, db)
    if session is None:
        raise HTTPException(401, "authentication required")
    user = await db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, "authentication required")
    return Authenticated(user=user, session=session)


async def require_user(request: Request, db: DbSession) -> User:
    return (await require_auth(request, db)).user


async def require_admin(request: Request, db: DbSession) -> User:
    user = (await require_auth(request, db)).user
    if not user.is_admin:
        raise HTTPException(403, "admin privileges required")
    return user


async def require_csrf(request: Request, db: DbSession) -> Authenticated:
    settings = get_settings()
    auth = await require_auth(request, db)
    expected = auth.session.csrf_token or ""
    header = request.headers.get(settings.CSRF_HEADER, "")
    cookie = request.cookies.get(settings.CSRF_COOKIE, "")
    if not expected or not header or not cookie:
        raise HTTPException(403, "csrf token required")
    if not secrets.compare_digest(header, expected) or not secrets.compare_digest(cookie, expected):
        raise HTTPException(403, "csrf token mismatch")
    return auth


def owned_or_admin(user: User, owner_id: int) -> bool:
    return user.is_admin or user.id == owner_id


def ensure_owned_or_admin(user: User, owner_id: int) -> None:
    if not owned_or_admin(user, owner_id):
        raise HTTPException(403, "not your resource")
