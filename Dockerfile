FROM python:3.10-slim

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    ca-certificates \
    chromium \
    chromium-driver \
    libx11-xcb1 \
    libxcb1 \
    libxcb-dri3-0 \
    libxcb-present0 \
    libxcb-randr0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-keysyms1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-shape0 \
    libxcb-util1 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libglib2.0-0 \
    libnss3 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxss1 \
    libgbm1 \
    libasound2 \
    libxrandr2 \
    libxinerama1 \
    libxi6 \
    libxcursor1 \
    libxext6 \
    libxdamage1 \
    libxfixes3 \
    libpango-1.0-0 \
    libcairo2 \
    libxcomposite1 \
    libxshmfence1 \
    libgtk-3-0 \
    libgdk-pixbuf-2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean

RUN chromium --version && node --version && npm --version

WORKDIR /app

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY package*.json ./
RUN npm install --production \
    && npm cache clean --force

COPY src/ ./src/
COPY whatsapp/ ./whatsapp/
COPY run.py .

RUN mkdir -p data/raw data/processed data/sessions \
    && mkdir -p .wwebjs_auth \
    && chmod -R 777 .wwebjs_auth \
    && chmod -R 777 data

RUN apt-get update && apt-get install -y \
    fonts-noto-color-emoji \
    fonts-dejavu \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["./entrypoint.sh"]