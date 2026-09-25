# Syntax: docker/dockerfile:1.7
# Pinned, non-root ComfyUI server image used by both compose and k8s.

# Python 3.12 CUDA base. Tag + digest pinned for reproducibility (digest of
# nvidia/cuda:12.4.1-runtime-ubuntu22.04 as resolved via docker.io, matching the
# unpinned default resolution).
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04@sha256:517da2300c184c9999ec203c2665244bdebd3578d12fcc7065e83667932643d9 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# --- Versions (reproducibility contract) --------------------------------
# COMIFYUI *backend* revision: must include native Qwen-Image-2.1 support
#   (merged in Comfy-Org/ComfyUI#16400; backend >= 0.37.0).
# RELEASE_PIN is a full 40-char commit SHA on a released tag's lineage.
ENV COMFYUI_BACKEND_REV=73c9bad4d21e7addbe1d13bc92eee0f1431b017d
# COMfyUI *frontend*: pinned for reproducibility only (the SPA is the user
# surface; ComfyUI's built-in UI is never served to users).
ENV COMFYUI_FRONTEND_TAG=v1.55.11

# --- System deps --------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
      git \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
      curl \
      python3 \
      python3-pip \
      unzip \
      && rm -rf /var/lib/apt/lists/*

# --- Non-root user -------------------------------------------------------
RUN useradd --create-home --uid 1000 --gid 100 comfy
WORKDIR /home/comfy

# --- Python deps ---------------------------------------------------------
COPY requirements-extra.txt /opt/requirements-extra.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install \
         torch==2.5.1 \
         torchvision==0.20.1 \
         torchaudio==2.5.1 \
         --index-url https://download.pytorch.org/whl/cu124

# --- ComfyUI checkout (pinned) -------------------------------------------
RUN git clone https://github.com/Comfy-Org/ComfyUI.git /opt/ComfyUI \
    && cd /opt/ComfyUI \
    && git checkout "${COMFYUI_BACKEND_REV}" \
    && python3 -m pip install --no-cache-dir -r requirements.txt

RUN if [ -s /opt/requirements-extra.txt ]; then \
      python3 -m pip install --no-cache-dir -r /opt/requirements-extra.txt; \
    fi

# --- Frontend (pinned) ----------------------------------------------------
# The backend self-manages the frontend via --front-end-version when the
# web/ dir is absent; we install it explicitly so the version is auditable
# and reproducible without assuming the CLI's network fetch at boot.
ARG COMFYUI_FRONTEND_URL=\
https://github.com/Comfy-Org/ComfyUI_frontend/releases/download/${COMFYUI_FRONTEND_TAG}/dist.zip
RUN curl -fsSL "${COMFYUI_FRONTEND_URL}" -o /tmp/frontend.zip \
    && mkdir -p /opt/ComfyUI/web \
    && unzip -q /tmp/frontend.zip -d /opt/ComfyUI/web \
    && rm /tmp/frontend.zip

# --- Layout & entrypoint --------------------------------------------------
RUN mkdir -p /opt/ComfyUI/models \
             /opt/ComfyUI/output \
             /opt/ComfyUI/input \
             /opt/ComfyUI/user \
             /opt/ComfyUI/custom_nodes \
    && chown -R 1000:100 /opt/ComfyUI

COPY --chown=1000:100 entrypoint.sh /usr/local/bin/comfy-entrypoint
RUN chmod +x /usr/local/bin/comfy-entrypoint

WORKDIR /opt/ComfyUI
USER 1000:100
EXPOSE 8188
ENTRYPOINT ["/usr/local/bin/comfy-entrypoint"]
