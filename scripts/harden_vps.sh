#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'USAGE'
PesaPilot VPS security check and (optional) hardening for Ubuntu/Debian.

  sudo scripts/harden_vps.sh                 Audit only: reads settings, changes nothing.
  sudo scripts/harden_vps.sh --apply         Apply safe hardening (asks before each step):
                                             firewall, fail2ban, automatic security updates, .env permissions.
  sudo scripts/harden_vps.sh --apply --ssh   Also disable SSH password login (only if your key login works).
USAGE
}

APPLY=false
SSH_HARDEN=false
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=true ;;
    --ssh)   SSH_HARDEN=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
ISSUES=0

ok()   { echo "  ${GREEN}OK${NC}    $*"; }
warn() { echo "  ${YELLOW}WARN${NC}  $*"; ISSUES=$((ISSUES + 1)); }
bad()  { echo "  ${RED}RISK${NC}  $*"; ISSUES=$((ISSUES + 1)); }
confirm() {
  local answer
  read -r -p "  -> $1 [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]]
}

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo so every setting can be read: sudo $0 $*" >&2
  exit 1
fi

SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
SSH_PORT="${SSH_PORT:-22}"

echo "== 1. Network exposure =="
if command -v ss >/dev/null 2>&1; then
  while read -r proto addr; do
    port="${addr##*:}"
    host="${addr%:*}"
    case "$host" in
      127.*|'[::1]'|::1) continue ;;
    esac
    if [ "$port" = "$SSH_PORT" ] || [ "$port" = 80 ] || [ "$port" = 443 ]; then
      ok "$proto listening on $addr (expected)"
    elif [ "$port" = 5432 ]; then
      bad "PostgreSQL ($addr) listens on a non-loopback address. Bind it to localhost + the Docker bridge only (listen_addresses='localhost,172.17.0.1') and keep 5432 closed in the firewall."
    elif [ "$port" = 8000 ] || [ "$port" = 8011 ] || [ "$port" = 8501 ]; then
      bad "PesaPilot port $port is exposed on $addr. Keep it on 127.0.0.1 (API_BIND=127.0.0.1) and use a TLS reverse proxy or an SSH tunnel."
    else
      warn "$proto listening on $addr: make sure you intend this to be public."
    fi
  done < <(ss -H -ltn 2>/dev/null | awk '{print "tcp", $4}'; ss -H -lun 2>/dev/null | awk '{print "udp", $4}')
else
  warn "'ss' not found; install iproute2 to audit listening ports."
fi
if command -v docker >/dev/null 2>&1; then
  published="$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E '0\.0\.0\.0:|\[::\]:' || true)"
  if [ -n "$published" ]; then
    bad "Docker containers published on all interfaces (Docker bypasses ufw!):"
    echo "$published" | sed 's/^/        /'
  else
    ok "No Docker container is published on all interfaces."
  fi
fi

echo "== 1b. Dashboard must never be on a server =="
for leftover in dashboard .streamlit requirements-dashboard.txt scripts/run_dashboard.sh; do
  if [ -e "$PROJECT_ROOT/$leftover" ]; then
    warn "$leftover exists on this server. It is not part of the Docker image and is harmless unless started, but the dashboard is for your own computer only: delete it (rm -rf $PROJECT_ROOT/$leftover)."
  fi
done
if command -v pgrep >/dev/null 2>&1 && pgrep -f "streamlit" >/dev/null 2>&1; then
  bad "A Streamlit process is running on this server. Stop it (pkill -f streamlit)."
else
  ok "No Streamlit process is running."
fi

echo "== 2. Firewall =="
if command -v ufw >/dev/null 2>&1; then
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ok "ufw is active."
  else
    warn "ufw is installed but inactive."
  fi
else
  warn "ufw is not installed."
fi

