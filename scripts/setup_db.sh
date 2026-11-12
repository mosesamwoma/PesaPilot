#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCHEMA_FILE="$PROJECT_ROOT/schema/init_db.sql"

env_value() {
    [ -f "$PROJECT_ROOT/.env" ] || return 0
    grep -E "^$1=" "$PROJECT_ROOT/.env" | tail -n1 | cut -d= -f2- || true
}

PGSQL_USER="${PGSQL_USER:-$(env_value POSTGRES_USER)}"
PGSQL_PASSWORD="${PGSQL_PASSWORD:-$(env_value POSTGRES_PASSWORD)}"
PGSQL_DB="${PGSQL_DB:-$(env_value POSTGRES_DB)}"
PGSQL_USER="${PGSQL_USER:-pesapilot}"
PGSQL_DB="${PGSQL_DB:-pesapilot}"

if [ -z "$PGSQL_PASSWORD" ]; then
    echo "No database password set. Run scripts/generate_secrets.sh first (or export PGSQL_PASSWORD)."
    exit 1
fi
case "$(echo "$PGSQL_PASSWORD" | tr '[:upper:]' '[:lower:]')" in
    change-me*|pesapilot|password) echo "POSTGRES_PASSWORD is a placeholder. Run scripts/generate_secrets.sh."; exit 1 ;;
esac
if [ "${#PGSQL_PASSWORD}" -lt 12 ]; then
    echo "POSTGRES_PASSWORD must be at least 12 characters."
    exit 1
fi
if ! printf '%s' "$PGSQL_PASSWORD" | grep -Eq '^[A-Za-z0-9._~@%^+=:,-]+$'; then
    echo "POSTGRES_PASSWORD may only contain letters, digits and . _ ~ @ % ^ + = : , -"
    echo "Use scripts/generate_secrets.sh --rotate to create a compatible one."
    exit 1
fi
if ! printf '%s' "$PGSQL_USER$PGSQL_DB" | grep -Eq '^[a-z_][a-z0-9_]*$'; then
    echo "POSTGRES_USER and POSTGRES_DB must be lower-case letters, digits and underscores."
    exit 1
fi

echo "=============================================================="
echo " PesaPilot — standalone PostgreSQL setup"
echo " (this does NOT touch Docker or Podman — Postgres runs directly"
echo "  on this machine, as its own system service)"
echo "=============================================================="
echo

if [ ! -f "$SCHEMA_FILE" ]; then
    echo "Could not find $SCHEMA_FILE"
    echo "   Run this script from a checkout of the PesaPilot repo."
    exit 1
fi

if command -v psql >/dev/null 2>&1; then
    echo "PostgreSQL client already installed ($(psql --version))"
else
    echo "==> Installing PostgreSQL..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y postgresql postgresql-contrib
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y postgresql-server postgresql-contrib
        if [ ! -d /var/lib/pgsql/data ] || [ -z "$(ls -A /var/lib/pgsql/data 2>/dev/null)" ]; then
            sudo postgresql-setup --initdb
        fi
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y postgresql-server postgresql-contrib
        if [ ! -d /var/lib/pgsql/data ] || [ -z "$(ls -A /var/lib/pgsql/data 2>/dev/null)" ]; then
            sudo postgresql-setup --initdb
        fi
    elif command -v brew >/dev/null 2>&1; then
        brew install postgresql@16
        brew services start postgresql@16
    else
        echo "Could not detect a supported package manager (apt/dnf/yum/brew)."
        echo "   Install PostgreSQL manually for your distro, then re-run this script —"
        echo "   it will skip installation and continue from schema setup."
        exit 1
    fi
fi

echo "==> Ensuring PostgreSQL service is running..."
if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable postgresql --now 2>/dev/null \
        || sudo systemctl enable postgresql.service --now 2>/dev/null \
        || true
elif command -v brew >/dev/null 2>&1; then
    brew services start postgresql@16 || true
fi

sleep 2

echo "==> Creating role '$PGSQL_USER' and database '$PGSQL_DB' (if they don't exist)..."

run_psql() {
    if id -u postgres >/dev/null 2>&1; then
        if [ "$(id -u)" -eq 0 ]; then
            runuser -u postgres -- psql -v ON_ERROR_STOP=1 "$@"
        else
            sudo -u postgres psql -v ON_ERROR_STOP=1 "$@"
        fi
    else
        psql -v ON_ERROR_STOP=1 "$@"
    fi
}

run_psql -d postgres <<SQL
\set u '$PGSQL_USER'
\set pw '$PGSQL_PASSWORD'
\set d '$PGSQL_DB'
SELECT format('CREATE ROLE %I LOGIN', :'u') WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'u') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'u', :'pw') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'d', :'u') WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'d') \gexec
SQL

echo "Role and database ready"
echo

echo "==> Applying schema/init_db.sql..."

if command -v psql >/dev/null 2>&1; then
    PGPASSWORD="$PGSQL_PASSWORD" psql -v ON_ERROR_STOP=1 \
        -h 127.0.0.1 -p 5432 -U "$PGSQL_USER" -d "$PGSQL_DB" \
        -f "$SCHEMA_FILE"
fi

echo
echo "=============================================================="
echo " PesaPilot DB ready"
echo "=============================================================="
echo
echo "Your .env should contain:"
echo
echo "  POSTGRES_USER=$PGSQL_USER"
echo "  POSTGRES_PASSWORD=(unchanged - already in your .env)"
echo "  POSTGRES_DB=$PGSQL_DB"
echo "  POSTGRES_HOST=127.0.0.1"
echo "  POSTGRES_PORT=5432"
echo
echo "If the app runs inside Docker, set POSTGRES_HOST=host.docker.internal instead of 127.0.0.1."
echo "If the app runs inside Podman, set POSTGRES_HOST=host.containers.internal instead."
echo
echo "PostgreSQL must also be configured to accept connections from your"
echo "container's network. If Docker/Podman can't reach it, check that"
echo "postgresql.conf has listen_addresses='*' and pg_hba.conf allows"
echo "connections from the container's subnet (typically 172.16.0.0/12"
echo "for Docker, 10.88.0.0/16 for Podman's default network)."
