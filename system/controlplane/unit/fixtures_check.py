"""Phase-3 check: the TEMPLATE_FIXTURES_DIR registry hook.

A full unit run (controlplane_unit.sh -> run.py) boots the API with NO
fixture dir and asserts exactly the five keyed templates. This process boots
WITH the fixtures dir and asserts the deliberate broken fixture is registered,
resolves through the graph/builder, hides its internals from the API payload,
and never shadows an unknown template.

Run from system/controlplane:
  TEMPLATE_FIXTURES_DIR=... PYTHONPATH=. .venv/bin/python -m unit.fixtures_check
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["TEMPLATE_FIXTURES_DIR"] = str(
    Path(__file__).resolve().parents[2] / "tests" / "workflows"
)
os.environ["OIDC_MOCK"] = "1"

from fastapi import HTTPException  # noqa: E402

from app.routers.templates import get_template  # noqa: E402
from app.workflow import build_workflow, template_definitions, template_graph, template_spec  # noqa: E402

failed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   - {label}")
    else:
        failed.append(label)
        print(f"  FAIL - {label}: {detail}")


def main() -> int:
    defs = template_definitions()
    check(
        "fixture 'broken' joins the five keyed templates",
        all(template_id in defs for template_id in ("qwen-t2i", "qwen-edit", "wan-t2v", "wan-i2v", "smoke", "broken")),
        f"ids={sorted(defs)}",
    )
    spec = template_spec("broken")
    check("fixture spec carries params + display", spec.get("params") == {} and bool(spec.get("display")))
    graph = template_graph("broken")
    check(
        "fixture graph references the deliberate unknown node",
        graph.get("1", {}).get("class_type") == "NotFound_BrokenTestNode_v0",
        str(graph),
    )
    built = build_workflow("broken", {}, graph)
    check(
        "build_workflow runs over the fixture graph",
        built["1"]["class_type"] == "NotFound_BrokenTestNode_v0"
        and built["9"]["inputs"]["filename_prefix"] == "broken-fixture",
        str(built),
    )
    payload = get_template("broken")
    check(
        "template router serves the fixture publicly",
        payload["id"] == "broken" and payload["display"],
        str(payload),
    )
    check(
        "router payload strips fixture internals",
        "graph" not in payload and "_fixture" not in payload,
        str(payload),
    )
    try:
        get_template("definitely-not-a-template")
        check("unknown template still 404s in fixture mode", False)
    except HTTPException as exc:
        check("unknown template still 404s in fixture mode", exc.status_code == 404)

    if failed:
        print(f"fixtures_check: {len(failed)} FAILED")
        return 1
    print("fixtures_check: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())