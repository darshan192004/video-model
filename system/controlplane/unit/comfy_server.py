"""Native-stack MockComfy HTTP server for the P1.5 e2e suite.

The unit suite drives MockComfy in-process via httpx.ASGITransport; the final
P1.5 runtime pass instead points the control-plane worker at a real socket, so
this wrapper exposes the same fixture over uvicorn on 127.0.0.1:8999.

Env:
    COMFY_OUTPUT_DIR      scratch dir the worker reads back (default /tmp/comfy-output)
    COMFY_MOCK_PORT       bind port (default 8999)
    COMFY_MOCK_FAIL_SUBSTR  when set, /prompt rejects any graph containing it
                            (e2e "broken workflow" fixture)
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from unit.comfy_mock import MockComfy


def build_app() -> MockComfy:
    output = Path(os.environ.get("COMFY_OUTPUT_DIR", "/tmp/comfy-output"))
    mock = MockComfy(output)
    fail_substr = os.environ.get("COMFY_MOCK_FAIL_SUBSTR", "")
    mock.fail_substr = fail_substr or None
    return mock


def main() -> None:
    app = build_app()
    port = int(os.environ.get("COMFY_MOCK_PORT", "8999"))
    host = os.environ.get("COMFY_MOCK_LISTEN", "127.0.0.1")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("COMFY_MOCK_LOG_LEVEL", "warning"),
    )


if __name__ == "__main__":
    main()