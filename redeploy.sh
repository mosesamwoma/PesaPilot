#!/usr/bin/env bash
# redeploy.sh — sync PesaPilot to the VPS and rebuild the Docker container
#
# Requires: Docker, the deploy user, and docker-group access already set up
# on the VPS (see setup-vps.sh for the one-time bootstrap).
#
# Usage:
#   ./redeploy.sh            # sync + rebuild + restart
#   ./redeploy.sh --no-build # sync only, then just restart (fast path for non-Dockerfile changes)
#   ./redeploy.sh --logs     # after deploying, tail the logs
#
# You will be prompted for your VPS username, host/IP, and remote path
# every run. Nothing is hardcoded or stored in this file, so it's safe
# to publish/open-source as-is.
#
set -euo pipefail

LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # folder this script lives in

# ── Prompt for connection details ──────────────────────────────────────────
read -rp "VPS username: " VPS_USER
read -rp "VPS host/IP: " VPS_HOST
read -rp "Remote project path [default: ~/PesaPilot]: " VPS_PATH_INPUT
VPS_PATH="${VPS_PATH_INPUT:-~/PesaPilot}"

# ── Flags ─────────────────────────────────────────────────────────────────
DO_BUILD=true
TAIL_LOGS=false

for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=false ;;
    --logs)     TAIL_LOGS=true ;;
    *) echo "Unknown flag: $arg" && exit 1 ;;
  esac
done

echo "==> Deploying from $LOCAL_PATH to $VPS_USER@$VPS_HOST:$VPS_PATH"

# ── Step 1: sync code (skip stuff that gets rebuilt or is local junk) ──────
echo "==> Syncing files..."
rsync -avz --progress \
  --exclude 'node_modules' \
  --exclude 'venv' \
  --exclude 'dist' \
  --exclude '.git' \
  --exclude 'sessions' \
  --exclude '.baileys_auth' \
  --exclude 'whatsapp-sessions' \
  --exclude '*.log' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.wwebjs_cache' \
  "$LOCAL_PATH"/ "$VPS_USER@$VPS_HOST:$VPS_PATH/"

# ── Step 2: rebuild / restart on the VPS ───────────────────────────────────
if [ "$DO_BUILD" = true ]; then
  echo "==> Rebuilding and restarting container on VPS..."
  ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose up -d --build"
else
  echo "==> Restarting container on VPS (no rebuild)..."
  ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose restart"
fi

# ── Step 3: show status ─────────────────────────────────────────────────
echo "==> Container status:"
ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose ps"

echo "==> Deploy complete."

# ── Optional: tail logs ──────────────────────────────────────────────────
if [ "$TAIL_LOGS" = true ]; then
  echo "==> Tailing logs (Ctrl+C to detach, container keeps running)..."
  ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose logs -f"
fi