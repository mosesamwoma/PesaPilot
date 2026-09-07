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
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
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
    echo -e "${RED}POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB must point at a PostgreSQL server you already set up${NC}"
    echo -e "${RED}(see scripts/setup_db.sh) — this container does not run its own database.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All required variables configured${NC}\n"

# ============================================================
# STEP 2b: VERIFY DATABASE IS REACHABLE
# ============================================================
echo -e "${YELLOW}🗄️  Step 2b: Checking database connectivity...${NC}"

# POSTGRES_HOST supports the special value "auto" (also the default when the
# var is unset/empty) — same contract as src/database.py's _pg_connection_kwargs().
# This resolves it in bash BEFORE the psycopg2 check below, otherwise the
# literal string "auto" gets used as a hostname and DNS resolution fails.
_detect_postgres_host() {
    # Podman: sets /run/.containerenv and/or container=podman. Resolves
    # host.containers.internal for every container automatically.
    if [ -f /run/.containerenv ] || [ "$container" = "podman" ]; then
        echo "host.containers.internal"
        return
    fi
    # Docker: /.dockerenv exists in every container's root filesystem.
    if [ -f /.dockerenv ]; then
        if python -c "import socket; socket.gethostbyname('host.docker.internal')" >/dev/null 2>&1; then
            echo "host.docker.internal"
        else
            # host.docker.internal didn't resolve (e.g. plain `docker run`
            # without extra_hosts on Linux) — fall back to the default
            # bridge network's gateway, which reaches the host on most
            # Linux installs without any extra config.
            echo "172.17.0.1"
        fi
        return
    fi
    # Bare metal: no container runtime detected.
    echo "127.0.0.1"
}

RAW_POSTGRES_HOST="${POSTGRES_HOST:-auto}"
RAW_POSTGRES_HOST_LOWER=$(echo "$RAW_POSTGRES_HOST" | tr '[:upper:]' '[:lower:]')
if [ -z "$RAW_POSTGRES_HOST" ] || [ "$RAW_POSTGRES_HOST_LOWER" = "auto" ]; then
    POSTGRES_HOST="$(_detect_postgres_host)"
    echo -e "${BLUE}   POSTGRES_HOST=auto -> detected '$POSTGRES_HOST'${NC}"
else
    POSTGRES_HOST="$RAW_POSTGRES_HOST"
fi
export POSTGRES_HOST
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

if python -c "
import sys, psycopg2
try:
    conn = psycopg2.connect(
        user='$POSTGRES_USER',
        password='$POSTGRES_PASSWORD',
        dbname='$POSTGRES_DB',
        host='$POSTGRES_HOST',
        port='$POSTGRES_PORT',
        connect_timeout=5,
    )
    conn.close()
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
" 2>/tmp/db_check_error; then
    echo -e "${GREEN}✅ Database is reachable${NC}\n"
else
    echo -e "${RED}❌ Could not connect to Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}${NC}"
    echo -e "${RED}   $(cat /tmp/db_check_error)${NC}"
    echo -e "${RED}   Make sure PostgreSQL is running and reachable from this container${NC}"
    echo -e "${RED}   (see scripts/setup_db.sh for a standalone setup, run outside Docker/Podman).${NC}"
    exit 1
fi

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
export PUPPETEER_EXECUTABLE_PATH=${PUPPETEER_EXECUTABLE_PATH:-/usr/bin/google-chrome-stable}
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