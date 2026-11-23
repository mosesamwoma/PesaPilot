# PesaPilot — Baileys (TypeScript) WhatsApp bot + FastAPI API
# Shipped image: Baileys only. No Chromium/Puppeteer needed in production —
# Baileys talks to WhatsApp over a websocket, not a headless browser.
# (whatsapp-web.js scripts in package.json remain available for local dev only.)
#
# Multi-stage build: Node is copied from the official Node image instead of piping a
# remote setup script into bash as root, which removes a supply-chain risk from the build.

# ---------------------------------------------------------------- stage 1: build the bot
FROM node:24-bookworm-slim AS nodebuild
ENV PUPPETEER_SKIP_DOWNLOAD=true
WORKDIR /build
COPY package*.json tsconfig.json ./
RUN npm ci --ignore-scripts && npm cache clean --force
COPY whatsapp/ ./whatsapp/
RUN npm run build \
    && npm prune --omit=dev \
    && npm cache clean --force

# ---------------------------------------------------------------- stage 2: runtime
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Force UTF-8 everywhere (Python, Node, shell, logs) so emojis in
# WhatsApp replies / AI responses / chart titles never get mangled
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# curl (healthcheck) + fontconfig/fonts (chart text)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    fontconfig \
    fonts-noto-color-emoji \
    fonts-dejavu \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Node runtime from the official image (same Debian release, so it links cleanly).
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node
RUN node --version

# Unprivileged runtime user. The app code stays root-owned (read-only to the
# app); only the session and data folders are writable by this user.
# The host folders you bind-mount must be owned by this UID/GID — run
# scripts/prepare_dirs.sh once (or: sudo chown -R 10001:10001 sessions data).
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid ${APP_GID} pesapilot \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --home-dir /home/pesapilot \
       --create-home --shell /usr/sbin/nologin pesapilot

WORKDIR /app

COPY entrypoint_baileys.sh /app/entrypoint_baileys.sh
RUN chmod 755 /app/entrypoint_baileys.sh

# Python deps (all pinned in requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Compiled bot + production node_modules from stage 1
COPY package*.json ./
COPY --from=nodebuild /build/node_modules ./node_modules
COPY --from=nodebuild /build/dist ./dist

# App source
COPY src/ ./src/
COPY whatsapp/ ./whatsapp/

RUN mkdir -p data/raw data/processed data/sessions .baileys_auth \
    && chown -R ${APP_UID}:${APP_GID} data .baileys_auth \
    && chmod 700 .baileys_auth \
    && chmod 750 data

ENV NODE_ENV=production \
    HOME=/home/pesapilot

USER pesapilot

ENTRYPOINT ["./entrypoint_baileys.sh"]
