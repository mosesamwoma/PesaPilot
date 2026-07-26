#!/bin/bash
# PesaPilot Entrypoint - whatsapp-web.js - Production Ready
# Works on any server: plain Docker, Docker Compose, VPS, bare-metal, Raspberry Pi.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🚀 PesaPilot Startup Sequence${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

# ============================================================
# STEP 1: DETECT ENVIRONMENT
# ============================================================
echo -e "${YELLOW}📋 Step 1: Detecting environment...${NC}"

INTERNAL_IP=$(hostname -i 2>/dev/null | awk '{print $1}')
if [ -z "$INTERNAL_IP" ]; then
    INTERNAL_IP="127.0.0.1"
fi
echo -e "${BLUE}   Internal IP: $INTERNAL_IP${NC}"
echo -e "${BLUE}   Hostname: $(hostname 2>/dev/null || echo unknown)${NC}\n"

# ============================================================
# STEP 2: VALIDATE ENVIRONMENT VARIABLES
# ============================================================
echo -e "${YELLOW}📋 Step 2: Validating environment variables...${NC}"

REQUIRED_VARS=(
    "SUPABASE_URL"
    "SUPABASE_KEY"
    "GROQ_API_KEY"
    "WHATSAPP_MAIN_NUMBER"
    "WHATSAPP_LID"
    "WHATSAPP_PIN"
)

MISSING_VARS=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo -e "${RED}❌ Missing required environment variables:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo -e "${RED}   - $var${NC}"
    done
    echo -e "${RED}Set these in your .env file (or however you inject env vars) and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All required variables configured${NC}\n"

# ============================================================
# STEP 3: CONFIGURE API URL
# ============================================================
echo -e "${YELLOW}🔗 Step 3: Configuring API URL...${NC}"

# If API_URL is explicitly set (e.g. the bot and API run on different hosts/containers),
# always respect it. Otherwise default to loopback, since both processes run in this
# same container/host and talk to each other over localhost.
if [ -n "$API_URL" ]; then
    export API_URL="$API_URL"
    echo -e "${BLUE}   Using API_URL: $API_URL${NC}"
else
    export API_URL="http://127.0.0.1:${API_PORT:-8000}"
    echo -e "${BLUE}   Default API_URL: $API_URL${NC}"
fi

echo -e "${GREEN}✅ API_URL configured${NC}\n"

# ============================================================
# STEP 4: CLEANUP CHROME LOCK FILES
# ============================================================
echo -e "${YELLOW}🧹 Step 4: Cleaning Chrome lock files...${NC}"

AUTH_PATH="/app/.wwebjs_auth"

if [ ! -d "$AUTH_PATH" ]; then
    mkdir -p "$AUTH_PATH"
fi

LOCK_FILES=(
    "SingletonLock"
    "SingletonSocket"
    "SingletonCookie"
    "SingletonTab"
)

CLEANED_COUNT=0

for lockfile in "${LOCK_FILES[@]}"; do
    FILEPATH="$AUTH_PATH/$lockfile"
    if [ -f "$FILEPATH" ]; then
        rm -f "$FILEPATH" 2>/dev/null || true
        CLEANED_COUNT=$((CLEANED_COUNT + 1))
    fi
done

if [ -d "$AUTH_PATH/Default" ]; then
    for lockfile in "${LOCK_FILES[@]}"; do
        FILEPATH="$AUTH_PATH/Default/$lockfile"
        if [ -f "$FILEPATH" ]; then
            rm -f "$FILEPATH" 2>/dev/null || true
            CLEANED_COUNT=$((CLEANED_COUNT + 1))
        fi
    done
fi

# Remove any other lock files
find "$AUTH_PATH" -name "*.lock" -delete 2>/dev/null || true
find "$AUTH_PATH" -name "*.ldb" -delete 2>/dev/null || true

if [ $CLEANED_COUNT -gt 0 ]; then
    echo -e "${GREEN}✅ Removed $CLEANED_COUNT lock file(s)${NC}\n"
else
    echo -e "${GREEN}✅ No lock files found (clean state)${NC}\n"
fi

# ============================================================
# STEP 5: SET PROPER PERMISSIONS
# ============================================================
echo -e "${YELLOW}🔐 Step 5: Setting directory permissions...${NC}"

chmod -R 755 "$AUTH_PATH" 2>/dev/null || true
chmod -R 755 /app/data 2>/dev/null || true

echo -e "${GREEN}✅ Permissions set${NC}\n"

# ============================================================
# STEP 6: START FASTAPI SERVER
# ============================================================
echo -e "${YELLOW}🐍 Step 6: Starting FastAPI server...${NC}"

