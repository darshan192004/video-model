"""Resolve a job into a ComfyUI workflow graph.

The committed graphs under config/workflows.json are provisional stand-ins;
Phase 2 authors the real Wan/Qwen workflows against ComfyUI /object_info. The
placeholder syntax `{{ name }}` lets the worker inject validated user params
into node inputs without Phase 2 depending on this module.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

WORKFLOWS_PATH = Path(__file__).resolve().parents[2] / "config" / "workflows.json"
PLACEHOLDER = re.compile(r"^\{\{\s*([A-Za-z0-9_]+)\s*\}\}$")


@lru_cache(maxsize=1)
def workflow_graphs() -> dict[str, Any]:
    with WORKFLOWS_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError("invalid workflows.json")
    return value


def template_graph(template_id: str) -> dict[str, Any]:
    try:
        graph = workflow_graphs()[template_id]
    except KeyError as exc:
        raise ValueError(f"no workflow graph for template {template_id}") from exc
    return _clone(graph)


def build_workflow(template_id: str, params: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Return the graph with `{{ param }}` placeholders resolved from params."""
    resolved = dict(params or {})
    # Plan/Makefile normalizer: a LoRA workflow receives `lo ras` keys in some
    # deployments; unify them before injection.
    if template_id == "loras":
        resolved = {("loras" if key == "lo ras" else key): value for key, value in resolved.items()}

    def _resolve(value: Any) -> Any:
        if isinstance(value, str):
            match = PLACEHOLDER.match(value.strip())
            if match and match.group(1) in resolved:
                return resolved[match.group(1)]
            return value
        if isinstance(value, dict):
            return {key: _resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_resolve(item) for item in value]
        return value

    return {node_id: _resolve(node) for node_id, node in graph.items()}


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))