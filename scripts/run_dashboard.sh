#!/usr/bin/env bash
# Start the Streamlit dashboard bound to 127.0.0.1 ONLY (never the public interface).
#   Local:   scripts/run_dashboard.sh   then open http://localhost:8501
#   Server:  ssh -L 8501:127.0.0.1:8501 user@your-server   then open http://localhost:8501 on your laptop
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -x "$PROJECT_ROOT/venv/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/venv/bin/python"
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

PORT="${DASHBOARD_PORT:-8501}"
case "$PORT" in
  ''|*[!0-9]*) echo "DASHBOARD_PORT must be a number" >&2; exit 1 ;;
esac

if ! grep -qE '^DASHBOARD_PASSWORD=.+' "$PROJECT_ROOT/.env" 2>/dev/null; then
  echo "Note: DASHBOARD_PASSWORD is not set in .env. The dashboard will only answer on localhost." >&2
fi

# The address is forced here as well as in .streamlit/config.toml so no environment can override it.
exec "$PYTHON" -m streamlit run dashboard/app.py \
  --server.address 127.0.0.1 \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false
