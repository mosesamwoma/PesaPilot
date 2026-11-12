#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
EXAMPLE="$ROOT/.env.example"
ROTATE=false
[ "${1:-}" = "--rotate" ] && ROTATE=true

command -v python3 >/dev/null 2>&1 || { echo "python3 is required"; exit 1; }
[ -f "$EXAMPLE" ] || { echo "Missing $EXAMPLE"; exit 1; }

if [ -f "$ENV_FILE" ] && [ "$ROTATE" = false ]; then
    echo ".env already exists. Use --rotate to replace its secrets, or delete it first."
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    ( umask 077 && cp "$EXAMPLE" "$ENV_FILE" )
fi

ENV_FILE="$ENV_FILE" python3 - <<'PY'
import os, re, secrets

path = os.environ["ENV_FILE"]
new = {
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "API_TOKEN": secrets.token_urlsafe(32),
    "WHATSAPP_PIN": f"{secrets.randbelow(10**6):06d}",
}
lines = open(path, encoding="utf-8").read().splitlines()
seen = set()
for i, line in enumerate(lines):
    m = re.match(r"^([A-Z_]+)=", line)
    if m and m.group(1) in new:
        lines[i] = f"{m.group(1)}={new[m.group(1)]}"
        seen.add(m.group(1))
for key in new.keys() - seen:
    lines.append(f"{key}={new[key]}")
fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_CREAT, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
os.chmod(path, 0o600)
PY

echo "Wrote $ENV_FILE (mode 600) with new POSTGRES_PASSWORD, API_TOKEN and WHATSAPP_PIN."
echo
echo "Next:"
echo "  1. Edit .env: set GROQ_API_KEY (new key from console.groq.com) and WHATSAPP_MAIN_NUMBER."
echo "  2. Apply the database password:  scripts/setup_db.sh"
echo "  3. Prepare folders (Docker):     scripts/prepare_dirs.sh"
echo "  4. If you rotated: unlink old WhatsApp linked devices on your phone and re-pair."
