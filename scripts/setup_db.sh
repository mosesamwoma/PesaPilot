#!/usr/bin/env bash
set -euo pipefail

PGSQL_USER="${PGSQL_USER:-pesapilot}"
PGSQL_PASSWORD="${PGSQL_PASSWORD:-pesapilot}"
PGSQL_DB="${PGSQL_DB:-pesapilot}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SCHEMA_FILE="$PROJECT_ROOT/schema/init_db.sql"

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
        sudo -u postgres psql -v ON_ERROR_STOP=0 "$@"
    else
        psql -v ON_ERROR_STOP=0 "$@"
    fi
}

run_psql <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$PGSQL_USER') THEN
        CREATE ROLE $PGSQL_USER WITH LOGIN PASSWORD '$PGSQL_PASSWORD';
    END IF;
END
\$\$;
SQL

DB_EXISTS="$(run_psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$PGSQL_DB'")"
if [ "$DB_EXISTS" != "1" ]; then
    run_psql -c "CREATE DATABASE $PGSQL_DB OWNER $PGSQL_USER;"
fi

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
echo "Add this to your .env:"
echo
echo "  POSTGRES_USER=$PGSQL_USER"
echo "  POSTGRES_PASSWORD=$PGSQL_PASSWORD"
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
