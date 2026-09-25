"""In-process ComfyUI stand-in exercising the worker's /prompt -> /history path.

An httpx ASGITransport drives this object directly; no sockets, no spinning up
the real backend with its model deps.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from httpx import ASGITransport


class MockComfy:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.prompt_ids: list[str] = []
        self.interrupts = 0
        self.fail_prompt = False
        self.exec_error: str | None = None
        # When set, any /prompt submission whose raw graph JSON contains this
        # substring is rejected with 500 (simulates ComfyUI rejecting a node
        # graph with an unknown node class). Lets the e2e suite exercise the
        # job->failed path without a real backend or model weights.
        self.fail_substr: str | None = None
        self._last_raw_body = ""

    def transport(self) -> ASGITransport:
        return ASGITransport(app=self)

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            return
        data: dict[str, Any] = {}
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            body = b""
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    break
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            self._last_raw_body = body.decode("utf-8", "replace")
            if body:
                data = json.loads(body)
        status, payload = await self._route(scope["method"], scope["path"], data)
        response_body = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": response_body})

    async def _route(self, method: str, path: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if method == "POST" and path == "/prompt":
            if self.fail_substr and self.fail_substr in self._last_raw_body:
                return 500, {"error": f"mock: unknown node class ({self.fail_substr})"}
            if self.fail_prompt:
                return 500, {"error": "mock prompt rejected"}
            prompt_id = str(uuid.uuid4())
            self.prompt_ids.append(prompt_id)
            run_index = len(self.prompt_ids)
            run_dir = self.output_dir / f"run_{run_index:04d}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "out.png").write_bytes(b"\x89PNG\r\n\x1a\nmock-canvas")
            return 200, {"prompt_id": prompt_id, "number": run_index, "node_errors": {}}
        if method == "GET" and path.startswith("/history/"):
            prompt_id = path.rsplit("/", 1)[-1]
            if self.exec_error is not None:
                return 200, {prompt_id: {"status": {"status_str": "error", "error": self.exec_error}, "outputs": {}}}
            if prompt_id in self.prompt_ids:
                run_index = self.prompt_ids.index(prompt_id) + 1
                entry = {
                    "status": {"status_str": "completed"},
                    "outputs": {
                        "9": {
                            "images": [
                                {"filename": "out.png", "subfolder": f"run_{run_index:04d}", "type": "output"}
                            ]
                        }
                    },
                }
                return 200, {prompt_id: entry}
            return 200, {}
        if method == "POST" and path == "/interrupt":
            self.interrupts += 1
            return 200, {}
        return 404, {"error": "not found"}