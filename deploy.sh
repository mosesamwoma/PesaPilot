#!/usr/bin/env bash
#
# deploy.sh — sync PesaPilot to the VPS and rebuild the Docker container
#
# Usage:
#   ./deploy.sh            # sync + rebuild + restart
#   ./deploy.sh --no-build # sync only, then just restart (fast path for non-Dockerfile changes)
#   ./deploy.sh --logs     # after deploying, tail the logs
#
set -euo pipefail

# ── Config — edit these if your setup changes ────────────────────────────
VPS_USER="mosesamwoma"
VPS_HOST="153.75.247.17"
VPS_PATH="~/PesaPilot"
LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # folder this script lives in

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