echo "== 3. SSH =="
if command -v sshd >/dev/null 2>&1; then
  [ "$(sshd -T 2>/dev/null | awk '/^passwordauthentication /{print $2}')" = "no" ] \
    && ok "SSH password login is disabled." || warn "SSH password login is enabled (use keys; see --ssh)."
  root_login="$(sshd -T 2>/dev/null | awk '/^permitrootlogin /{print $2}')"
  case "$root_login" in
    no|prohibit-password|without-password) ok "Root SSH login: $root_login." ;;
    *) warn "Root SSH login is '$root_login'." ;;
  esac
else
  warn "sshd not found."
fi

echo "== 4. Brute-force protection and updates =="
systemctl is-active --quiet fail2ban 2>/dev/null && ok "fail2ban is running." || warn "fail2ban is not running."
if dpkg -s unattended-upgrades >/dev/null 2>&1; then ok "unattended-upgrades is installed."; else warn "Automatic security updates are not installed."; fi

echo "== 5. Secrets =="
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  mode="$(stat -c '%a' "$ENV_FILE")"
  [ "$mode" = "600" ] && ok ".env permissions are 600." || warn ".env permissions are $mode (should be 600)."
  grep -qE '^API_TOKEN=.{32,}' "$ENV_FILE" && ok "API_TOKEN looks strong." || bad "API_TOKEN is missing or shorter than 32 characters (run scripts/generate_secrets.sh)."
else
  warn "No .env file found at $ENV_FILE."
fi

echo
if [ "$APPLY" != true ]; then
  if [ "$ISSUES" -eq 0 ]; then
    echo "${GREEN}Audit finished with no findings.${NC}"
  else
    echo "${YELLOW}Audit finished with $ISSUES finding(s). Re-run with --apply to fix the safe ones.${NC}"
  fi
  exit 0
fi

echo "== Applying hardening (each step asks first) =="
export DEBIAN_FRONTEND=noninteractive

if confirm "Install and enable ufw (deny all incoming except SSH on port $SSH_PORT)?"; then
  apt-get install -y ufw >/dev/null
  ufw default deny incoming >/dev/null
  ufw default allow outgoing >/dev/null
  ufw allow "${SSH_PORT}/tcp" >/dev/null
  if confirm "Also allow web traffic on ports 80 and 443 (only if you run a reverse proxy)?"; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
  fi
  ufw --force enable >/dev/null
  echo "     ufw enabled. Reminder: published Docker ports bypass ufw, so keep API_BIND=127.0.0.1."
fi

if confirm "Install and enable fail2ban for SSH?"; then
  apt-get install -y fail2ban >/dev/null
  systemctl enable --now fail2ban >/dev/null 2>&1
  echo "     fail2ban running."
fi

if confirm "Install automatic security updates (unattended-upgrades)?"; then
  apt-get install -y unattended-upgrades >/dev/null
  printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades
  echo "     automatic security updates enabled."
fi

if [ -f "$ENV_FILE" ] && confirm "Set .env permissions to 600?"; then
  chmod 600 "$ENV_FILE"
fi

if [ "$SSH_HARDEN" = true ]; then
  login_user="${SUDO_USER:-root}"
  login_home="$(getent passwd "$login_user" | cut -d: -f6)"
  if [ ! -s "$login_home/.ssh/authorized_keys" ]; then
    echo "  ${RED}Skipping SSH hardening:${NC} $login_home/.ssh/authorized_keys is empty. Add your public key first, or you would lock yourself out."
  else
    echo "  Before continuing, open a SECOND terminal and confirm that you can log in with your SSH key."
    if confirm "Disable SSH password login and root password login now?"; then
      conf="/etc/ssh/sshd_config.d/99-pesapilot.conf"
      printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' > "$conf"
      if sshd -t; then
        systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null
        echo "     SSH hardened. Keep your current session open until you have tested a new login."
      else
        rm -f "$conf"
        echo "  ${RED}sshd rejected the new config; it was removed. Nothing changed.${NC}"
      fi
    fi
  fi
fi

echo
echo "Done. Run the script again without --apply to re-check."
