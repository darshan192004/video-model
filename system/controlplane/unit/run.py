"""In-process API assertions for the control-plane."""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import GalleryMedia, Job, User  # noqa: E402
from app.settings import get_settings  # noqa: E402

BASE_URL = "https://testserver"
EXPECTED_CHECKS = 58

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


def csrf_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF": client.cookies.get("media_csrf") or ""}


async def mark_running(job_id: str) -> None:
    async with get_sessionmaker()() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is None:
            raise RuntimeError(f"missing job fixture {job_id}")
        job.status = "running"
        await db.commit()


async def seed_gallery_item(email: str, label: str) -> dict[str, int | str]:
    async with get_sessionmaker()() as db:
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one()
        job = Job(
            owner_id=user.id,
            template_id="smoke",
            params={"seed": label},
            status="success",
            counts={"completed": 1},
        )
        db.add(job)
        await db.flush()
        content = f"fixture-{label}".encode()
        directory = Path(get_settings().gallery_root) / str(user.id) / str(job.id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{label}.png"
        path.write_bytes(content)
        media = GalleryMedia(
            job_id=job.id,
            user_id=user.id,
            kind="image",
            filename=path.name,
            size_bytes=len(content),
            content_type="image/png",
            sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(media)
        await db.commit()
        return {
            "user_id": user.id,
            "job_id": str(job.id),
            "media_id": media.id,
        }


def main() -> int:
    with TestClient(create_app(), base_url=BASE_URL) as client:
        health = client.get("/api/healthz")
        check(
            "healthz 200 with db up",
            health.status_code == 200 and health.json().get("db") == "up",
            health.text,
        )

        anon_jobs = client.get("/api/jobs")
        check(
            "unauthenticated /api/jobs is 401 JSON",
            anon_jobs.status_code == 401
            and anon_jobs.headers.get("content-type", "").startswith("application/json"),
            f"got {anon_jobs.status_code} {anon_jobs.text}",
        )
        anon_gallery = client.get("/api/gallery")
        check(
            "unauthenticated /api/gallery is 401 JSON",
            anon_gallery.status_code == 401
            and anon_gallery.headers.get("content-type", "").startswith("application/json"),
            f"got {anon_gallery.status_code} {anon_gallery.text}",
        )
        anon_admin = client.get("/api/admin/system")
        check(
            "unauthenticated /api/admin/system is 401 JSON",
            anon_admin.status_code == 401
            and anon_admin.headers.get("content-type", "").startswith("application/json"),
            f"got {anon_admin.status_code} {anon_admin.text}",
        )
        check("unauthenticated /api/auth/me is 401", client.get("/api/auth/me").status_code == 401)

        start = client.get("/api/auth/start", follow_redirects=False)
        check(
            "plain mock sign-in redirects",
            start.status_code == 302,
            f"got {start.status_code}",
        )
        location = start.headers.get("location", "")
        query = parse_qs(urlparse(location).query)
        check(
            "plain mock sign-in defaults to admin@test and its group",
            query.get("email") == ["admin@test"] and query.get("groups") == ["media-admins"],
            location,
        )
        callback = client.get(location, follow_redirects=False)
        check(
            "plain mock callback returns to the SPA",
            callback.status_code == 302
            and urlparse(callback.headers.get("location", "/x")).path == "/",
            f"got {callback.status_code} {callback.headers.get('location')}",
        )
        sid = set_cookie_header(callback, "media_sid")
        csrf_cookie = set_cookie_header(callback, "media_csrf")
        check("media_sid cookie is set", bool(sid), str(callback.headers))
        check(
            "media_sid is HttpOnly/Secure/SameSite=Lax/Path=/",
            all(token in sid.lower() for token in ("httponly", "secure", "samesite=lax", "path=/")),
            sid,
        )
        check(
            "media_csrf cookie is set and script-readable",
            bool(csrf_cookie) and "httponly" not in csrf_cookie.lower(),
            csrf_cookie,
        )

        me = client.get("/api/auth/me")
        body = me.json() if me.status_code == 200 else {}
        check(
            "me roundtrip shows the default admin identity",
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

        templates = client.get("/api/templates")
        template_body = templates.json() if templates.status_code == 200 else {}
        template_ids = [item.get("id") for item in template_body.get("templates", [])]
        check(
            "templates expose exactly the five provisional workflows",
            templates.status_code == 200
            and template_ids == ["t2v", "i2v", "loras", "edit", "smoke"],
            templates.text,
        )
        smoke_schema = client.get("/api/templates/smoke/schema")
        smoke_body = smoke_schema.json() if smoke_schema.status_code == 200 else {}
        smoke_params = smoke_body.get("params", [])
        check(
            "smoke schema has one optional string seed",
            smoke_schema.status_code == 200
            and len(smoke_params) == 1
            and smoke_params[0].get("name") == "seed"
            and smoke_params[0].get("type") == "string"
            and smoke_params[0].get("default") is None,
            smoke_schema.text,
        )
        check(
            "unknown template schema is 404",
            client.get("/api/templates/unknown/schema").status_code == 404,
        )

        unknown_template = client.post(
            "/api/jobs",
            json={"template_id": "unknown", "params": {}},
            headers=csrf_headers(client),
        )
        check(
            "unknown job template is 400 JSON",
            unknown_template.status_code == 400
            and unknown_template.headers.get("content-type", "").startswith("application/json"),
            f"got {unknown_template.status_code} {unknown_template.text}",
        )
        invalid_params = client.post(
            "/api/jobs",
            json={"template_id": "smoke", "params": {"seed": {"bad": True}}},
            headers=csrf_headers(client),
        )
        unsafe_image = client.post(
            "/api/jobs",
            json={"template_id": "i2v", "params": {"image": "/etc/passwd"}},
            headers=csrf_headers(client),
        )
        check(
            "job parameter type and image ownership validation return 422 JSON",
            invalid_params.status_code == 422
            and invalid_params.headers.get("content-type", "").startswith("application/json")
            and unsafe_image.status_code == 422
            and unsafe_image.headers.get("content-type", "").startswith("application/json"),
            f"type {invalid_params.status_code} {invalid_params.text}; image {unsafe_image.status_code} {unsafe_image.text}",
        )
        queued = client.post(
            "/api/jobs",
            json={"template_id": "smoke", "params": {"seed": "queued"}},
            headers=csrf_headers(client),
        )
        queued_body = queued.json() if queued.status_code == 201 else {}
        queued_id = str(queued_body.get("job_id", ""))
        check(
            "smoke job is created with 201 and job_id",
            queued.status_code == 201 and bool(queued_id),
            f"got {queued.status_code} {queued.text}",
        )
        listed = client.get("/api/jobs")
        listed_body = listed.json() if listed.status_code == 200 else {}
        check(
            "newest queued smoke job appears in the owner list",
            listed.status_code == 200
            and listed_body.get("jobs", [{}])[0].get("job_id") == queued_id
            and listed_body["jobs"][0].get("status") == "queued",
            listed.text,
        )
        detail = client.get(f"/api/jobs/{queued_id}")
        detail_body = detail.json() if detail.status_code == 200 else {}
        check(
            "job detail exposes status, params, timestamps, progress, and gallery",
            detail.status_code == 200
            and detail_body.get("status") == "queued"
            and detail_body.get("params") == {"seed": "queued"}
            and detail_body.get("created_at")
            and "progress" in detail_body
            and detail_body.get("gallery") == [],
            detail.text,
        )
        cancel_without_csrf = client.post(f"/api/jobs/{queued_id}/cancel")
        cancelled = client.post(
            f"/api/jobs/{queued_id}/cancel",
            headers=csrf_headers(client),
        )
        check(
            "queued job cancellation requires CSRF and succeeds",
            cancel_without_csrf.status_code == 403
            and cancelled.status_code == 200
            and cancelled.json().get("status") == "cancelled",
            f"without CSRF {cancel_without_csrf.status_code}; with CSRF {cancelled.status_code} {cancelled.text}",
        )
        after_cancel = client.get(f"/api/jobs/{queued_id}")
        check(
            "cancelled status is persisted",
            after_cancel.status_code == 200 and after_cancel.json().get("status") == "cancelled",
            after_cancel.text,
        )
        running = client.post(
            "/api/jobs",
            json={"template_id": "smoke", "params": {"seed": "running"}},
            headers=csrf_headers(client),
        )
        running_body = running.json() if running.status_code == 201 else {}
        running_id = str(running_body.get("job_id", ""))
        check(
            "running-cancel fixture job is created",
            running.status_code == 201 and bool(running_id),
            f"got {running.status_code} {running.text}",
        )
        client.portal.call(mark_running, running_id)
        running_cancel = client.post(
            f"/api/jobs/{running_id}/cancel",
            headers=csrf_headers(client),
        )
        running_cancel_body = running_cancel.json() if running_cancel.status_code == 200 else {}
        check(
            "running cancellation sets the worker flag without claiming completion",
            running_cancel.status_code == 200
            and running_cancel_body.get("status") == "running"
            and running_cancel_body.get("cancel_requested") is True,
            f"got {running_cancel.status_code} {running_cancel.text}",
        )
        running_detail = client.get(f"/api/jobs/{running_id}")
        check(
            "running job detail exposes the semantic cancel flag",
            running_detail.status_code == 200
            and running_detail.json().get("cancel_requested") is True,
            running_detail.text,
        )

        check(
            "logout without X-CSRF is 403",
            client.post("/api/auth/logout").status_code == 403,
        )
        out = client.post("/api/auth/logout", headers=csrf_headers(client))
        check("logout with X-CSRF succeeds", out.status_code == 204, f"got {out.status_code}")
        check("logout invalidates the session", client.get("/api/auth/me").status_code == 401)
        check("protected route is 401 after logout", client.get("/api/jobs").status_code == 401)

        login(client, "user@test")
        me_user = client.get("/api/auth/me")
        user_body = me_user.json() if me_user.status_code == 200 else {}
        check(
            "explicit non-admin identity is not an admin",
            me_user.status_code == 200
            and user_body.get("email") == "user@test"
            and user_body.get("is_admin") is False,
            me_user.text,
        )
        user_smoke = client.get("/api/templates/smoke/schema")
        check(
            "admin and user receive the identical smoke schema",
            user_smoke.status_code == 200 and user_smoke.json() == smoke_body,
            user_smoke.text,
        )

        bad_upload = client.post(
            "/api/uploads/pre",
            files={"file": ("notes.txt", b"not allowed", "text/plain")},
            headers=csrf_headers(client),
        )
        check(
            "upload rejects a disallowed MIME type with 415",
            bad_upload.status_code == 415
            and bad_upload.headers.get("content-type", "").startswith("application/json"),
            f"got {bad_upload.status_code} {bad_upload.text}",
        )
        uploaded = client.post(
            "/api/uploads/pre",
            files={"file": ("../../frame.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            headers=csrf_headers(client),
        )
        uploaded_body = uploaded.json() if uploaded.status_code == 200 else {}
        uploaded_path = Path(str(uploaded_body.get("path", "")))
        check(
            "valid upload is stored under a sanitized owner path",
            uploaded.status_code == 200
            and uploaded_path.name.startswith("frame.png") is False
            and ".." not in uploaded_path.as_posix()
            and uploaded_path.is_file(),
            f"got {uploaded.status_code} {uploaded.text}",
        )
        user_id = int(uploaded_path.parent.name) if uploaded_path.parent.name.isdigit() else -1
        upload_files = client.get(f"/api/uploads/{user_id}/files")
        check(
            "owner lists stored upload files",
            upload_files.status_code == 200
            and any(item.get("name") == uploaded_path.name for item in upload_files.json().get("files", [])),
            upload_files.text,
        )

        admin_item = client.portal.call(seed_gallery_item, "admin@test", "admin-item")
        admin_user_id = int(admin_item["user_id"])
        check(
            "non-admin cannot list another user's uploads",
            client.get(f"/api/uploads/{admin_user_id}/files").status_code == 403,
        )
        user_job = client.post(
            "/api/jobs",
            json={"template_id": "smoke", "params": {"seed": "isolation"}},
            headers=csrf_headers(client),
        )
        user_job_body = user_job.json() if user_job.status_code == 201 else {}
        user_job_id = str(user_job_body.get("job_id", ""))
        check(
            "non-admin creates an owned job for isolation checks",
            user_job.status_code == 201 and bool(user_job_id),
            f"got {user_job.status_code} {user_job.text}",
        )
        check(
            "non-admin raw job view is 403",
            client.get(f"/api/admin/jobs/{user_job_id}/raw").status_code == 403,
        )

        owner_item = client.portal.call(seed_gallery_item, "user@test", "owner-item")
        moderation_item = client.portal.call(seed_gallery_item, "user@test", "moderation-item")
        owner_media_id = int(owner_item["media_id"])
        admin_media_id = int(admin_item["media_id"])
        gallery = client.get("/api/gallery")
        gallery_ids = {
            item.get("id") for item in gallery.json().get("items", []) if gallery.status_code == 200
        }
        check(
            "gallery listing is owner-only",
            gallery.status_code == 200
            and owner_item["media_id"] in gallery_ids
            and moderation_item["media_id"] in gallery_ids
            and admin_media_id not in gallery_ids,
            gallery.text,
        )
        own_file = client.get(f"/api/gallery/{owner_media_id}/file")
        check(
            "owner downloads gallery media",
            own_file.status_code == 200 and own_file.content == b"fixture-owner-item",
            f"got {own_file.status_code}",
        )
        check(
            "non-owner gallery file access is 403",
            client.get(f"/api/gallery/{admin_media_id}/file").status_code == 403,
        )
        metadata = client.get(f"/api/gallery/{owner_media_id}/metadata")
        metadata_body = metadata.json() if metadata.status_code == 200 else {}
        check(
            "gallery metadata is available to its owner",
            metadata.status_code == 200
            and metadata_body.get("id") == owner_media_id
            and metadata_body.get("sha256"),
            metadata.text,
        )
        delete_without_csrf = client.delete(f"/api/gallery/{owner_media_id}")
        owner_delete = client.delete(
            f"/api/gallery/{owner_media_id}",
            headers=csrf_headers(client),
        )
        check(
            "owner gallery deletion requires CSRF and succeeds",
            delete_without_csrf.status_code == 403
            and owner_delete.status_code == 200
            and owner_delete.json().get("deleted") is True,
            f"without CSRF {delete_without_csrf.status_code}; with CSRF {owner_delete.status_code} {owner_delete.text}",
        )
        check(
            "deleted gallery file is 404",
            client.get(f"/api/gallery/{owner_media_id}/file").status_code == 404,
        )

        login(client, "admin@test", "media-admins")
        system = client.get("/api/admin/system")
        system_body = system.json() if system.status_code == 200 else {}
        check(
            "admin system view exposes versions, queue, worker, and storage",
            system.status_code == 200
            and set(system_body.get("versions", {})) == {"app", "uvicorn", "fastapi"}
            and "queue_depth" in system_body
            and "worker" in system_body
            and "storage" in system_body,
            system.text,
        )
        users = client.get("/api/admin/users")
        check(
            "admin user list includes both documented identities",
            users.status_code == 200
            and {"admin@test", "user@test"}.issubset(
                {item.get("email") for item in users.json().get("users", [])}
            ),
            users.text,
        )
        raw = client.get(f"/api/admin/jobs/{user_job_id}/raw")
        check(
            "admin raw job view is 200",
            raw.status_code == 200
            and raw.json().get("job_id") == user_job_id
            and raw.json().get("workflow") == {"seed": "isolation"},
            raw.text,
        )
        admin_uploads = client.get(f"/api/uploads/{user_id}/files")
        check(
            "admin lists another user's upload files",
            admin_uploads.status_code == 200
            and any(item.get("name") == uploaded_path.name for item in admin_uploads.json().get("files", [])),
            admin_uploads.text,
        )
        moderation_media_id = int(moderation_item["media_id"])
        admin_gallery = client.get("/api/gallery", params={"user": user_id})
        check(
            "admin filters gallery by user",
            admin_gallery.status_code == 200
            and moderation_media_id
            in {item.get("id") for item in admin_gallery.json().get("items", [])},
            admin_gallery.text,
        )
        moderated = client.post(
            f"/api/admin/gallery/{moderation_media_id}/delete",
            headers=csrf_headers(client),
        )
        check(
            "admin moderation delete succeeds with CSRF",
            moderated.status_code == 200 and moderated.json().get("deleted") is True,
            f"got {moderated.status_code} {moderated.text}",
        )
        check(
            "moderated gallery file is 404",
            client.get(f"/api/gallery/{moderation_media_id}/file").status_code == 404,
        )

    failed = [name for ok, name, _ in results if not ok]
    if len(results) != EXPECTED_CHECKS:
        print(f"FAIL: expected {EXPECTED_CHECKS} checks, observed {len(results)}")
        failed.append("check count")
    print(f"controlplane_unit: {len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("controlplane_unit: FAILED -> " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
