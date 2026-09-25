#!/usr/bin/env bash
# Phase 2 workflow/schema validation (Task 2.7). Structure checks run always and
# must PASS; class membership against ComfyUI /object_info runs only when a real
# backend is reachable (final consolidated pass / pinned backend); otherwise the
# class check is SKIPPED with a warning and exit 0.
#
# Checks:
#   - every template in config/templates.schema.json points at an existing,
#     valid, API-format workflow JSON (no UI-format keys)
#   - bind "<node>.<widget>" targets an existing node/widget in the workflow
#   - {PARAM.x} markers reference a declared template param (width/height are
#     derived from enums and are exempt)
#   - node references [n, slot] point at existing node ids
#   - when COMFY_OBJECT_INFO is set+reachable: every class_type exists there
#
# Usage: bash tests/workflow_schema.sh    (from system/)
#   COMFY_OBJECT_INFO=http://127.0.0.1:8999/object_info   optional class check
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

out="$(SYSTEM_ROOT="${ROOT}" python3 - "${ROOT}" <<'PY'
import json, os, re, sys
from pathlib import Path

root = Path(sys.argv[1])
schema = json.loads((root / "config" / "templates.schema.json").read_text())
if len(schema["templates"]) != 5:
    sys.exit(f"expected 5 templates, got {len(schema['templates'])}")
template_ids = list(schema["templates"])
errors = []
for tid, tpl in schema["templates"].items():
    wf_path = root / "workflows" / tpl["workflow"]
    if not wf_path.is_file():
        errors.append(f"{tid}: workflow file missing: {tpl['workflow']}")
        continue
    graph = json.loads(wf_path.read_text())
    if not isinstance(graph, dict) or not graph:
        errors.append(f"{tid}: workflow is not a non-empty object")
        continue
    ui_keys = [k for k in ("nodes", "links", "last_node_id", "version") if k in graph]
    if ui_keys:
        errors.append(f"{tid}: UI-format keys present: {ui_keys}")
        continue
    node_ids = set(graph)
    for nid, node in graph.items():
        if not isinstance(node, dict) or "class_type" not in node or not isinstance(node.get("inputs"), dict):
            errors.append(f"{tid}: node {nid} lacks class_type/inputs")
            continue
        for port in node["inputs"].values():
            if isinstance(port, list) and len(port) == 2 and str(port[0]) not in node_ids:
                errors.append(f"{tid}: node {nid} references missing node {port[0]}")
    declared = set(tpl.get("params", {}))
    for nid, node in graph.items():
        for widget in node.get("inputs", {}).values():
            if not isinstance(widget, str):
                continue
            m = re.fullmatch(r"\{PARAM\.([A-Za-z0-9_]+)\}", widget.strip())
            if m and m.group(1) not in declared and m.group(1) not in ("width", "height"):
                errors.append(f"{tid}: marker {{{ 'PARAM.' + m.group(1)}}} is not declared in params")
    for pname, p in tpl.get("params", {}).items():
        if "bind" not in p:
            continue
        node_id, widget = p["bind"].split(".", 1)
        node = graph.get(node_id)
        if node is None or widget not in node.get("inputs", {}):
            errors.append(f"{tid}: bind {p['bind']} missing node/widget in workflow")

print("templates=" + ",".join(template_ids))
if errors:
    print("ERRORS")
    for e in errors:
        print(e)
    sys.exit(1)
print("structure OK")
PY
)"

if [[ "${out}" == *"structure OK"* && -z "${out##*templates=*}" ]]; then
  echo "workflow_schema: ${out}"
else
  echo "workflow_schema: FAIL"
  printf '%s\n' "${out}" >&2
  exit 1
fi

# Optional class membership (final pass / pinned backend only).
if [[ -n "${COMFY_OBJECT_INFO:-}" ]]; then
  classes="$({ command -v curl >/dev/null 2>&1 && curl -fsS --max-time 5 "${COMFY_OBJECT_INFO}"; } 2>/dev/null || true)"
  if [[ -z "${classes}" ]]; then
    echo "workflow_schema: SKIP class check (${COMFY_OBJECT_INFO} unreachable)"
    exit 0
  fi
  missing="$(COMFY_CLASSES="${classes}" python3 - "${ROOT}" <<'PY'
import json, os, re, sys
from pathlib import Path
classes = set(json.loads(os.environ["COMFY_CLASSES"]))
root = Path(sys.argv[1])
schema = json.loads((root / "config" / "templates.schema.json").read_text())
node_classes = set()
for tpl in schema["templates"].values():
    graph = json.loads((root / "workflows" / tpl["workflow"]).read_text())
    node_classes.update(n["class_type"] for n in graph.values())
print("\n".join(sorted(node_classes - classes)))
PY
)"
  if [[ -n "${missing}" ]]; then
    echo "workflow_schema: FAIL class membership in /object_info:"
    printf '%s\n' "${missing}" >&2
    exit 1
  fi
  echo "workflow_schema: class membership in /object_info OK"
else
  echo "workflow_schema: SKIP class check (COMFY_OBJECT_INFO unset; runs in the final pass)"
fi
exit 0