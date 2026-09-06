# PesaPilot

AI-powered M-Pesa financial assistant for Kenya. Parses your SMS transaction backup, stores it in a self-hosted PostgreSQL database, and lets you explore your spending — and get real Kenyan financial advice — through a Streamlit dashboard or by texting it on WhatsApp.

![PesaPilot WhatsApp Bot Demo](assets/whatsapp.gif)

---

## Features

* **Dashboard** — spending overview, daily trend, category breakdown, top merchants, heatmap, histogram, and AI-generated insights

  ![Dashboard overview](assets/1.png)
  ![Spending heatmap](assets/2.png)

* **Forecast** — Prophet-powered 7-day and 30-day spending projections with confidence band, trend classification (Increasing / Decreasing / Stable), risk level (Low / Moderate / High), and a Groq plain-English summary

* **Ask AI** — ask questions in plain English; Groq turns them into SQL, runs it, and explains the result grounded in your actual numbers

* **Budget plans** — ask for a "budget plan" and get a KES-denominated needs/wants/savings split sized to your real spending

* **Investment guidance** — ask "what should I invest in?" and get a Sacco / MMF / T-Bill recommendation sized to your actual free cash flow

* **Transactions** — filterable, searchable transaction history

* **Smarter anomaly detection** — ML-based per-user patterns instead of z-score

* **Budget goals with alerts** — proactive WhatsApp pings near/over budget

* **WhatsApp Bot** — ask the same questions, get charts, get budget/investment advice, and log SMS manually, all from WhatsApp

* **Daily summary** — a 9 PM scheduled job (Africa/Nairobi) sends an end-of-day spending digest to your WhatsApp

* **Two-tier AI** — fast model (`openai/gpt-oss-20b`) for chat/insights, smarter model (`openai/gpt-oss-120b`) for SQL generation, result analysis, and budget/investment advice

* **SQL safety guard** — every LLM-generated SQL query is validated (`SELECT`-only, no stacked statements, no DDL/DML keywords) before it touches the database

* **Response caching** — in-memory TTL cache on all Groq calls, automatically invalidated whenever new transactions are inserted

