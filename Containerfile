# ────────────────────────────────────────────────────────
# Just for fun — Podman/Chromium variant, not used for shipping.
# Same PesaPilot bot, built with a real headless Chromium instead
# of Baileys, so it runs via whatsapp-web.js under Podman.
# ────────────────────────────────────────────────────────
#
# Build:
#   podman build -t pesapilot .

FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1

RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    fontconfig \
    fonts-noto-color-emoji \
    fonts-dejavu \
    chromium \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN node --version && npm --version && chromium --version

WORKDIR /app

COPY entrypoint.wwebjs.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

ENV PUPPETEER_SKIP_DOWNLOAD=true

COPY package*.json ./
RUN npm install \
    && npm cache clean --force

COPY src/ ./src/
COPY whatsapp/ ./whatsapp/
COPY run.py .

RUN mkdir -p data/raw data/processed data/sessions \
    && mkdir -p .wwebjs_auth \
    && chmod -R 777 .wwebjs_auth \
    && chmod -R 777 data

ENV NODE_ENV=production
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

ENTRYPOINT ["./entrypoint.sh"]