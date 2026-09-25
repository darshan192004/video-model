from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("media.settings")

OIDC_PROD_VARS = (
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_redirect_uri",
    "session_secret",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    controlplane_listen: str = "0.0.0.0"
    controlplane_port: int = 8000

    dex_oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    session_secret: str = ""
    oidc_mock: bool = False
    # Kept as the raw comma-separated string: pydantic-settings JSON-decodes
    # complex env values, which rejects a bare "media-admins" list literal.
    admin_groups: str = ""
    default_admin_groups: str = "media-admins"

    comfy_internal_url: str = "http://comfyui:8188"
    database_url: str = "postgresql+psycopg://media:media@postgres:5432/media"
    gallery_root: str = "/data/galleries"
    upload_root: str = "/data/uploads"
    auto_migrate: bool = True
    spa_static: str = "/opt/media/spa"

    # Where the worker reads ComfyUI's scratch output volume. In compose this is
    # the shared `comfy-output` named volume; on a native dev box it points at
    # the mock/real backend's output directory.
    comfy_output_dir: str = "/data/comfy-output"
    # Where the worker stages `{PARAM.image}` uploads for ComfyUI to LoadImage.
    # In compose this is the shared `comfy-input` volume mounted at ComfyUI's
    # input directory.
    comfy_input_dir: str = "/data/comfy-input"
    # Canonical phase-2 graphs (system/workflows/) and the keyed template schema
    # (system/config/templates.schema.json). In compose these are read-only
    # mounts; on a native checkout the repo-relative defaults are used.
    workflows_dir: str = str(Path(__file__).resolve().parents[2] / "workflows")
    template_schema_path: str = str(Path(__file__).resolve().parents[2] / "config" / "templates.schema.json")
    # Test/dev-only: directory of extra isolated template fixtures (registered
    # alongside the keyed schema). Unset in production.
    template_fixtures_dir: str = ""
    worker_poll_seconds: float = 2.0
    worker_job_timeout_seconds: float = 3600.0
    worker_log_level: str = "INFO"

    SESSION_TTL_SECONDS: ClassVar[int] = 12 * 60 * 60
    AUTHZ_TTL_SECONDS: ClassVar[int] = 10 * 60
    SID_COOKIE: ClassVar[str] = "media_sid"
    CSRF_COOKIE: ClassVar[str] = "media_csrf"
    CSRF_HEADER: ClassVar[str] = "X-CSRF"
    SID_SALT: ClassVar[str] = "media-sid"
    IDENTITY_SALT: ClassVar[str] = "media-identity"

    @property
    def admin_group_names(self) -> set[str]:
        raw = self.admin_groups.strip()
        names = {item.strip() for item in raw.split(",") if item.strip()} if raw else set()
        if not names and self.default_admin_groups.strip():
            names = {self.default_admin_groups.strip()}
        return names

    @model_validator(mode="after")
    def _require_oidc_prod_config(self) -> Settings:
        if self.oidc_mock:
            return self
        missing = [name for name in OIDC_PROD_VARS if not getattr(self, name).strip()]
        if missing:
            env_names = ", ".join(name.upper() for name in missing)
            raise ValueError(
                f"OIDC_MOCK=0 requires {env_names} in the environment; "
                "set them or run with OIDC_MOCK=1 for tests"
            )
        if not self.dex_oidc_issuer.strip():
            log.warning("DEX_OIDC_ISSUER is empty: OIDC discovery will fail at login time")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
