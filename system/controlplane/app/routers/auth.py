"""OIDC authorization-code endpoints and the server-side session lifecycle."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import Authenticated, DbSession, require_csrf, require_user
from ..models import Session, User, as_utc, utcnow
from ..oidc import (
    exchange_code,
    is_admin,
    mock_identity,
    parse_group_list,
    sign_sid,
    start_authorize,
)
from ..settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

AuthCsrf = Annotated[Authenticated, Depends(require_csrf)]


async def _create_pending(db: AsyncSession, *, state: str, nonce: str) -> None:
    settings = get_settings()
    db.add(
        Session(
            user_id=None,
            csrf_token=None,
            state=state,
            nonce=nonce,
            expires_at=utcnow() + timedelta(seconds=settings.AUTHZ_TTL_SECONDS),
        )
    )
    await db.commit()


async def _claim_pending(db: AsyncSession, state: str | None) -> Session:
    if not state:
        raise HTTPException(400, "missing state")
    pending = (
        await db.execute(select(Session).where(Session.state == state))
    ).scalar_one_or_none()
    expires_at = as_utc(pending.expires_at) if pending is not None else None
    if pending is None or pending.user_id is not None or expires_at is None or expires_at <= utcnow():
        raise HTTPException(400, "invalid or expired state")
    return pending


async def _upsert_user(db: AsyncSession, claims: dict, admin_groups: set[str]) -> User:
    subject = str(claims.get("sub") or "")
    if not subject:
        raise HTTPException(400, "id token without sub")
    groups = [str(group) for group in (claims.get("groups") or [])]
    admin = is_admin(groups, admin_groups)
    name = claims.get("name")
    email = claims.get("email")
    user = (
        await db.execute(select(User).where(User.subject == subject))
    ).scalar_one_or_none()
    if user is None:
        user = User(subject=subject, name=name, email=email, groups=groups, is_admin=admin)
        db.add(user)
        await db.flush()
        return user
    user.name = name
    user.email = email
    user.groups = groups
    # Roles are re-derived server-side on every login; the client cannot set them.
    user.is_admin = admin
    await db.flush()
    return user


@router.get("/start")
async def start(request: Request, db: DbSession) -> RedirectResponse:
    settings = get_settings()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(16)
    await _create_pending(db, state=state, nonce=nonce)
    if settings.oidc_mock:
        if "email" in request.query_params:
            email = request.query_params["email"]
            groups = request.query_params.get("groups", "")
        else:
            email = "admin@test"
            groups = request.query_params.get(
                "groups", ",".join(sorted(settings.admin_group_names))
            )
        query = urlencode(
            {
                "code": "mock",
                "state": state,
                "email": email,
                "groups": ",".join(parse_group_list(groups)),
            }
        )
        target = str(request.url_for("auth_callback")) + "?" + query
        return RedirectResponse(target, status_code=302)
    return RedirectResponse(await start_authorize(request, state=state, nonce=nonce), status_code=302)


@router.get("/callback", name="auth_callback")
async def callback(request: Request, db: DbSession) -> RedirectResponse:
    settings = get_settings()
    pending = await _claim_pending(db, request.query_params.get("state"))
    if settings.oidc_mock:
        if request.query_params.get("code") != "mock":
            raise HTTPException(400, "invalid mock authorization code")
        if "email" in request.query_params:
            email = request.query_params["email"]
            groups = request.query_params.get("groups", "")
        else:
            email = "admin@test"
            groups = request.query_params.get(
                "groups", ",".join(sorted(settings.admin_group_names))
            )
        claims = mock_identity(email, parse_group_list(groups))
    else:
        claims = await exchange_code(request, nonce=pending.nonce or "")

    user = await _upsert_user(db, claims, settings.admin_group_names)
    session = Session(
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        state=None,
        nonce=None,
        expires_at=utcnow() + timedelta(seconds=settings.SESSION_TTL_SECONDS),
    )
    await db.execute(delete(Session).where(Session.id == pending.id))
    db.add(session)
    await db.commit()

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        settings.SID_COOKIE,
        sign_sid(session.id),
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.CSRF_COOKIE,
        session.csrf_token or "",
        max_age=settings.SESSION_TTL_SECONDS,
        # Readable by the SPA bundle: it echoes the value in the X-CSRF header.
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(auth: AuthCsrf, db: DbSession) -> Response:
    settings = get_settings()
    await db.execute(delete(Session).where(Session.id == auth.session.id))
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(settings.SID_COOKIE, path="/")
    response.delete_cookie(settings.CSRF_COOKIE, path="/")
    return response


@router.get("/me")
async def me(user: Annotated[User, Depends(require_user)]) -> dict:
    return {
        "name": user.name,
        "email": user.email,
        "is_admin": user.is_admin,
        "groups": list(user.groups or []),
    }
