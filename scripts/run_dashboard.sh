#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f /.dockerenv ] || [ -f /run/.containerenv ]; then
  echo "Refusing to start: the dashboard must never run inside a container." >&2
  exit 1
fi
if [ -n "${SSH_CONNECTION:-}" ] && [ "${PESAPILOT_ALLOW_DASHBOARD_OVER_SSH:-}" != "1" ]; then
  echo "Refusing to start: this looks like an SSH session on a server." >&2
  echo "Run the dashboard on your own computer and reach the database through a tunnel:" >&2
  echo "  ssh -L 5432:127.0.0.1:5432 user@your-server   (then set POSTGRES_HOST=localhost)" >&2
  exit 1
fi

if [ -x "$PROJECT_ROOT/venv/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/venv/bin/python"
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

if ! "$PYTHON" -c "import streamlit" >/dev/null 2>&1; then
  echo "Streamlit is not installed. Run: pip install -r requirements-dashboard.txt" >&2
  exit 1
fi

PORT="${DASHBOARD_PORT:-8501}"
case "$PORT" in
  ''|*[!0-9]*) echo "DASHBOARD_PORT must be a number" >&2; exit 1 ;;
esac

if ! grep -qE '^DASHBOARD_PASSWORD=.+' "$PROJECT_ROOT/.env" 2>/dev/null; then
  echo "Note: DASHBOARD_PASSWORD is not set in .env. The dashboard will only answer on localhost." >&2
fi

exec "$PYTHON" -m streamlit run dashboard/app.py \
  --server.address 127.0.0.1 \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false