* **Till, Paybill, and Pochi la Biashara aware** — merchant categorization and transaction typing understand all three business-payment methods (see [How M-Pesa fees, Till, Paybill, and Pochi la Biashara work](#how-m-pesa-fees-till-paybill-and-pochi-la-biashara-work) below)

> **Note:** loading SMS data has no CLI command or dashboard button in the current codebase — see [Set up PostgreSQL, schema, and data](#3-set-up-postgresql-schema-and-data) below for the one-off script that does it.

---

## WhatsApp Bot — Two Modes

PesaPilot ships with **two WhatsApp bot implementations**. They share the same FastAPI backend and self-hosted PostgreSQL database — only the WhatsApp connection layer differs.

|                  | `whatsapp_bot.js`                  | `whatsapp_bot.ts`         |
| ---------------- | ---------------------------------- | ------------------------- |
| **Library**      | whatsapp-web.js                    | Baileys                   |
| **Connection**   | Headless Google Chrome (Puppeteer) | Pure WebSocket            |
| **Use case**     | Local development                  | Docker / VPS (production) |
| **Memory**       | ~300–500 MB (Google Chrome)        | ~80–120 MB                |
| **Auth session** | `.wwebjs_auth/`                    | `.baileys_auth/`          |
| **npm script**   | `npm run dev:wwebjs`               | `npm run dev`             |
| **Docker**       | ❌ not used                         | ✅ default                 |

> **Rule of thumb:** use `whatsapp_bot.js` when developing locally on your own machine. Use `whatsapp_bot.ts` (Baileys) for everything deployed — Docker, VPS, Railway, Raspberry Pi, any server. Baileys' low memory footprint (~80–120 MB, no Chromium) makes it well-suited to a Raspberry Pi (3B+ or newer recommended) running the Dockerized setup, giving you an always-on bot without paying for a VPS.

---

## Prerequisites

* Python 3.10+
* Node.js 20+ (`package.json` requires `>=20.0.0`)
* A self-hosted PostgreSQL server — **always installed and run on its own, directly on the host or a separate machine, never inside a Docker or Podman container.** Both `docker-compose.yml` and `podman/compose.yml` expect Postgres to already be running outside the container and only connect to it over the network. `scripts/setup_db.sh` automates that standalone install for you (see [Set up PostgreSQL, schema, and data](#3-set-up-postgresql-schema-and-data))
* A [Groq](https://console.groq.com) API key (free tier works)
* Docker + Docker Compose, or Podman + podman-compose, for VPS/production deployment (the app container only — not the database)
* A spare WhatsApp-capable SIM to run the bot on (you message it from your main number)

---

## 1. Clone and install

```bash
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot

# Python
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Node.js
npm install
```

---

## 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values. **Never commit `.env`** — it is already in `.gitignore`.

### Required

| Variable       | Where to get it                                                            |
| -------------- | -------------------------------------------------------------------------- |
| `DATABASE_URL` | PostgreSQL DSN, e.g. `postgresql://user:password@127.0.0.1:5432/pesapilot` — produced for you at the end of `scripts/setup_db.sh` |
| `GROQ_API_KEY` | `console.groq.com` → API Keys                                              |

### Optional

| Variable                    | Default                     | Purpose                                                                                                                                                                    |
| --------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WHATSAPP_MAIN_NUMBER`      | —                           | Your main number e.g. `254712345678` (country code, no `+`) — the number you text the bot from                                                                             |
| `WHATSAPP_PIN`              | —                           | Any 4-digit number you choose e.g. `1234` — used for manual SMS entry                                                                                                      |
| `WHATSAPP_LID`              | —                           | WhatsApp sometimes routes your number through an internal LID. Run the bot once, send a message, copy the value printed next to `From:` in the terminal, and paste it here |
| `API_URL`                   | `http://127.0.0.1:8000`     | Where the bot looks for the FastAPI service                                                                                                                                |
| `WHATSAPP_API_PORT`         | `8000`                      | Port FastAPI listens on                                                                                                                                                    |
| `LLM_MODEL_FAST`            | `openai/gpt-oss-20b`        | Groq model used for chat and dashboard insights (speed-sensitive)                                                                                                          |
| `LLM_MODEL_SMART`           | `openai/gpt-oss-120b`       | Groq model used for SQL generation, result analysis, and budget/investment advice (accuracy-sensitive)                                                                     |
| `LLM_MODEL`                 | —                           | Legacy/back-compat: if set, overrides `LLM_MODEL_FAST`                                                                                                                     |
| `LLM_TEMPERATURE`           | `0.6`                       | Groq sampling temperature                                                                                                                                                  |
| `LLM_MAX_TOKENS`            | `1536`                      | Max tokens per Groq response (the reasoning pass shares this budget with the visible answer)                                                                              |
| `NODE_ENV`                  | `production`                | Node runtime mode                                                                                                                                                          |
| `NODE_OPTIONS`              | `--max-old-space-size=2048` | Node heap size cap                                                                                                                                                         |
| `TZ`                        | `Africa/Nairobi`            | Timezone — affects log timestamps and the 9 PM daily-summary cron                                                                                                          |
| `WHATSAPP_USE_PAIRING_CODE` | `false`                     | Use a pairing code instead of a QR code to link the Baileys bot                                                                                                            |
| `BAILEYS_AUTH_PATH`         | `./.baileys_auth`           | Where Baileys session files are written                                                                                                                                    |
| `BAILEYS_LOG_LEVEL`         | `info`                      | Baileys/pino log verbosity                                                                                                                                                 |
| `WWEBJS_AUTH_PATH`          | `./.wwebjs_auth`            | Where whatsapp-web.js session files are written                                                                                                                            |

`.env.example` also lists `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (read by `scripts/setup_db.sh` to name the standalone role/database — override them there if you don't want the `pesapilot`/`pesapilot` defaults), plus `APP_ENV`, `DEBUG`, `SECRET_KEY`, `LOG_LEVEL`, `DB_MAX_CONNECTIONS`, `DB_CONNECTION_TIMEOUT`, `CACHE_TTL`, and `API_TIMEOUT`, which are placeholders for future use and not currently read anywhere in the app.

---

## 3. Set up PostgreSQL, schema, and data

PostgreSQL is **always installed and run standalone** — directly on your VPS, laptop, or a separate database server. It is never started by Docker Compose or Podman Compose; neither `docker-compose.yml` nor `podman/compose.yml` define a database service, both only ever *connect* to one over the network via `DATABASE_URL`. Set up Postgres and load your data before you start Docker, Podman, or the local app.

### Option A — automated (recommended)

```bash
chmod +x scripts/setup_db.sh
./scripts/setup_db.sh
```

This installs PostgreSQL via your system's package manager if it isn't already installed (apt/dnf/yum/brew), starts the service, creates the `pesapilot` role and database, and applies `schema/init_db.sql`. It's idempotent — safe to re-run. At the end it prints the exact `DATABASE_URL` to paste into your `.env`, including the right host to use if the app itself runs in Docker (`host.docker.internal`) or Podman (`host.containers.internal`).

Override the defaults with environment variables if you want different credentials:

```bash
PGSQL_USER=pesapilot PGSQL_PASSWORD=your-own-password PGSQL_DB=pesapilot ./scripts/setup_db.sh
```

### Option B — manual

Install PostgreSQL yourself, then:

```bash
sudo -u postgres psql
```

```sql
CREATE USER pesapilot WITH PASSWORD 'pesapilot';
CREATE DATABASE pesapilot OWNER pesapilot;
\q
```

If the user or database already exists, keep them and continue without running the failing `CREATE` command again.

Apply the schema:

```bash
psql "postgresql://pesapilot:pesapilot@127.0.0.1:5432/pesapilot" -f schema/init_db.sql
```

Verify that the tables exist:

```bash
psql "postgresql://pesapilot:pesapilot@127.0.0.1:5432/pesapilot" -c "\dt"
```

### Allowing container access (Docker/Podman only)

If the app itself will run inside Docker or Podman while Postgres runs on the host, Postgres needs to accept connections from the container's network:

* In `postgresql.conf`, set `listen_addresses = '*'` (or at least the host's private/bridge IP).
* In `pg_hba.conf`, add a line allowing the container subnet, e.g. `host all all 172.16.0.0/12 md5` for Docker's default bridge range, or `host all all 10.88.0.0/16 md5` for Podman's default range.
* Restart PostgreSQL after editing either file: `sudo systemctl restart postgresql`.

If you're running everything on bare metal with no containers at all, none of this is needed — `127.0.0.1` just works.

### Load your M-Pesa data

1. Install **SMS Backup & Restore** on the phone with your M-Pesa SMS history.
2. Choose **Back Up** → select **SMS only** → save to phone storage or Google Drive.
3. Transfer the XML file to your computer.
4. Place it in `data/raw/`.
5. Replace the filename below with your actual XML filename:

```bash
python -c "from src.analyzer import MpesaAnalyzer; count = MpesaAnalyzer().load_transactions('data/raw/your-sms-backup.xml', 'data/processed/mpesa_transactions.csv'); print(f'Loaded {count} transactions')"
```

For Docker, run the same import inside the running application container (Postgres itself is not in the container, so this only touches the app side):

```bash
docker compose exec pesapilot python -c "from src.analyzer import MpesaAnalyzer; count = MpesaAnalyzer().load_transactions('data/raw/your-sms-backup.xml', 'data/processed/mpesa_transactions.csv'); print(f'Loaded {count} transactions')"
```

The command saves a cleaned CSV and upserts transactions into PostgreSQL. Re-running it is safe because records are upserted by `transaction_id`.

Verify that data was loaded:

```bash
psql "postgresql://pesapilot:pesapilot@127.0.0.1:5432/pesapilot" -c "SELECT COUNT(*) FROM transactions;"
```

The count should be greater than zero when the XML contains valid M-Pesa messages.

---

## 4. Run the application

### Both services together

```bash
python run.py
```

Starts the FastAPI backend (port 8000) and the Streamlit dashboard (port 8501) together, and shuts both down cleanly on Ctrl+C. This does **not** start the WhatsApp bot — that's always a separate process (see below).

### Dashboard only

```bash
streamlit run dashboard/app.py
```

Open http://localhost:8501.

### API + WhatsApp bot (whatsapp-web.js — local dev)

Open two terminals:

```bash
# Terminal 1 — FastAPI backend
npm run api

# (equivalent to: uvicorn whatsapp.whatsapp_api:app --host 0.0.0.0 --port 8000 --reload)

# Terminal 2 — WhatsApp bot (whatsapp-web.js + Google Chrome)
npm run dev:wwebjs
```

A QR code prints in Terminal 2 on first run. Scan it:

**WhatsApp → Settings → Linked Devices → Link a Device**

Session is saved under `.wwebjs_auth/` — no rescan on normal restarts.

### API + WhatsApp bot (Baileys TypeScript — also works locally)

```bash
# Terminal 1 — FastAPI backend
npm run api

# Terminal 2 — WhatsApp bot (Baileys, no Chromium)
npm run dev
```

Session is saved under `.baileys_auth/`.

The Streamlit dashboard is for local use only and is not included in the Docker image.

---

## npm scripts

```bash
npm run api          # FastAPI backend with auto-reload (uvicorn --reload)
npm run dev          # Baileys bot via ts-node (auto-restart on save)
npm run dev:wwebjs   # whatsapp-web.js bot via nodemon
npm run build        # Compile whatsapp_bot.ts → dist/whatsapp_bot.js (auto-cleans dist/ first, writes dist/package.json)
npm start             # Run compiled Baileys bot: node dist/whatsapp_bot.js
npm run start:wwebjs  # Run whatsapp-web.js bot: node whatsapp/whatsapp_bot.js
npm run clean         # Remove dist/ only — safe, does not touch your live WhatsApp session
npm run clean:all     # Remove dist/ AND both auth session folders — forces a QR rescan, use deliberately
```

> **Why two clean scripts?** `npm run build` used to run a `clean` step that also deleted `.baileys_auth/`/`.wwebjs_auth/`, so every rebuild on a live server silently logged the bot out of WhatsApp and forced a new QR scan. `build` now only ever clears `dist/`. If you actually want to wipe a session (e.g. switching WhatsApp numbers), run `npm run clean:all` yourself.

> **Why `postbuild` writes `dist/package.json`?** `tsconfig.json` compiles `whatsapp_bot.ts` to ES modules, but `whatsapp_bot.js` (the whatsapp-web.js variant, used for local dev) is plain CommonJS and would break if the root `package.json` declared `"type": "module"`. Instead, `postbuild` drops a tiny `{"type":"module"}` file inside `dist/` so only the compiled Baileys output is treated as ESM, and `whatsapp_bot.js` keeps working unmodified.

---

## CLI reference

`run.py` takes no subcommands — it starts both the FastAPI backend and the Streamlit dashboard and blocks until you Ctrl+C:

```bash
python run.py
```

There is no `setup`, `load`, `ask`, or `dashboard` subcommand. For loading data, see [Set up PostgreSQL, schema, and data](#3-set-up-postgresql-schema-and-data) above.

For a connection check:

```bash
python -c "from src.database import PostgresDB; PostgresDB()"
```

This will raise if `DATABASE_URL` is missing or wrong.

---

## The Forecast page

Uses [Meta Prophet](https://facebook.github.io/prophet/) to project daily spending forward 7 or 30 days.

![Forecast view](assets/3.png)

**Minimum data required:** 14 days of spending history.

### How it works

1. Pulls up to 180 days of debit transactions from PostgreSQL
2. Aggregates into a daily series (zero-filled for no-spend days)
3. Prophet fits a linear-growth model with weekly seasonality
4. The result is cached in memory (6-hour TTL, invalidated on new inserts)
5. Groq writes a plain-English insight framing the projection as a prediction, not a fact

**Trend classification:** Increasing / Decreasing / Stable based on a ±7% difference between the first and second half of the forecast horizon.

**Risk level:** High (>25% above historical pace or volatility >0.9) / Moderate (10–25% or 0.6–0.9) / Low (everything else).

---

## What you can ask the bot

![Ask AI view](assets/4.png)

| You send                                                                    | What happens                                              |
| --------------------------------------------------------------------------- | --------------------------------------------------------- |
| `bar chart` / `pie chart` / `trend` / `heatmap` / `merchants` / `histogram` | Chart rendered and sent as an image                       |
| `What did I spend on food?`                                                 | Plain-English answer with KES + % breakdown               |
| `Give me a budget plan`                                                     | Needs/wants/savings split in KES, one category to trim    |
| `What should I invest in?`                                                  | Sacco / MMF / T-Bill recommendation sized to your surplus |
| `forecast` / `forecast 30 days`                                             | Spending forecast with trend, risk level, and AI summary  |
| `Summary` / `Daily summary` / `Today`                                       | Period or daily financial digest                          |
| `help`                                                                      | Full command list                                         |
| `1234-MJ7XK2P9 Confirmed. You have sent...`                                 | Manual SMS: `PIN-PASTE_SMS_HERE`                          |

Anyone texting the bot's WhatsApp number who isn't `WHATSAPP_MAIN_NUMBER` / `WHATSAPP_LID` is simply left alone — the bot does not reply or react, so the message sits as a normal WhatsApp chat for you to answer manually from your phone.

Only messages from `WHATSAPP_MAIN_NUMBER` (or `WHATSAPP_LID`) trigger the bot's AI/analytics replies.

---

## How M-Pesa fees, Till, Paybill, and Pochi la Biashara work

PesaPilot doesn't invent or hardcode any fee logic — it reads whatever amount Safaricom already printed in the SMS ("Transaction cost, Ksh X.XX") and stores it in `transaction_cost`. This section explains the real-world M-Pesa behavior behind those numbers, so the figures in your dashboard make sense.

### The general rule Safaricom applies

* **Sending money to another person (P2P), buying goods at a Till, and paying via Pochi la Biashara** are all **free for amounts up to and including KES 100.** Above that, Safaricom's published P2P/Till tariff applies and a fee shows up in the SMS.
* **Paybill payments** (bills, school fees, subscriptions, etc.) follow Safaricom's Paybill tariff, which usually charges a fee even on small amounts — this varies by biller and amount band.
* **Withdrawing cash** (agent or ATM) always carries a fee, at every amount, following Safaricom's withdrawal tariff.
* **Airtime purchases and most P2P sends under the free threshold** have no fee, which is why `transaction_cost` is legitimately `0.00` for a large share of your transactions — that's correct, not a bug.

Because this is Safaricom's tariff and not something PesaPilot decides, the exact fee for any given amount can change if Safaricom updates its pricing — always trust the number printed in your own SMS over any general rule stated here.

### How PesaPilot reads this from your SMS

`src/parse_sms.py` → `_extract_transaction_cost()` looks for a line matching `Transaction cost, Ksh...` in the SMS body:

* **Found →** that exact amount is stored in `transaction_cost`.
* **Not found →** `transaction_cost` is stored as `0.00` (never `NULL`), because plain P2P sends and airtime top-ups typically don't include a cost line at all. This keeps the column summable and chartable without any special-casing downstream.

### Till, Paybill, and Pochi la Biashara in categorization

`MpesaParser.MERCHANT_CATEGORIES['business']` recognizes all of the keywords a merchant-payment SMS typically contains: `till`, `lipa na mpesa`, `paybill`, `buy goods`, `pochi la biashara`, and `pochi`. Any transaction whose SMS body or recipient name contains one of these is categorized as `business` spending in the dashboard and AI analysis — regardless of which of the three payment rails (Till, Paybill, or Pochi la Biashara) was actually used.

`_determine_type()` separately classifies the transaction as `payment` (paid to a till/paybill/Pochi merchant), `withdrawal`, `transfer`, `airtime`, or `credit`/`debit`, based on the SMS wording — this is independent of the fee amount.

---

## Docker (VPS / Production)

> **The Docker image uses Baileys (`whatsapp_bot.ts`) exclusively.**
>
> Baileys connects to WhatsApp over a pure WebSocket — no Chromium, no Puppeteer, no browser needed. This is why the Docker image is lean (~80 MB Node footprint vs ~500 MB with Chromium).
>
> `whatsapp_bot.js` (whatsapp-web.js) is available for local development only and is never invoked inside the container.

**PostgreSQL is not part of this setup.** `docker-compose.yml` defines a single service — the app itself — and connects out to a PostgreSQL instance you already set up with `scripts/setup_db.sh` (see [Set up PostgreSQL, schema, and data](#3-set-up-postgresql-schema-and-data)). The container talks to it over `host.docker.internal`, which `docker-compose.yml` maps to the Docker host automatically (via `extra_hosts: host-gateway`, which also makes this work on Linux, not just Docker Desktop).

The container runs **both the FastAPI backend and the Baileys bot together** — no separate bot host needed.

### Build and run

```bash
docker compose up -d --build
docker compose logs -f pesapilot     # watch startup + QR code
```

The entrypoint validates `DATABASE_URL` (along with `GROQ_API_KEY`, `WHATSAPP_MAIN_NUMBER`, `WHATSAPP_PIN`) and actively test-connects to Postgres before starting anything — if the database isn't reachable, the container fails fast with a clear error instead of starting in a broken state.

Health check:

```text
http://YOUR_VPS_IP:8000/health
```

### What's persisted

`docker-compose.yml` uses bind mounts, not named volumes:

| Host path    | Container path       | Purpose                                               |
| ------------ | --------------------- | ----------------------------------------------------- |
| `./sessions` | `/app/.baileys_auth`  | Baileys session — survives restarts, no rescan needed |
| `./data`     | `/app/data`           | Raw/processed transaction files                       |

PostgreSQL's own data directory lives entirely on the host (wherever your OS/package manager put it, e.g. `/var/lib/postgresql/` on Debian/Ubuntu) — it's not part of this container at all, so back it up separately with `pg_dump` or your usual Postgres backup process:

```bash
pg_dump "postgresql://pesapilot:pesapilot@127.0.0.1:5432/pesapilot" > pesapilot-db-backup-$(date +%F).sql
```

Back up the app-side files with:

```bash
tar czf pesapilot-backup-$(date +%F).tar.gz ./sessions ./data
```

### Management

```bash
docker compose ps                        # status
docker compose logs -f pesapilot         # live logs
docker compose restart pesapilot         # restart (session persists)
docker compose down                      # stop and remove container
docker compose up -d --build             # rebuild after code change

# Force a new QR scan (wipes Baileys session)
docker compose exec pesapilot rm -rf /app/.baileys_auth
docker compose restart pesapilot
docker compose logs -f pesapilot
```

### Test the API

```bash
curl http://YOUR_VPS_IP:8000/health

curl -X POST http://YOUR_VPS_IP:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What did I spend on food?"}'

curl -X POST http://YOUR_VPS_IP:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Give me a budget plan"}'
```

---

## Podman (Local / Just for Fun)

> Not used for shipping. The files in `podman/` run the local **whatsapp-web.js** bot (Puppeteer/Google Chrome) under Podman — separate from `Dockerfile` / `docker-compose.yml`, which ship Baileys and stay the production path.

The Podman files live in `podman/` so the production Docker files can remain at the project root.

**Important:** Complete [Set up PostgreSQL, schema, and data](#3-set-up-postgresql-schema-and-data) first. As with Docker, Podman does not create PostgreSQL, run it, or apply the schema — it only connects to a standalone instance you already set up with `scripts/setup_db.sh`.

`podman/compose.yml` already points `DATABASE_URL` at `host.containers.internal` by default, which Podman resolves to the host automatically:

```env
DATABASE_URL=postgresql://pesapilot:pesapilot@host.containers.internal:5432/pesapilot
```

### Install

```bash
sudo dnf install podman podman-compose      # Fedora/RHEL
sudo apt install podman podman-compose      # Debian/Ubuntu
```

### Build and run

```bash
podman-compose -f podman/compose.yml up -d --build
podman-compose -f podman/compose.yml logs -f     # watch startup + QR code
```

Scan it:

**WhatsApp → Settings → Linked Devices → Link a Device**

Session is saved under `./sessions-local` — no rescan on normal restarts.

### Management

```bash
podman-compose -f podman/compose.yml ps                # status
podman-compose -f podman/compose.yml logs -f           # live logs
podman-compose -f podman/compose.yml restart           # restart (session persists)
podman-compose -f podman/compose.yml down              # stop and remove container
podman-compose -f podman/compose.yml up -d --build     # rebuild after code change

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

SELinux is enforced by default. The `:Z` suffix on the volume mounts (`./data:/app/data:Z`) tells Podman to relabel the bind-mounted folders so the container can read/write them — required on Fedora/RHEL, a harmless no-op on Debian/Ubuntu.

If you see permission-denied errors on `./data` or `./sessions-local` from inside the container, this is the first thing to check.

---

## Redeploying after a code change

`redeploy.sh` (in the project root) syncs your local changes to the VPS and rebuilds/restarts the Docker container in one step. It never touches PostgreSQL — that keeps running on the VPS the whole time, independent of the app container.

It doesn't hardcode any server details — you're prompted for them each run, so the script is safe to keep in a public/open-source repo.

### One-time setup

```bash
chmod +x redeploy.sh
```

### Usage

```bash
./redeploy.sh
```

You'll be prompted for:

* VPS username: `your-username`
* VPS host/IP: `your.vps.ip.address`
* Remote project path: press Enter to accept the default path (`~/PesaPilot`)

Then for your SSH password (may be asked more than once, since sync, rebuild, and status checks each open a separate SSH connection).

The script then:

1. **Syncs** your local project to the VPS via `rsync` (skipping `node_modules`, `venv`, `dist`, `podman/`, `.git`, `sessions`, `.baileys_auth`, `whatsapp-sessions`, logs, and caches)
2. **Rebuilds** the Docker image on the VPS (`docker compose up -d --build`), which recompiles the TypeScript bot and restarts the container
3. **Shows** the container status so you can confirm it came up healthy

### Flags

```bash
./redeploy.sh --no-build   # sync only, then restart without rebuilding (fast path for non-code changes)
./redeploy.sh --logs       # after deploying, tail the container logs so you can watch it come online
```

---

## How the AI advice is grounded

Every question sent to Groq is paired with live context pulled from PostgreSQL first:

* Summary stats (total spent, received, balance, transaction count)
* Top spending categories with KES amounts and percentages
* Top merchants/recipients
* Recent daily spending trend
* Detected anomalies

This sits under a Kenya-specific system prompt (`src/groq_client.py`) that enforces: show amounts and percentages, compare to averages, give one actionable tip, reference real Kenyan options (Sacco, MMF, Treasury Bills), recommend a budget split, nudge toward an emergency fund, celebrate small wins.

It never recommends Fuliza or names a specific bank.

### Two-tier model routing

| Model                                     | Used for                                                                      |
| ----------------------------------------- | ----------------------------------------------------------------------------- |
| `LLM_MODEL_FAST` (`openai/gpt-oss-20b`)   | `chat()`, `generate_insights()`, `generate_forecast_insights()`               |
| `LLM_MODEL_SMART` (`openai/gpt-oss-120b`) | `generate_sql()`, `analyze_results()`, `budget_plan()`, `investment_advice()` |

### SQL safety guard

All LLM-generated SQL is passed through `is_safe_select_sql()` before execution.

It must:

* Start with `SELECT`
* Contain no stacked statements (`;`)
* Contain none of `DROP / DELETE / UPDATE / INSERT / ALTER / TRUNCATE / GRANT / REVOKE / EXEC / EXECUTE / CREATE / ATTACH / REPLACE / MERGE / CALL`

Anything that fails is rejected and never reaches PostgreSQL.

### Response caching

Every Groq call is cached in-memory, keyed on a SHA-256 hash of `(system prompt, user prompt)`, with TTLs tuned per call type:

* **1 hour** for SQL generation
* **15 min** for budget/investment advice
* **10 min** for insights
* **5 min** for general chat

The cache is cleared automatically whenever a new transaction is inserted (`GroqClient.invalidate_cache()`).

---

## Testing

```bash
python -m pytest tests/ -v
```

53 tests across:

* `test_parser.py` — 17 tests
* `test_analyzer.py` — 10 tests
* `test_database.py` — 11 tests
* `test_forecasting.py` — 15 tests

> `test_analyzer.py` and `test_database.py` are **not mocked** — they call your real PostgreSQL database and Groq API key. `test_insert_and_retrieve` writes one row (`transaction_id = TEST0000001`) into your live `transactions` table. Don't run against a production database you care about being pristine.
>
> `test_parser.py` and `test_forecasting.py` are fully self-contained (synthetic data, no network calls) and safe to run anywhere.

---

## Troubleshooting

| Issue                                                           | Fix                                                                                                                       |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `❌ .env file not found!` (from `python run.py`)                 | Copy `.env.example` to `.env` in the project root before running                                                          |
| Container exits immediately with a missing-env-var error        | `DATABASE_URL`, `GROQ_API_KEY`, `WHATSAPP_MAIN_NUMBER`, and `WHATSAPP_PIN` are all required — the entrypoint refuses to start without them |
| Container exits with "Could not connect to DATABASE_URL"        | PostgreSQL isn't running, isn't reachable from the container network, or the credentials/host in `DATABASE_URL` are wrong — run `scripts/setup_db.sh` and check the pg_hba.conf note in [step 3](#allowing-container-access-dockerpodman-only) |
| Database connection errors (running locally, no containers)     | Verify PostgreSQL is running and that `DATABASE_URL` uses `127.0.0.1`                                                    |
| `ModuleNotFoundError: No module named 'src'`                    | Run commands from the project root, not from inside `src/` or `whatsapp/`                                                 |
| No transactions after loading XML                               | Confirm the file is an unmodified export from SMS Backup & Restore containing M-Pesa messages                             |
| Port 8000 already in use                                        | Set `WHATSAPP_API_PORT` to another port and update `API_URL` and `docker-compose.yml` to match                            |
| **Baileys:** `405 Connection Failure` loop, no QR shown         | The bot auto-fetches the latest WA Web protocol version on startup — if it still loops, wipe `.baileys_auth/` and restart |
| **Baileys:** QR never appears after wiping session              | Check internet connectivity from the container: `docker compose exec pesapilot curl -I https://web.whatsapp.com`          |
| **whatsapp-web.js:** `Failed to launch the browser process`     | Google Chrome is missing or `PUPPETEER_EXECUTABLE_PATH` is wrong — only relevant for local dev, not Docker                |
| **whatsapp-web.js:** `profile already in use` after a crash     | Delete `.wwebjs_auth/` once, restart, and rescan the QR                                                                   |
| **Podman:** permission denied on `./data` or `./sessions-local` | Fedora/RHEL SELinux — confirm the `:Z` suffix is present on the volume mounts in `podman/compose.yml`                     |
| WhatsApp session keeps logging out                              | Confirm the auth path (`./sessions` for Docker, `.baileys_auth/` locally) is not being wiped — `npm run build` no longer deletes it, only `npm run clean:all` does |
| Charts not sending                                              | Confirm `matplotlib` and `seaborn` are installed: `pip install matplotlib seaborn`                                        |
| Forecast shows "Not enough data"                                | You need at least 14 distinct days of debit transactions                                                                  |
| Forecast shows "forecasting engine unavailable"                 | `pip install prophet cmdstanpy`                                                                                           |
| Groq rate limit / empty AI responses                            | Wait ~60s and retry; lower `LLM_MAX_TOKENS` if it happens often                                                           |
| `streamlit: command not found`                                  | Activate your virtualenv: `source venv/bin/activate`                                                                      |
| `balance` column empty for some rows                            | Expected — not every M-Pesa SMS includes a balance figure                                                                 |
| A Till/Paybill/Pochi transaction shows `transaction_cost = 0`   | Expected for amounts at or under Safaricom's fee-free threshold (typically ≤ KES 100) — see [How M-Pesa fees, Till, Paybill, and Pochi la Biashara work](#how-m-pesa-fees-till-paybill-and-pochi-la-biashara-work) |
| `pytest` fails on PostgreSQL/Groq tests                         | Tests need real credentials and the schema from `schema/init_db.sql` already applied                                      |

---

## Future Improvements

* Multi-user support — currently hardcoded to one number/PostgreSQL database
* Other mobile money providers — Airtel Money, T-Kash via pluggable parsers
* Self-hosted/local LLM option — for privacy-conscious users
* CI/CD pipeline — automated tests + Docker builds via GitHub Actions
* Native mobile app — replaces local Streamlit dashboard
