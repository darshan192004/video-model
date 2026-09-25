"""Minimal HTTP client for the internal ComfyUI backend.

Used by the FIFO worker. Progress/terminal detection is poll-based over
/history (robust against both the real backend and the mock); a real-WebSocket
ticker is deferred to the GPU phases (P3/P4) where the ComfyUI frontend runs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("media.comfy")


class ComfyError(RuntimeError):
    """The ComfyUI backend rejected or failed a prompt."""


class ComfyClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # transport injection keeps worker logic testable against an in-process
        # ASGI mock, with no sockets involved.
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"base_url": self.base_url, "timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def post_prompt(self, workflow: dict[str, Any], client_id: str) -> str:
        payload = {"prompt": workflow, "client_id": client_id}
        async with self._client() as client:
            response = await client.post("/prompt", json=payload)
        if response.status_code != 200:
            raise ComfyError(f"comfy /prompt returned HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ComfyError("comfy /prompt omitted prompt_id")
        return str(prompt_id)

    async def history(self, prompt_id: str) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get(f"/history/{prompt_id}")
        if response.status_code not in (200, 202):
            raise ComfyError(f"comfy /history returned HTTP {response.status_code}")
        value = response.json()
        return value if isinstance(value, dict) else {}

    async def interrupt(self) -> None:
        async with self._client() as client:
            response = await client.post("/interrupt")
        if response.status_code not in (200, 202, 204):
            log.warning("comfy /interrupt returned HTTP %s", response.status_code)