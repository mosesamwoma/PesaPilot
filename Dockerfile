# PesaPilot — Baileys (TypeScript) WhatsApp bot + FastAPI dashboard API
# Shipped image: Baileys only. No Chromium/Puppeteer needed in production —
# Baileys talks to WhatsApp over a websocket, not a headless browser.
# (whatsapp-web.js scripts in package.json remain available for local dev only.)
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

# ----------------------------------------------------------------
# Force UTF-8 everywhere (Python, Node, shell, logs) so emojis in
# WhatsApp replies / AI responses / chart titles never get mangled
# ----------------------------------------------------------------
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1

# ----------------------------------------------------------------
# System deps: curl (healthcheck) + fontconfig (chart fonts) + Node.js 20.x
# ----------------------------------------------------------------
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    fontconfig \
    fonts-noto-color-emoji \
    fonts-dejavu \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN node --version && npm --version

WORKDIR /app

# ----------------------------------------------------------------
# Entrypoint (Baileys only — entrypoint.sh stays in the repo as a
# local-dev/manual fallback for whatsapp-web.js, but is intentionally
# NOT copied into the shipped image)
# ----------------------------------------------------------------
COPY entrypoint.baileys.sh /app/entrypoint.baileys.sh
RUN chmod +x /app/entrypoint.baileys.sh

# ----------------------------------------------------------------
# Python deps
# ----------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------------
# Node deps (full install incl. devDependencies for the tsc build step;
# puppeteer/whatsapp-web.js get installed here too since they're still
# in package.json for local dev, but they are NEVER invoked at runtime
# in this image since only dist/whatsapp_bot.js gets executed)
#
# PUPPETEER_SKIP_DOWNLOAD=true is required here: puppeteer's postinstall
# script otherwise tries to download a full Chrome binary, which fails
# the build entirely on networks/CI runners that block that host. This
# must be a real ENV var at build time — .env is never read by `docker
# build`, and older var names like PUPPETEER_SKIP_CHROMIUM_DOWNLOAD are
# ignored by current puppeteer versions.
# ----------------------------------------------------------------
ENV PUPPETEER_SKIP_DOWNLOAD=true

COPY package*.json tsconfig.json ./
RUN npm install \
    && npm cache clean --force

# ----------------------------------------------------------------
# App source
# ----------------------------------------------------------------
COPY src/ ./src/
COPY whatsapp/ ./whatsapp/
COPY run.py .

# Compile whatsapp_bot.ts -> dist/whatsapp_bot.js (Baileys)
RUN npm run build

# Drop devDependencies now that the build is done, to slim the image
RUN npm prune --omit=dev \
    && npm cache clean --force

RUN mkdir -p data/raw data/processed data/sessions \
    && mkdir -p .baileys_auth \
    && chmod -R 777 .baileys_auth \
    && chmod -R 777 data

ENV NODE_ENV=production

ENTRYPOINT ["./entrypoint.baileys.sh"]