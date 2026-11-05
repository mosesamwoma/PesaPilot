#!/usr/bin/env bash
# Prepares the bind-mounted folders for the non-root container user (UID/GID 10001).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

mkdir -p "$ROOT/sessions" "$ROOT/data/raw" "$ROOT/data/processed"

run() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }

run chown -R "$APP_UID:$APP_GID" "$ROOT/sessions" "$ROOT/data"
run chmod 700 "$ROOT/sessions"
run chmod 750 "$ROOT/data"
[ -f "$ROOT/.env" ] && chmod 600 "$ROOT/.env"

echo "sessions/ and data/ are now owned by $APP_UID:$APP_GID (sessions 700, data 750)."
echo "Note: to add SMS exports to data/raw/ later, use sudo, or run the import as root."
