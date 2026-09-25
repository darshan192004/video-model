# Control-plane + SPA + native-stack test entry points.
#
# make e2e    P1.5: OIDC e2e through the native nginx+SPA stack (12 groups).
#             Requires the native stack running (control-plane, worker, mock
#             ComfyUI on :8999, Postgres, nginx on :8443) with OIDC_MOCK=1.
# make smoke  P3: control-plane smoke (login, FIFO, cancel, failure,
#             isolation). Requires the same stack, with real test Dex OIDC.
# make unit   In-process API + worker checks over sqlite (no services needed).
# make k8s-smoke       P5.4: in-cluster roundtrip (k3s overlay NodePort 30443).
# make k3s-regression  P5.5: every prior suite re-run against the k3s overlay.

.PHONY: unit e2e smoke k8s-smoke k3s-regression

unit:
	bash tests/controlplane_unit.sh

e2e:
	DOMAIN=media.local HTTPS_PORT=8443 OIDC_MOCK=1 bash tests/e2e_spa.sh

smoke: ## Control-plane smoke (OIDC, FIFO, cancel, failure, isolation)
	bash tests/smoke.sh

k8s-smoke: ## In-cluster control-plane roundtrip (k3s overlay)
	bash tests/k8s-smoke.sh

k3s-regression: ## Full in-cluster regression (all prior suites)
	bash tests/k3s-regression.sh