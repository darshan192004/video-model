from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from authlib.integrations.starlette_client import OAuth
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .settings import get_settings

_client: StarletteOAuth2App | None = None
_client_issuer = ""


def oauth_registry() -> OAuth:
    settings = get_settings()
    oauth = OAuth()
    oauth.register(
        name="dex",
        server_metadata_url=(
            f"{settings.dex_oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        ),
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={
            "scope": "openid profile email groups",
            "code_challenge_method": "S256",
        },
    )
    return oauth


async def get_oidc_client(request: Request) -> StarletteOAuth2App:
    global _client, _client_issuer
    settings = get_settings()
    if _client is None or _client_issuer != settings.dex_oidc_issuer:
        client = oauth_registry().create_client("dex")
        await client.load_server_metadata()
        # Discovery is cached per issuer so the login path does not pay a
        # network round trip on every authorization.
        _client, _client_issuer = client, settings.dex_oidc_issuer
    return _client


async def start_authorize(request: Request, *, state: str, nonce: str) -> str:
    client = await get_oidc_client(request)
    return await client.authorize_redirect(
        request,
        state=state,
        nonce=nonce,
        redirect_uri=get_settings().oidc_redirect_uri,
    )


async def exchange_code(request: Request, *, nonce: str) -> dict[str, Any]:
    client = await get_oidc_client(request)
    token = await client.authorize_access_token(
        request,
        redirect_uri=get_settings().oidc_redirect_uri,
        nonce=nonce,
    )
    claims = token.get("userinfo")
    if not claims:
        claims = client.parse_id_token(token, nonce=nonce)
    return dict(claims)


def mock_identity(email: str, groups: Iterable[str]) -> dict[str, Any]:
    # Test-mode stand-in for the issuer: a stable synthetic subject so repeated
    # logins from unit tests hit the same users row.
    return {
        "sub": f"mock:{email}",
        "email": email,
        "name": email.split("@", 1)[0],
        "groups": list(groups),
    }


def parse_group_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _group_keys(value: str) -> set[str]:
    keys = {value.strip().lower()}
    # FreeIPA hands over group names as DNs; compare the RDN value too.
    first = value.split(",", 1)[0].strip()
    if "=" in first:
        keys.add(first.rsplit("=", 1)[1].strip().lower())
    return {key for key in keys if key}


def is_admin(groups: Iterable[str] | None, admin_groups: Iterable[str]) -> bool:
    wanted: set[str] = set()
    for name in admin_groups:
        wanted |= _group_keys(name)
    if not wanted:
        return False
    for group in groups or ():
        if _group_keys(str(group)) & wanted:
            return True
    return False


def _sid_serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.session_secret, salt=settings.SID_SALT)


def sign_sid(sid: str) -> str:
    return _sid_serializer().dumps(sid)


def unsign_sid(value: str) -> str | None:
    settings = get_settings()
    try:
        return _sid_serializer().loads(value, max_age=settings.SESSION_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
