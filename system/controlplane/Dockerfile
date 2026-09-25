# Syntax: docker/dockerfile:1.7
# Control-plane image: Nuxt SPA (SSG) baked into a FastAPI runtime.

# --- Stage 1: build the SPA static output ---
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS spa-build
WORKDIR /app/spa
COPY spa/package.json spa/package-lock.json ./
RUN npm ci
COPY spa/ ./
RUN npm run build
# Nitro publicDir 'dist' -> static index.html + hash-busted /_nuxt bundle.
RUN test -f dist/index.html

# --- Stage 2: Python runtime ---
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS runtime
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 --gid 100 control
COPY controlplane/requirements.txt /opt/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /opt/requirements.txt
WORKDIR /opt/media
COPY --from=spa-build /app/spa/dist /opt/media/spa
COPY controlplane/app/ /opt/media/app/
# Phase 2 canonical graphs + keyed template schema (read-only mounts override
# these when compose runs; the baked copies keep the bare image self-sufficient).
COPY workflows/ /opt/media/workflows/
COPY config/ /opt/media/config/
RUN chown -R 1000:100 /opt/media
USER 1000:100
EXPOSE 8000
ENV CONTROLPLANE_LISTEN=0.0.0.0 CONTROLPLANE_PORT=8000 SPA_STATIC=/opt/media/spa \
    WORKFLOWS_DIR=/opt/media/workflows TEMPLATE_SCHEMA=/opt/media/config/templates.schema.json
CMD ["sh", "-c", "cd /opt/media && uvicorn app.main:app --host ${CONTROLPLANE_LISTEN} --port ${CONTROLPLANE_PORT}"]
