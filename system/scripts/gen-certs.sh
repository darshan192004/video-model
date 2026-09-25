#!/usr/bin/env bash
# Generate a self-signed TLS cert (internal use). Idempotent: refuses to
# overwrite existing files unless FORCE=1.
set -euo pipefail

DOMAIN="${DOMAIN:-media.local}"
CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../deploy" && pwd)/certs"
mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/fullchain.pem" && "${FORCE:-0}" != "1" ]]; then
  echo "cert exists; set FORCE=1 to regenerate" >&2
  exit 0
fi

openssl req -x509 -newkey rsa:4096 -sha256 -days 825 -nodes \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/CN=${DOMAIN}" \
  -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1

chmod 600 "$CERT_DIR/privkey.pem" "$CERT_DIR/fullchain.pem"
echo "cert written: $CERT_DIR (fullchain.pem, privkey.pem)"
