#!/bin/bash
# PesaPilot Entrypoint - Baileys (TypeScript) - Production Ready

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🚀 PesaPilot Startup Sequence (Baileys)${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

# ============================================================
# STEP 1: DETECT ENVIRONMENT
# ============================================================
echo -e "${YELLOW}📋 Step 1: Detecting environment...${NC}"

if [ -n "$RAILWAY_ENVIRONMENT" ] || [ -n "$RAILWAY_SERVICE_NAME" ]; then
    ENVIRONMENT="railway"
    echo -e "${BLUE}   Environment: Railway${NC}"
else
    ENVIRONMENT="docker"
    echo -e "${BLUE}   Environment: Docker/Local${NC}"
fi

INTERNAL_IP=$(hostname -i 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
echo -e "${BLUE}   Internal IP: $INTERNAL_IP${NC}"

# ============================================================
# STEP 2: VALIDATE ENVIRONMENT VARIABLES
# ============================================================
echo -e "${YELLOW}📋 Step 2: Validating environment variables...${NC}"

REQUIRED_VARS=(
    "SUPABASE_URL"
    "SUPABASE_KEY"
    "GROQ_API_KEY"
    "WHATSAPP_MAIN_NUMBER"
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
    echo -e "${RED}Update your environment variables and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All required variables configured${NC}\n"

# ============================================================
# STEP 3: CONFIGURE API URL
# ============================================================
echo -e "${YELLOW}🔗 Step 3: Configuring API URL...${NC}"

if [ -n "$API_URL" ]; then
    export API_URL=$API_URL
    echo -e "${BLUE}   Using API_URL: $API_URL${NC}"
elif [ "$ENVIRONMENT" = "railway" ]; then
    if [ -n "$RAILWAY_PRIVATE_DOMAIN" ]; then
        export API_URL="http://$RAILWAY_PRIVATE_DOMAIN:8000"
    elif [ -n "$RAILWAY_SERVICE_NAME" ]; then
        export API_URL="http://$RAILWAY_SERVICE_NAME.railway.internal:8000"
    else
        export API_URL="http://$INTERNAL_IP:8000"
    fi
    echo -e "${BLUE}   Railway API_URL: $API_URL${NC}"
else
    export API_URL="http://127.0.0.1:8000"
    echo -e "${BLUE}   Local API_URL: $API_URL${NC}"
fi

echo -e "${GREEN}✅ API_URL configured${NC}\n"

# ============================================================
# STEP 4: PREPARE BAILEYS AUTH DIRECTORY
# ============================================================
echo -e "${YELLOW}🧹 Step 4: Preparing Baileys auth directory...${NC}"

AUTH_PATH="${BAILEYS_AUTH_PATH:-/app/.baileys_auth}"

if [ ! -d "$AUTH_PATH" ]; then
    mkdir -p "$AUTH_PATH"
fi

echo -e "${GREEN}✅ Auth directory ready: $AUTH_PATH${NC}\n"

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
    echo -e "${BLUE}   Listening on: http://0.0.0.0:8000${NC}\n"
else
    echo -e "${RED}❌ whatsapp/whatsapp_api.py not found!${NC}"
    exit 1
fi

# ============================================================
# STEP 7: WAIT FOR API TO BE READY
# ============================================================
echo -e "${BLUE}⏳ Waiting for API to initialize...${NC}"

for i in {1..20}; do
    if curl -f http://127.0.0.1:8000/health 2>/dev/null; then
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
# STEP 8: START WHATSAPP BOT (BAILEYS, COMPILED JS)
# ============================================================
echo -e "${YELLOW}📱 Step 8: Starting WhatsApp Bot (Baileys)...${NC}\n"

export API_URL=${API_URL}
export BAILEYS_AUTH_PATH=${AUTH_PATH}

echo -e "${BLUE}   Bot will use API: $API_URL${NC}\n"

BOT_PATH=""
if [ -f "/app/dist/whatsapp_bot.js" ]; then
    BOT_PATH="/app/dist/whatsapp_bot.js"
else
    echo -e "${RED}❌ Could not find compiled Baileys bot at /app/dist/whatsapp_bot.js${NC}"
    echo -e "${RED}   Did the TypeScript build (npm run build) run during image build?${NC}"
    exit 1
fi

echo -e "${BLUE}   Bot file: $BOT_PATH${NC}"

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
echo -e "${BLUE}   API:  http://0.0.0.0:8000${NC}"
echo -e "${BLUE}   Bot:  WhatsApp (Baileys, multi-device socket)${NC}"
echo -e "${BLUE}   API_URL: $API_URL${NC}\n"

# ============================================================
# STEP 10: PROCESS MANAGEMENT AND CLEANUP
# ============================================================

cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down gracefully...${NC}"

    if kill -0 $API_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping FastAPI (PID: $API_PID)...${NC}"
        kill -TERM $API_PID 2>/dev/null || true
        wait $API_PID 2>/dev/null || true
        echo -e "${GREEN}   ✅ FastAPI stopped${NC}"
    fi

    if kill -0 $BOT_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping WhatsApp Bot (PID: $BOT_PID)...${NC}"
        kill -TERM $BOT_PID 2>/dev/null || true
        wait $BOT_PID 2>/dev/null || true
        echo -e "${GREEN}   ✅ WhatsApp Bot stopped${NC}"
    fi

    echo -e "${GREEN}✅ Shutdown complete${NC}"
    exit 0
}

trap cleanup SIGTERM SIGINT

wait -n

echo -e "${RED}❌ A process exited unexpectedly${NC}"
echo -e "${RED}   API PID: $API_PID, Bot PID: $BOT_PID${NC}"

kill -TERM $API_PID 2>/dev/null || true
kill -TERM $BOT_PID 2>/dev/null || true
wait 2>/dev/null || true

exit 1