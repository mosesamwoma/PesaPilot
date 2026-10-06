#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}🚀 PesaPilot Startup Sequence${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}📋 Step 1: Detecting environment...${NC}"

INTERNAL_IP=$(hostname -i 2>/dev/null | awk '{print $1}')
if [ -z "$INTERNAL_IP" ]; then
    INTERNAL_IP="127.0.0.1"
fi
echo -e "${BLUE}   Internal IP: $INTERNAL_IP${NC}"
echo -e "${BLUE}   Hostname: $(hostname 2>/dev/null || echo unknown)${NC}\n"

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

echo -e "${YELLOW}🗄️  Step 2b: Checking database connectivity...${NC}"

_detect_postgres_host() {
    if [ -f /run/.containerenv ] || [ "$container" = "podman" ]; then
        echo "host.containers.internal"
        return
    fi
    if [ -f /.dockerenv ]; then
        if python -c "import socket; socket.gethostbyname('host.docker.internal')" >/dev/null 2>&1; then
            echo "host.docker.internal"
        else
            echo "172.17.0.1"
        fi
        return
    fi
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

export POSTGRES_PORT
if python -c "
import os, sys, psycopg2
try:
    conn = psycopg2.connect(
        user=os.environ['POSTGRES_USER'],
        password=os.environ['POSTGRES_PASSWORD'],
        dbname=os.environ['POSTGRES_DB'],
        host=os.environ['POSTGRES_HOST'],
        port=os.environ['POSTGRES_PORT'],
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

echo -e "${YELLOW}🔗 Step 3: Configuring API URL...${NC}"

if [ -n "$API_URL" ]; then
    export API_URL="$API_URL"
    echo -e "${BLUE}   Using API_URL: $API_URL${NC}"
else
    export API_URL="http://127.0.0.1:${WHATSAPP_API_PORT:-8000}"
    echo -e "${BLUE}   Default API_URL: $API_URL${NC}"
fi

echo -e "${GREEN}✅ API_URL configured${NC}\n"

echo -e "${YELLOW}🧹 Step 4: Cleaning Chrome lock files...${NC}"

AUTH_PATH="${WWEBJS_AUTH_PATH:-/app/.wwebjs_auth}"

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

find "$AUTH_PATH" -name "*.lock" -delete 2>/dev/null || true
find "$AUTH_PATH" -name "*.ldb" -delete 2>/dev/null || true

if [ $CLEANED_COUNT -gt 0 ]; then
    echo -e "${GREEN}✅ Removed $CLEANED_COUNT lock file(s)${NC}\n"
else
    echo -e "${GREEN}✅ No lock files found (clean state)${NC}\n"
fi

echo -e "${YELLOW}🔐 Step 5: Setting directory permissions...${NC}"

chmod -R 755 "$AUTH_PATH" 2>/dev/null || true
chmod -R 755 /app/data 2>/dev/null || true

echo -e "${GREEN}✅ Permissions set${NC}\n"

echo -e "${YELLOW}🐍 Step 6: Starting FastAPI server...${NC}"

cd /app

export PYTHONPATH=/app:$PYTHONPATH

if [ -f "/app/whatsapp/whatsapp_api.py" ]; then
    python -m whatsapp.whatsapp_api &
    API_PID=$!
    echo -e "${GREEN}✅ FastAPI started (PID: $API_PID)${NC}"
    echo -e "${BLUE}   Listening on: http://0.0.0.0:${WHATSAPP_API_PORT:-8000}${NC}\n"
else
    echo -e "${RED}❌ whatsapp/whatsapp_api.py not found!${NC}"
    exit 1
fi

echo -e "${BLUE}⏳ Waiting for API to initialize...${NC}"

for i in {1..20}; do
    if curl -fsS "http://127.0.0.1:${WHATSAPP_API_PORT:-8000}/health" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ API is healthy${NC}\n"
        break
    fi
    if [ "$i" -eq 20 ]; then
        echo -e "${YELLOW}⚠️  API health check timeout (continuing anyway)${NC}\n"
    else
        echo -e "${BLUE}   Attempt $i/20...${NC}"
        sleep 1
    fi
done

echo -e "${YELLOW}📱 Step 7: Starting WhatsApp Bot...${NC}\n"

export PUPPETEER_EXECUTABLE_PATH=${PUPPETEER_EXECUTABLE_PATH:-/usr/bin/google-chrome-stable}
export API_URL=${API_URL}

echo -e "${BLUE}   Bot will use API: $API_URL${NC}\n"

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

node "$BOT_PATH" &
BOT_PID=$!
echo -e "${GREEN}✅ WhatsApp Bot started (PID: $BOT_PID)${NC}\n"

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🚀 PesaPilot is ONLINE and READY${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}\n"

echo -e "${BLUE}📊 Running processes:${NC}"
echo -e "${BLUE}   API:  http://0.0.0.0:${WHATSAPP_API_PORT:-8000}${NC}"
echo -e "${BLUE}   Bot:  WhatsApp Web (Headless)${NC}"
echo -e "${BLUE}   API_URL: $API_URL${NC}\n"


cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down gracefully...${NC}"

    if kill -0 "$API_PID" 2>/dev/null; then
        echo -e "${BLUE}   Stopping FastAPI (PID: $API_PID)...${NC}"
        kill -TERM "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
        echo -e "${GREEN}   ✅ FastAPI stopped${NC}"
    fi

    if kill -0 "$BOT_PID" 2>/dev/null; then
        echo -e "${BLUE}   Stopping WhatsApp Bot (PID: $BOT_PID)...${NC}"
        kill -TERM "$BOT_PID" 2>/dev/null || true
        wait "$BOT_PID" 2>/dev/null || true
        echo -e "${GREEN}   ✅ WhatsApp Bot stopped${NC}"
    fi

    echo -e "${GREEN}✅ Shutdown complete${NC}"
    exit 0
}

trap cleanup SIGTERM SIGINT

wait -n

echo -e "${RED}❌ A process exited unexpectedly${NC}"
echo -e "${RED}   API PID: $API_PID, Bot PID: $BOT_PID${NC}"

kill -TERM "$API_PID" 2>/dev/null || true
kill -TERM "$BOT_PID" 2>/dev/null || true
wait 2>/dev/null || true

exit 1