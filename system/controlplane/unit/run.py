"""In-process API assertions for the control-plane.

Driven by system/tests/controlplane_unit.sh, which supplies OIDC_MOCK=1, a
sqlite DATABASE_URL, and an SESSION_SECRET through the environment. Exercises
the unauthenticated contract, the mock browser redirect shape, the admin role
mapping, /api/auth/me, CSRF, and logout invalidation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

# Secure cookies are only replayed over https, which is what nginx terminates.
BASE_URL = "https://testserver"

results: list[tuple[bool, str, str]] = []


def check(name: str, condition: object, detail: str = "") -> bool:
    ok = bool(condition)
    results.append((ok, name, detail))
    line = f"{'PASS' if ok else 'FAIL'}: {name}"
    print(line if ok else f"{line} :: {detail}")
    return ok


def set_cookie_header(response, name: str) -> str:
    for header in response.headers.get_list("set-cookie"):
        if header.lower().startswith(f"{name.lower()}="):
            return header
    return ""


def login(client: TestClient, email: str, groups: str = ""):
    start = client.get(
        "/api/auth/start",
        params={"email": email, "groups": groups},
        follow_redirects=False,
    )
    if not check(f"start redirects ({email})", start.status_code == 302, f"got {start.status_code}"):
        return start
    location = start.headers.get("location", "")
    query = parse_qs(urlparse(location).query)
    check(
        f"start targets the mock callback ({email})",
        query.get("code") == ["mock"] and bool(query.get("state")),
        location,
    )
    done = client.get(location, follow_redirects=False)
    check(
        f"callback returns to the SPA ({email})",
        done.status_code == 302 and urlparse(done.headers.get("location", "/x")).path == "/",
        f"got {done.status_code} {done.headers.get('location')}",
    )
    return done


def main() -> int:
    with TestClient(create_app(), base_url=BASE_URL) as client:
        health = client.get("/api/healthz")
        check(
            "healthz 200 with db up",
            health.status_code == 200 and health.json().get("db") == "up",
            health.text,
        )

        anon = client.get("/api/jobs")
        check(
            "unauthenticated /api/jobs is 401 JSON",
            anon.status_code == 401
            and anon.headers.get("content-type", "").startswith("application/json"),
            f"got {anon.status_code} {anon.text}",
        )
        check("unauthenticated /api/auth/me is 401", client.get("/api/auth/me").status_code == 401)

        callback = login(client, "admin@test", "media-admins")
        sid = set_cookie_header(callback, "media_sid")
        csrf_header = set_cookie_header(callback, "media_csrf")
        check("media_sid cookie is set", bool(sid), str(callback.headers))
        check(
            "media_sid is HttpOnly/Secure/SameSite=Lax/Path=/",
            all(token in sid.lower() for token in ("httponly", "secure", "samesite=lax", "path=/")),
            sid,
        )
        check(
            "media_csrf cookie is set and script-readable",
            bool(csrf_header) and "httponly" not in csrf_header.lower(),
            csrf_header,
        )

        me = client.get("/api/auth/me")
        body = me.json() if me.status_code == 200 else {}
        check(
            "me roundtrip shows the admin identity",
            me.status_code == 200
            and body.get("email") == "admin@test"
            and body.get("is_admin") is True,
            me.text,
        )
        check(
            "me carries the groups claim",
            body.get("groups") == ["media-admins"],
            str(body.get("groups")),
        )
        check("authenticated /api/jobs is 200", client.get("/api/jobs").status_code == 200)

        check(
            "logout without X-CSRF is 403",
            client.post("/api/auth/logout").status_code == 403,
        )
        csrf = client.cookies.get("media_csrf") or ""
        out = client.post("/api/auth/logout", headers={"X-CSRF": csrf})
        check("logout with X-CSRF succeeds", out.status_code == 204, f"got {out.status_code}")
        check("logout invalidates the session", client.get("/api/auth/me").status_code == 401)
        check("protected route is 401 after logout", client.get("/api/jobs").status_code == 401)

        login(client, "user@test")
        me_user = client.get("/api/auth/me")
        user_body = me_user.json() if me_user.status_code == 200 else {}
        check(
            "non-admin identity is not an admin",
            me_user.status_code == 200
            and user_body.get("email") == "user@test"
            and user_body.get("is_admin") is False,
            me_user.text,
        )

    failed = [name for ok, name, _ in results if not ok]
    print(f"controlplane_unit: {len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("controlplane_unit: FAILED -> " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
