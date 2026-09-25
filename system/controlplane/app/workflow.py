"""Resolve a job into a ComfyUI API-format workflow graph.

The canonical graphs live under system/workflows/ (phase 2, API format) with
`{PARAM.<name>}` markers. The worker injects validated user params into those
markers. Params not supplied by the caller fall back to the template default;
`{PARAM.width}/{PARAM.height}` are derived from an enum whose selected value is
a width/height tuple (`resolution`) or a `resolutions` megapixel table when the
user did not supply width/height directly. `{PARAM.image}` is replaced by the
filename of a copy of the owned upload staged into ComfyUI's shared input dir.
"""

from __future__ import annotations

import json
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .settings import get_settings

MARKER = re.compile(r"^\{PARAM\.([A-Za-z0-9_]+)\}$")


@lru_cache(maxsize=1)
def template_schema() -> dict[str, Any]:
    with Path(get_settings().template_schema_path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("templates"), dict):
        raise RuntimeError("invalid templates schema")
    return value


def template_spec(template_id: str) -> dict[str, Any]:
    try:
        template = template_schema()["templates"][template_id]
    except KeyError as exc:
        raise ValueError(f"no template {template_id!r} in the schema") from exc
    return {"id": template_id, **template}


def template_graph(template_id: str) -> dict[str, Any]:
    spec = template_spec(template_id)
    filename = spec.get("workflow")
    if not filename:
        raise ValueError(f"template {template_id!r} has no workflow file")
    with Path(get_settings().workflows_dir, filename).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"workflow {filename!r} is not a JSON object")
    return value


def build_workflow(template_id: str, params: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Return the graph with `{PARAM.<name>}` markers resolved from params.

    Schema defaults are merged underneath the supplied values so a caller may
    submit only the params it wants to change.
    """
    spec = template_spec(template_id)
    parameters = spec.get("params", {})
    resolved: dict[str, Any] = {
        name: parameter.get("default")
        for name, parameter in parameters.items()
        if "default" in parameter
    }
    resolved.update(params or {})

    def _resolve(value: Any) -> Any:
        if isinstance(value, str):
            match = MARKER.match(value.strip())
            return _marker_value(match.group(1), resolved, spec) if match else value
        if isinstance(value, dict):
            return {key: _resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_resolve(item) for item in value]
        return value

    return {node_id: _resolve(node) for node_id, node in graph.items()}


def _marker_value(name: str, resolved: dict[str, Any], spec: dict[str, Any]) -> Any:
    parameters = spec.get("params", {})
    parameter = parameters.get(name, {})
    if name in resolved:
        value = resolved[name]
        if parameter.get("type") == "image":
            value = stage_image(value)
        return _as_widget_value(value)
    if name in ("width", "height"):
        dimensions = _derive_dimensions(resolved, parameters)
        if dimensions is not None:
            return dimensions[0] if name == "width" else dimensions[1]
        raise ValueError(f"cannot derive {name}: supply the param or a resolution enum")
    if "default" in parameter:
        default = parameter["default"]
        if parameter.get("type") == "image" and default:
            default = stage_image(default)
        return _as_widget_value(default)
    raise ValueError(f"required param {name!r} is not set and has no default")


def _as_widget_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return json.loads(json.dumps(value))


def _derive_dimensions(resolved: dict[str, Any], template_params: dict[str, Any]) -> tuple[int, int] | None:
    for name, parameter in template_params.items():
        if parameter.get("type") != "enum":
            continue
        selected = resolved.get(name)
        if selected is None:
            continue
        table = parameter.get("resolutions")
        if isinstance(table, dict):
            entry = table.get(str(selected))
            if _is_dimension_pair(entry):
                return int(entry[0]), int(entry[1])
        if _is_dimension_pair(selected):
            return int(selected[0]), int(selected[1])
    return None


def _is_dimension_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    )


def stage_image(reference: str) -> str:
    """Copy an upload URL reference into ComfyUI's shared input dir; return its filename.

    Ownership and existence were validated at job submission time; this resolves
    the URL back to the stored file and stages a flat, user-prefixed copy under
    COMFY_INPUT_DIR so ComfyUI can LoadImage it by filename.
    """
    upload_root = Path(get_settings().upload_root).resolve()
    parsed = urlparse(reference)
    match = re.match(r"^/api/uploads/([0-9]+)/([^/]+)$", parsed.path or "")
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or match is None:
        raise ValueError(f"image parameter is not an upload reference: {reference!r}")
    owner_id, filename = match.group(1), unquote(match.group(2))
    source = (upload_root / owner_id / filename).resolve()
    if not source.is_relative_to(upload_root) or not source.is_file():
        raise ValueError("image upload no longer exists on disk")
    input_dir = Path(get_settings().comfy_input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    destination = input_dir / f"{owner_id}-{source.name}"
    shutil.copyfile(source, destination)
    return destination.name