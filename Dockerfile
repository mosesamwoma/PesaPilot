FROM python:3.10-slim

# ═══════════════════════════════════════════════════════════════════════════════
# INSTALL SYSTEM DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    ca-certificates \
    chromium \
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
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Verify installations
RUN chromium --version && node --version && npm --version

WORKDIR /app

# ═══════════════════════════════════════════════════════════════════════════════
# COPY ENTRYPOINT SCRIPT
# ═══════════════════════════════════════════════════════════════════════════════
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# ═══════════════════════════════════════════════════════════════════════════════
# INSTALL PYTHON DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ═══════════════════════════════════════════════════════════════════════════════
# INSTALL NODE DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════
COPY package*.json ./
RUN npm install --production && npm cache clean --force

# ═══════════════════════════════════════════════════════════════════════════════
# COPY APPLICATION CODE
# ═══════════════════════════════════════════════════════════════════════════════
COPY src/ ./src/
COPY whatsapp/ ./whatsapp/
COPY run.py .

# ═══════════════════════════════════════════════════════════════════════════════
# CREATE DIRECTORIES WITH PROPER PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════
RUN mkdir -p data/raw data/processed data/sessions \
    && mkdir -p .wwebjs_auth \
    && chmod -R 777 .wwebjs_auth \
    && chmod -R 777 data

# ═══════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT SETUP
# ═══════════════════════════════════════════════════════════════════════════════
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    CHROME_PATH=/usr/bin/chromium \
    WHATSAPP_API_URL=http://localhost:8000 \
    WHATSAPP_API_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]