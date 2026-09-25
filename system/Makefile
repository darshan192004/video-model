SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
.PHONY: help doctor build dev-up gpu-up down smoke k3s-apply clean

COMPOSE_BASE := deploy/compose/base.yml

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

doctor: ## Run preflight checks
	scripts/doctor.sh

build: ## Build the ComfyUI + control-plane images
	docker build -t comfyui-media:0.1.0 ./comfyui
	docker build -t controlplane-media:0.1.0 -f controlplane/Dockerfile .

dev-up: ## Start CPU-mode stack (dev box, smoke only)
	COMFY_MODE=cpu docker compose -f $(COMPOSE_BASE) -f deploy/compose/compose.override.cpu.yml up -d --build

gpu-up: ## Start GPU-mode stack (RTX 3090)
	docker compose -f $(COMPOSE_BASE) -f deploy/compose/compose.override.gpu.yml up -d --build

down: ## Stop compose stack
	docker compose -f $(COMPOSE_BASE) down

smoke: ## Run the API roundtrip smoke test
	bash tests/smoke.sh

k3s-apply: ## Apply k8s manifests (overlay k3s)
	kubectl apply -k deploy/k8s/overlays/k3s

clean: ## Remove built image and test artifacts
	docker rm -f liveness-test-* 2>/dev/null || true
	docker image rm comfyui-media:0.1.0 2>/dev/null || true
