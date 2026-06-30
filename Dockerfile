# PesaPilot — Baileys (TypeScript) WhatsApp bot + FastAPI dashboard API
# No Chromium/Puppeteer needed: Baileys talks to WhatsApp over a websocket.
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true

# ----------------------------------------------------------------
# System deps: curl (healthcheck) + Node.js 20.x
# ----------------------------------------------------------------
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN node --version && npm --version

WORKDIR /app

# ----------------------------------------------------------------
# Entrypoint (Baileys-specific — entrypoint.sh in repo is for the
# legacy whatsapp-web.js bot and is intentionally NOT used here)
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
# Node deps (install all, including devDependencies, since we
# need typescript/ts-node to build the Baileys bot)
# ----------------------------------------------------------------
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

RUN apt-get update && apt-get install -y \
    fonts-noto-color-emoji \
    fonts-dejavu \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production \
    BAILEYS_AUTH_PATH=/app/.baileys_auth

ENTRYPOINT ["./entrypoint.baileys.sh"]