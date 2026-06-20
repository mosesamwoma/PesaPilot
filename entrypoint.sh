#!/bin/bash
# PesaPilot Entrypoint - Production Ready

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🚀 PesaPilot Startup Sequence${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

# ============================================================
# STEP 1: DETECT ENVIRONMENT
# ============================================================
echo -e "${YELLOW}📋 Step 1: Detecting environment...${NC}"

# Detect if running on Railway
if [ -n "$RAILWAY_ENVIRONMENT" ] || [ -n "$RAILWAY_SERVICE_NAME" ]; then
    ENVIRONMENT="railway"
    echo -e "${BLUE}   Environment: Railway${NC}"
else
    ENVIRONMENT="docker"
    echo -e "${BLUE}   Environment: Docker/Local${NC}"
fi

# Get internal IP (prefer 127.0.0.1 over localhost)
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
    exit 1
fi

echo -e "${GREEN}✅ All required variables configured${NC}\n"

# ============================================================
# STEP 3: SET API URL (ENVIRONMENT SPECIFIC)
# ============================================================
echo -e "${YELLOW}🔗 Step 3: Configuring API URL...${NC}"

# Use environment variable if set, otherwise auto-detect
if [ -n "$API_URL" ]; then
    # Use user-provided API_URL
    export API_URL=$API_URL
    echo -e "${BLUE}   Using API_URL: $API_URL${NC}"
elif [ "$ENVIRONMENT" = "railway" ]; then
    # Railway: Use internal networking
    if [ -n "$RAILWAY_PRIVATE_DOMAIN" ]; then
        export API_URL="http://$RAILWAY_PRIVATE_DOMAIN:8000"
    elif [ -n "$RAILWAY_SERVICE_NAME" ]; then
        export API_URL="http://$RAILWAY_SERVICE_NAME.railway.internal:8000"
    else
        export API_URL="http://$INTERNAL_IP:8000"
    fi
    echo -e "${BLUE}   Railway API_URL: $API_URL${NC}"
else
    # Docker/Local: Use 127.0.0.1 instead of localhost
    export API_URL="http://127.0.0.1:8000"
    echo -e "${BLUE}   Local API_URL: $API_URL${NC}"
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
# STEP 6: START PYTHON API (Background)
# ============================================================
echo -e "${YELLOW}🐍 Step 6: Starting FastAPI server...${NC}"

cd /app

# Start API on 0.0.0.0 to accept all connections
if [ -f "/app/run.py" ]; then
    python /app/run.py &
else
    python -m uvicorn src.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level warning &
fi

API_PID=$!
echo -e "${GREEN}✅ FastAPI started (PID: $API_PID)${NC}"
echo -e "${BLUE}   Listening on: http://0.0.0.0:8000${NC}\n"

# ============================================================
# STEP 7: WAIT FOR API TO BE READY
# ============================================================
echo -e "${BLUE}⏳ Waiting for API to initialize...${NC}"

API_READY=false
for i in {1..20}; do
    # Try multiple addresses
    if curl -f http://127.0.0.1:8000/health 2>/dev/null || \
       curl -f http://localhost:8000/health 2>/dev/null || \
       curl -f http://$INTERNAL_IP:8000/health 2>/dev/null; then
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
# STEP 8: START NODE BOT
# ============================================================
echo -e "${YELLOW}📱 Step 8: Starting WhatsApp Bot...${NC}\n"

# Set environment for bot
export PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
export API_URL=${API_URL}

echo -e "${BLUE}   Bot will use API: $API_URL${NC}\n"

# Try different possible bot paths
if [ -f "/app/whatsapp/whatsapp_bot.js" ]; then
    node /app/whatsapp/whatsapp_bot.js &
elif [ -f "/app/src/bot.js" ]; then
    node /app/src/bot.js &
elif [ -f "/app/index.js" ]; then
    node /app/index.js &
else
    echo -e "${RED}❌ Could not find WhatsApp bot file${NC}"
    exit 1
fi

BOT_PID=$!
echo -e "${GREEN}✅ WhatsApp Bot started (PID: $BOT_PID)${NC}\n"

# ============================================================
# STEP 9: WAIT AND MONITOR PROCESSES
# ============================================================
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 PesaPilot is ONLINE and READY${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

echo -e "${BLUE}📊 Running processes:${NC}"
echo -e "${BLUE}   API:  http://0.0.0.0:8000${NC}"
echo -e "${BLUE}   Bot:  WhatsApp Web (Headless)${NC}"
echo -e "${BLUE}   API_URL: $API_URL${NC}\n"

# Function to handle shutdown gracefully
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down gracefully...${NC}"
    
    if kill -0 $API_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping FastAPI...${NC}"
        kill -TERM $API_PID 2>/dev/null || true
        wait $API_PID 2>/dev/null || true
    fi
    
    if kill -0 $BOT_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping WhatsApp Bot...${NC}"
        kill -TERM $BOT_PID 2>/dev/null || true
        wait $BOT_PID 2>/dev/null || true
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
kill -TERM $API_PID 2>/dev/null || true
kill -TERM $BOT_PID 2>/dev/null || true
wait 2>/dev/null || true

exit 1