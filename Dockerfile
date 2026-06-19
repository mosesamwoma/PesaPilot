# Dockerfile (root) - PRODUCTION READY WITH LOCK FIX
FROM python:3.10-slim

# Install Node.js and Chromium correctly
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y \
    nodejs \
    chromium \
    libglib2.0-0 \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node deps
COPY package*.json ./
RUN npm install --production

# Copy code
COPY src/ ./src/
COPY whatsapp/ ./whatsapp/
COPY run.py .

# Create persistent directories with proper permissions
RUN mkdir -p data/raw data/processed data/sessions
RUN mkdir -p .wwebjs_auth
RUN chmod -R 777 .wwebjs_auth

# No Streamlit - API only
EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV NODE_ENV=production
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV WHATSAPP_API_URL=http://localhost:8000

# Clean up lock files before starting
# Both processes
CMD sh -c "rm -f /app/.wwebjs_auth/SingletonLock /app/.wwebjs_auth/SingletonSocket /app/.wwebjs_auth/SingletonCookie 2>/dev/null || true && uvicorn whatsapp.whatsapp_api:app --host 0.0.0.0 --port 8000 & node whatsapp/whatsapp_bot.js"