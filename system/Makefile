# Control-plane + SPA + native-stack test entry points.
#
# make e2e    P1.5: OIDC e2e through the native nginx+SPA stack (12 groups).
#             Requires the native stack running (control-plane, worker, mock
#             ComfyUI on :8999, Postgres, nginx on :8443) with OIDC_MOCK=1.
# make unit   In-process API + worker checks over sqlite (no services needed).

.PHONY: unit e2e

unit:
	bash tests/controlplane_unit.sh

e2e:
	DOMAIN=media.local HTTPS_PORT=8443 OIDC_MOCK=1 bash tests/e2e_spa.sh