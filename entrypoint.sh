#!/bin/bash
# PesaPilot Entrypoint - Startup with lock cleanup and process management

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

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: VALIDATE ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${YELLOW}📋 Step 1: Validating environment variables...${NC}"

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
    echo -e "${RED}Update your .env file and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All required variables configured${NC}\n"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: CLEANUP CHROME LOCK FILES
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${YELLOW}🧹 Step 2: Cleaning Chrome lock files...${NC}"

AUTH_PATH="/app/.wwebjs_auth"

# Create auth directory if it doesn't exist
if [ ! -d "$AUTH_PATH" ]; then
    echo -e "${BLUE}   Creating $AUTH_PATH${NC}"
    mkdir -p "$AUTH_PATH"
fi

# Define lock files that cause issues
LOCK_FILES=(
    "SingletonLock"
    "SingletonSocket"
    "SingletonCookie"
    "SingletonTab"
)

CLEANED_COUNT=0

# Remove lock files from auth directory
for lockfile in "${LOCK_FILES[@]}"; do
    FILEPATH="$AUTH_PATH/$lockfile"
    if [ -f "$FILEPATH" ]; then
        rm -f "$FILEPATH" 2>/dev/null || true
        CLEANED_COUNT=$((CLEANED_COUNT + 1))
        echo -e "${BLUE}   ✓ Removed $lockfile${NC}"
    fi
done

# Remove lock files from Default profile subdirectory
if [ -d "$AUTH_PATH/Default" ]; then
    for lockfile in "${LOCK_FILES[@]}"; do
        FILEPATH="$AUTH_PATH/Default/$lockfile"
        if [ -f "$FILEPATH" ]; then
            rm -f "$FILEPATH" 2>/dev/null || true
            CLEANED_COUNT=$((CLEANED_COUNT + 1))
            echo -e "${BLUE}   ✓ Removed Default/$lockfile${NC}"
        fi
    done
fi

# Remove Chrome crash report files and other lock-related files
if [ -d "$AUTH_PATH" ]; then
    find "$AUTH_PATH" -name "*SingletonLock*" -delete 2>/dev/null || true
    find "$AUTH_PATH" -name "*SingletonSocket*" -delete 2>/dev/null || true
    find "$AUTH_PATH" -name "*SingletonCookie*" -delete 2>/dev/null || true
    find "$AUTH_PATH" -name "*.lock" -delete 2>/dev/null || true
    find "$AUTH_PATH" -name "*.ldb" -delete 2>/dev/null || true
fi

if [ $CLEANED_COUNT -gt 0 ]; then
    echo -e "${GREEN}✅ Removed $CLEANED_COUNT lock file(s)${NC}\n"
else
    echo -e "${GREEN}✅ No lock files found (clean state)${NC}\n"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: SET PROPER PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${YELLOW}🔐 Step 3: Setting directory permissions...${NC}"

chmod -R 755 "$AUTH_PATH" 2>/dev/null || true
chmod -R 755 /app/data 2>/dev/null || true

echo -e "${GREEN}✅ Permissions set${NC}\n"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: START PYTHON API (Background)
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${YELLOW}🐍 Step 4: Starting FastAPI server...${NC}"

cd /app

python -m uvicorn whatsapp.whatsapp_api:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level warning \
    &

API_PID=$!
echo -e "${GREEN}✅ FastAPI started (PID: $API_PID)${NC}\n"

# Wait for API to be ready
echo -e "${BLUE}⏳ Waiting for API to initialize...${NC}"
sleep 3

# Check if API is responding
for i in {1..10}; do
    if curl -f http://localhost:8000/health >/dev/null 2>&1; then
        echo -e "${GREEN}✅ API is healthy${NC}\n"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${YELLOW}⚠️  API health check timeout (continuing anyway)${NC}\n"
    else
        echo -e "${BLUE}   Attempt $i/10...${NC}"
        sleep 1
    fi
done

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5: START NODE BOT
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${YELLOW}📱 Step 5: Starting WhatsApp Bot...${NC}\n"

node /app/whatsapp/whatsapp_bot.js &

BOT_PID=$!
echo -e "${GREEN}✅ WhatsApp Bot started (PID: $BOT_PID)${NC}\n"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6: WAIT AND MONITOR PROCESSES
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 PesaPilot is ONLINE and READY${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

echo -e "${BLUE}📊 Running processes:${NC}"
echo -e "${BLUE}   API:  http://0.0.0.0:8000${NC}"
echo -e "${BLUE}   Bot:  WhatsApp Web (Headless)${NC}\n"

# Function to handle shutdown gracefully
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down gracefully...${NC}"
    
    # Kill API
    if kill -0 $API_PID 2>/dev/null; then
        echo -e "${BLUE}   Stopping FastAPI...${NC}"
        kill -TERM $API_PID 2>/dev/null || true
        wait $API_PID 2>/dev/null || true
    fi
    
    # Kill Bot
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