cd /app

# Set Python path and run the API module
export PYTHONPATH=/app:$PYTHONPATH

# Check if whatsapp_api.py exists
if [ -f "/app/whatsapp/whatsapp_api.py" ]; then
    # Run as module with proper Python path
    python -m whatsapp.whatsapp_api &
    API_PID=$!
    echo -e "${GREEN}✅ FastAPI started (PID: $API_PID)${NC}"
    echo -e "${BLUE}   Listening on: http://0.0.0.0:${API_PORT:-8000}${NC}\n"
else
    echo -e "${RED}❌ whatsapp/whatsapp_api.py not found!${NC}"
    exit 1
fi

# ============================================================
# STEP 7: WAIT FOR API TO BE READY
# ============================================================
echo -e "${BLUE}⏳ Waiting for API to initialize...${NC}"

API_READY=false
for i in {1..20}; do
    if curl -f "http://127.0.0.1:${API_PORT:-8000}/health" 2>/dev/null; then
        API_READY=true
        echo -e "${GREEN}✅ API is healthy${NC}\n"
        break
    fi
    if [ $i -eq 20 ]; then
        echo -e "${YELLOW}⚠️  API health check timeout (continuing anyway)${NC}\n"
    else
        echo -e "${BLUE}   Attempt $i/20...${NC}"
        sleep 1
    fi
done

# ============================================================
# STEP 8: START WHATSAPP BOT
# ============================================================
echo -e "${YELLOW}📱 Step 8: Starting WhatsApp Bot...${NC}\n"

# Set environment for bot
export PUPPETEER_EXECUTABLE_PATH=${PUPPETEER_EXECUTABLE_PATH:-/usr/bin/chromium}
export API_URL=${API_URL}

echo -e "${BLUE}   Bot will use API: $API_URL${NC}\n"

# Try different possible bot paths
BOT_PATH=""
if [ -f "/app/whatsapp/whatsapp_bot.js" ]; then
    BOT_PATH="/app/whatsapp/whatsapp_bot.js"
elif [ -f "/app/src/bot.js" ]; then
    BOT_PATH="/app/src/bot.js"
elif [ -f "/app/index.js" ]; then
    BOT_PATH="/app/index.js"
else
    echo -e "${RED}❌ Could not find WhatsApp bot file${NC}"
    echo -e "${RED}   Searched in: whatsapp/whatsapp_bot.js, src/bot.js, index.js${NC}"
    exit 1
fi

echo -e "${BLUE}   Bot file: $BOT_PATH${NC}"

# Start the bot
node "$BOT_PATH" &
BOT_PID=$!
echo -e "${GREEN}✅ WhatsApp Bot started (PID: $BOT_PID)${NC}\n"

# ============================================================
# STEP 9: DISPLAY STATUS
# ============================================================
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 PesaPilot is ONLINE and READY${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

echo -e "${BLUE}📊 Running processes:${NC}"
echo -e "${BLUE}   API:  http://0.0.0.0:${API_PORT:-8000}${NC}"
echo -e "${BLUE}   Bot:  WhatsApp Web (Headless)${NC}"
echo -e "${BLUE}   API_URL: $API_URL${NC}\n"

# ============================================================
# STEP 10: PROCESS MANAGEMENT AND CLEANUP
# ============================================================

# Function to handle shutdown gracefully
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down gracefully...${NC}"

    # Kill API
    if kill -0 $API_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping FastAPI (PID: $API_PID)...${NC}"
        kill -TERM $API_PID 2>/dev/null || true
        wait $API_PID 2>/dev/null || true
        echo -e "${GREEN}   ✅ FastAPI stopped${NC}"
    fi

    # Kill Bot
    if kill -0 $BOT_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping WhatsApp Bot (PID: $BOT_PID)...${NC}"
        kill -TERM $BOT_PID 2>/dev/null || true
        wait $BOT_PID 2>/dev/null || true
        echo -e "${GREEN}   ✅ WhatsApp Bot stopped${NC}"
    fi

    echo -e "${GREEN}✅ Shutdown complete${NC}"
    exit 0
}

# Set trap for SIGTERM and SIGINT
trap cleanup SIGTERM SIGINT

# Wait for both processes
wait -n

# If one dies, kill the other and exit
echo -e "${RED}❌ A process exited unexpectedly${NC}"
echo -e "${RED}   API PID: $API_PID, Bot PID: $BOT_PID${NC}"

# Kill both processes
kill -TERM $API_PID 2>/dev/null || true
kill -TERM $BOT_PID 2>/dev/null || true
wait 2>/dev/null || true

exit 1