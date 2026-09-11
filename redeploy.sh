#!/usr/bin/env bash
set -euo pipefail

LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

read -rp "VPS username: " VPS_USER
read -rp "VPS host/IP: " VPS_HOST
read -rp "Remote project path [default: ~/PesaPilot]: " VPS_PATH_INPUT
VPS_PATH="${VPS_PATH_INPUT:-~/PesaPilot}"

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

echo "==> Syncing files..."
rsync -avz --progress \
  --exclude 'node_modules' \
  --exclude 'venv' \
  --exclude 'dist' \
  --exclude 'podman/' \
  --exclude 'assets' \
  --exclude '.git' \
  --exclude 'sessions' \
  --exclude '.baileys_auth' \
  --exclude '*.log' \
  --exclude '__pycache__' \
  --exclude '.wwebjs_auth' \
  --exclude '.wwebjs_cache' \
  "$LOCAL_PATH"/ "$VPS_USER@$VPS_HOST:$VPS_PATH/"

ssh "$VPS_USER@$VPS_HOST" "rm -rf $VPS_PATH/podman && rm -f $VPS_PATH/Containerfile $VPS_PATH/compose.yml $VPS_PATH/.containerignore"

if [ "$DO_BUILD" = true ]; then
  echo "==> Rebuilding and restarting container on VPS..."
  ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose up -d --build"
else
  echo "==> Restarting container on VPS (no rebuild)..."
  ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose restart"
fi

echo "==> Container status:"
ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose ps"

echo "==> Deploy complete."

if [ "$TAIL_LOGS" = true ]; then
  echo "==> Tailing logs (Ctrl+C to detach, container keeps running)..."
  ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PATH && docker compose logs -f"
fi