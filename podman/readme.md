## Podman (Local / Just for Fun)

> Not used for shipping. The files in `podman/` run the local **whatsapp-web.js** bot (Puppeteer/Google Chrome) under Podman — separate from `Dockerfile` / `docker-compose.yml`, which ship Baileys and stay the production path.

The Podman files live in `podman/` so the production Docker files can remain at the project root.

### Install

```bash
sudo dnf install podman podman-compose      # Fedora/RHEL
sudo apt install podman podman-compose      # Debian/Ubuntu
```

### Build and run

```bash
podman-compose -f podman/compose.yml up -d --build
podman-compose -f podman/compose.yml logs -f          # watch startup + QR code
```

Scan it: **WhatsApp → Settings → Linked Devices → Link a Device**. Session is saved under `./sessions-local` — no rescan on normal restarts.

### Management

```bash
podman-compose -f podman/compose.yml ps                 # status
podman-compose -f podman/compose.yml logs -f            # live logs
podman-compose -f podman/compose.yml restart            # restart (session persists)
podman-compose -f podman/compose.yml down                # stop and remove container
podman-compose -f podman/compose.yml up -d --build       # rebuild after code change

# Force a new QR scan (wipes the local session)
podman-compose -f podman/compose.yml exec pesapilot rm -rf /app/.wwebjs_auth
podman-compose -f podman/compose.yml restart
podman-compose -f podman/compose.yml logs -f
```

### Bare `podman` commands (no compose file)

```bash
# Build
podman build --ignorefile podman/.containerignore -f podman/Containerfile -t pesapilot .

# Run
podman run -d \
  --name pesapilot \
  --env-file .env \
  -e PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable \
  -v ./sessions-local:/app/.wwebjs_auth:Z \
  -v ./data:/app/data:Z \
  --shm-size=1g \
  -p 8000:8000 \
  pesapilot

# Everyday commands
podman logs -f pesapilot
podman stop pesapilot
podman start pesapilot
podman restart pesapilot
podman rm pesapilot
podman ps
```

### Fedora/RHEL note

SELinux is enforced by default. The `:Z` suffix on the volume mounts (`./data:/app/data:Z`) tells Podman to relabel the bind-mounted folders so the container can read/write them — required on Fedora/RHEL, a harmless no-op on Debian/Ubuntu. If you see permission-denied errors on `./data` or `./sessions-local` from inside the container, this is the first thing to check.