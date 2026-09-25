#!/usr/bin/env bash
# Regenerate deploy/k8s/base/configmaps.yaml from the AUTHORITATIVE repo files
# (nginx conf, workflows, templates.schema.json, control-plane env contract).
#
# Kustomize's loader refuses `configMapGenerator files:` targets outside the
# kustomization root, so the base carries generated-but-committed ConfigMaps
# instead; run this whenever the upstream files change (git diff surfaces drift):
#   bash scripts/k8s-sync-configmaps.sh        # verify (no write; prints to stdout)
#   bash scripts/k8s-sync-configmaps.sh --write
set -euo pipefail

SYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$SYS/deploy/k8s/base/configmaps.yaml"

export SYS
python3 - <<'PY'
import os
from pathlib import Path
import yaml

sys = Path(os.environ["SYS"])
out = Path(os.environ["OUT"]) if os.environ.get("WRITE") == "1" else None
dump = sys.stdout if out is None else out.open("w")

nginx_conf = (sys / "nginx" / "conf.d" / "default.conf").read_text()
nginx_main = (sys / "nginx" / "nginx.conf").read_text()
workflow_files = ["qwen-t2i.json", "qwen-edit.json", "wan-t2v-a14b.json", "wan-i2v-a14b.json", "smoke.json"]
templates_schema = (sys / "config" / "templates.schema.json").read_text()
literals = [
    "CONTROLPLANE_LISTEN=0.0.0.0", "CONTROLPLANE_PORT=8000",
    "COMFY_INTERNAL_URL=http://comfyui:8188",
    "GALLERY_ROOT=/data/galleries", "UPLOAD_ROOT=/data/uploads",
    "COMFY_OUTPUT_DIR=/data/comfy-output", "COMFY_INPUT_DIR=/data/comfy-input",
    "WORKFLOWS_DIR=/opt/media/workflows",
    "TEMPLATE_SCHEMA=/opt/media/config/templates.schema.json",
    "ADMIN_GROUPS=media-admins", "DEFAULT_ADMIN_GROUPS=media-admins",
    "AUTO_MIGRATE=1", "OIDC_MOCK=0", "OIDC_CLIENT_ID=media-controlplane",
    "WORKER_POLL_SECONDS=2", "WORKER_JOB_TIMEOUT_SECONDS=3600",
    "DOMAIN=media.local", "DEX_OIDC_ISSUER=http://host.docker.internal:5556/dex",
    "OIDC_REDIRECT_URI=https://media.local/api/auth/callback",
]

docs = [
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "nginx-conf"},
     "data": {"default.conf": nginx_conf, "nginx.conf": nginx_main}},
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "comfyui-workflows"},
     "data": {wf: (sys / "workflows" / wf).read_text() for wf in workflow_files}},
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "templates-schema"},
     "data": {"templates.schema.json": templates_schema}},
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "controlplane-env"},
     "data": {line.split("=", 1)[0]: line.split("=", 1)[1] for line in literals}},
]
yaml.dump_all(docs, dump, default_flow_style=False, sort_keys=False, allow_unicode=True)
if out is not None:
    dump.close()
PY