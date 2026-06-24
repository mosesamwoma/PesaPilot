# PesaPilot

AI-powered M-Pesa financial assistant for Kenya. It parses your SMS transaction backup, stores it in Supabase, and lets you explore your spending — and get real Kenyan financial advice — through a Streamlit dashboard or by just texting it on WhatsApp.

---

## Features

- **Dashboard** — spending overview, daily trend, category breakdown, top merchants, AI-generated insights
- **Ask AI** — ask questions about your spending in plain English; Groq turns them into SQL, runs it, and explains the result, grounded in your actual numbers (totals, % per category, top merchants, recent trend, anomalies)
- **Budget plans** — ask for a "budget plan" and get a KES-denominated needs/wants/savings split sized to your real spending, plus one specific category to trim
- **Investment guidance** — ask "what should I invest in?" and get a recommendation across Kenyan options (Sacco, Money Market Fund, Treasury Bills) sized to your actual free cash flow, with a suggested split and one concrete next step
- **Transactions** — filterable, searchable transaction history
- **Anomalies** — unusually large transactions flagged by z-score
- **Load Data** — parses SMS Backup & Restore XML exports, auto-categorizes, de-duplicates on reload
- **WhatsApp Bot** — ask the same questions, get charts, get budget/investment advice, and log SMS manually, all from WhatsApp
- **Daily summary** — a 9 PM scheduled job (Africa/Nairobi by default) sends an end-of-day spending digest to your WhatsApp

## Prerequisites

- Python 3.10+
- Node.js **20+** (the Dockerfile installs Node 20 LTS; `package.json` requires `>=20.0.0`)
- A [Supabase](https://supabase.com) project (free tier is fine)
- A [Groq](https://console.groq.com) API key (free tier is fine)
- Docker + Docker Compose, if you want to run it containerized
- A spare WhatsApp-capable number/SIM to run the bot on (you message it from your main number)

---

## 1. Clone and install

```bash
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot

# Python
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Node.js (for the WhatsApp bot)
npm install
```

## 2. Configure environment variables

```bash
cp .env.example .env
```

Then open `.env` and fill in the values below. **Never commit `.env`** — it's already in `.gitignore`.

### Required

The app refuses to start (both locally and in Docker) without these six:

| Variable | Where to get it |
|---|---|
| `SUPABASE_URL` | supabase.com/dashboard → Settings → API |
| `SUPABASE_KEY` | supabase.com/dashboard → Settings → API |
| `GROQ_API_KEY` | console.groq.com → API Keys |
| `WHATSAPP_MAIN_NUMBER` | Your main number, e.g. `254712345678` (country code, no `+`) — the number you'll text the bot **from** |
| `WHATSAPP_LID` | See "Finding your LID" below |
| `WHATSAPP_PIN` | Any 4-digit number you choose, e.g. `1234` — used for manual SMS entry |

**Finding your `WHATSAPP_LID`:** WhatsApp sometimes routes your number through an internal LID instead of the plain number. Run the bot once, send it any message from your main number, and the terminal prints the exact sender ID next to `From:`. Copy that into `.env` as `WHATSAPP_LID`.

### Optional (sensible defaults if omitted)

| Variable | Default | Purpose |
|---|---|---|
| `API_URL` | `http://127.0.0.1:8000` | Where the bot looks for the FastAPI service |
| `WHATSAPP_API_PORT` | `8000` | Port FastAPI listens on |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Groq model used for SQL generation, chat, budgets, and investment advice |
| `LLM_TEMPERATURE` | `0.6` | Groq sampling temperature — kept warmer than pure SQL-gen tasks so advice reads naturally |
| `LLM_MAX_TOKENS` | `600` | Max tokens per Groq response |
| `PUPPETEER_EXECUTABLE_PATH` | `/usr/bin/chromium` | Chromium binary the bot launches |
| `PUPPETEER_SKIP_CHROMIUM_DOWNLOAD` | `true` | Skips Puppeteer's own ~280MB Chromium download at install time (we use system Chromium instead) |
| `NODE_ENV` | `production` | Node runtime mode |
| `NODE_OPTIONS` | `--max-old-space-size=2048` | Node heap size cap |
| `PYTHONUNBUFFERED` | `1` | Streams Python logs immediately instead of buffering |
| `TZ` | `Africa/Nairobi` | Container timezone — affects log timestamps and the 7 AM daily-summary job |

## 3. Create the database schema

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard) → your project → **SQL Editor** → **New Query**
2. Paste the contents of `scripts/init_db.sql`
3. Click **Run**

You should see a single row back: `PesaPilot DB ready ✅`. This creates the `transactions` table, indexes, a `run_query(text)` RPC function (the only way the app is allowed to execute AI-generated SQL — it rejects anything that isn't a `SELECT`), and two read-only views (`daily_summary`, `category_summary`) you can query directly from the SQL editor if you want.

## 4. Get your M-Pesa data onto your computer

1. Install [SMS Backup & Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) on the phone with your M-Pesa SMS history
2. **Back Up** → select **SMS** only → save to phone storage or Google Drive
3. Transfer the resulting XML file to your computer
4. Place it in `data/raw/`

## 5. Load it

```bash
python run.py load data/raw/your-sms-backup.xml
```

Re-running this on the same or an updated file is always safe — transactions are upserted on `transaction_id`, so duplicates are silently skipped/updated rather than duplicated.

## 6. Run it

**Dashboard only:**

```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501).

**API + WhatsApp bot (two terminals):**

```bash
# Terminal 1 — FastAPI backend
uvicorn whatsapp.whatsapp_api:app --host 0.0.0.0 --port 8000

# Terminal 2 — WhatsApp bot
npm start
# (equivalent to: node whatsapp/whatsapp_bot.js)
```

A QR code prints in Terminal 2 the first time — scan it (see below). All three — dashboard, API, and bot — can run at once; they share the same Supabase database.

---

## WhatsApp bot setup

The bot logs into WhatsApp Web using **whatsapp-web.js** + a headless Chromium, ideally on a spare number, while you send it questions from your **main** number (`WHATSAPP_MAIN_NUMBER` / `WHATSAPP_LID`). Anyone who isn't that number gets a polite refusal.

### Scan the QR code

```
╔════════════════════════════════════════════════════════╗
║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║
║  Settings → Linked Devices → Link a Device              ║
╚════════════════════════════════════════════════════════╝
```

On the spare phone: **WhatsApp → Settings → Linked Devices → Link a Device**, then scan the ASCII QR code in the terminal. If the ASCII art doesn't scan cleanly (common over SSH/cloud log viewers), the bot also prints a fallback `https://api.qrserver.com/...` link that renders the same QR as an image you can open on the phone instead. The bot waits up to two minutes for a scan before regenerating.

Your session is saved under `.wwebjs_auth/` (Docker: the `sessions/` bind mount) — you won't be asked to scan again on normal restarts.

Anyone texting the bot's number who isn't `WHATSAPP_MAIN_NUMBER`/`WHATSAPP_LID` gets: *"⛔ This number is not authorized."*

### What you can ask it

| You send | What happens |
|---|---|
| `bar chart` / `pie chart` / `trend` / `heatmap` / `merchants` / `histogram` | Instant chart, rendered as an image |
| `What did I spend on food?` | Plain-English answer with KES + % breakdown, grounded in your real transactions |
| `Give me a budget plan` | A needs/wants/savings split in KES, one category to trim, where to park the savings bucket |
| `What should I invest in?` | A Sacco / Money Market Fund / Treasury Bill recommendation sized to your actual surplus, with a suggested split |
| `Summary` / `Daily summary` / `Today` | Period or daily financial digest |
| `help` | Full list of supported commands |
| `1234-MJ7XK2P9QD Confirmed. You have sent...` | Manual SMS entry: `PIN-PASTE_SMS_HERE` |

---

## CLI reference (`run.py`)

```bash
python run.py setup                          # Test the Supabase connection
python run.py load data/raw/sms-backup.xml    # Parse + load an SMS export
python run.py ask "what did I spend on rent?" # Ask a one-off question from the terminal
python run.py dashboard                       # Launch the Streamlit dashboard
```

## npm scripts

```bash
npm start    # node whatsapp/whatsapp_bot.js
npm run dev  # same, via nodemon (auto-restart on file changes; dev only)
```

---

## How the AI advice is grounded

Every question that reaches the AI — chat, budget plan, or investment advice — is paired with real context pulled live from Supabase before the prompt is sent to Groq:

- Summary stats (total spent, received, balance, transaction count)
- Top spending categories, with both KES amounts and percentages
- Top merchants/recipients
- Recent daily spending trend
- Any detected anomalies

This context sits underneath a Kenya-specific system prompt (in `src/groq_client.py`) that enforces seven rules on every response: show amounts *and* percentages, compare to averages, give one specific actionable tip, reference real Kenyan options (Sacco, MMF, Treasury Bills) where relevant, recommend a concrete budget split, nudge toward an emergency fund, and celebrate small wins. It never recommends Fuliza or names a specific bank or provider.

---

## Testing

```bash
python -m pytest tests/ -v
```

38 tests across `test_parser.py` (17), `test_analyzer.py` (10), and `test_database.py` (11).

> **Heads up:** unlike the parser tests, `test_analyzer.py` and `test_database.py` are **not mocked** — they call your real Supabase project and your real Groq API key, and `test_insert_and_retrieve` writes one row (`transaction_id = TEST0000001`) into your live `transactions` table. Don't point this at a production database you care about being pristine, and expect each full run to use a small amount of Groq quota.

---

## Docker

The container runs **both the FastAPI backend and the WhatsApp bot together** — there's no separate "bot host" needed. Streamlit isn't included in the image (it's a local/dev-only dashboard); only `src/`, `whatsapp/`, `run.py`, and `tests/` are copied in.

### Build and run

```bash
docker compose up -d --build
docker compose logs -f pesapilot     # watch startup + the QR code
```

- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

(`docker-compose` with a hyphen also works if you're on the older standalone CLI.)

> ⚠️ **Use `127.0.0.1`, not `localhost`, when shipping this.** Every default in the code — `.env.example`'s `API_URL`, the Docker healthcheck, `entrypoint.sh` — points at `http://127.0.0.1:8000`. On some hosts `localhost` resolves to the IPv6 loopback (`::1`) first, which fails to connect since the service only listens on IPv4. `localhost` is fine for a quick check in your own browser; for anything scripted, deployed, or shared with someone else, use `127.0.0.1` to match what's actually configured.

### What's persisted

`docker-compose.yml` bind-mounts two host folders, created next to the repo on first run:

| Host path | Container path | Purpose |
|---|---|---|
| `./sessions` | `/app/.wwebjs_auth` | WhatsApp session — keeps you logged in across restarts |
| `./data` | `/app/data` | Raw/processed transaction files |

Back them up like any other folder:

```bash
tar -czf pesapilot-backup-$(date +%F).tar.gz sessions/ data/
```

### Management

```bash
docker compose ps                          # status
docker compose logs -f pesapilot           # logs
docker compose restart                     # restart (session persists)
docker compose down                        # stop + remove container
docker compose up -d --build               # rebuild after a code change
docker compose exec pesapilot bash         # shell in
docker inspect pesapilot-bot --format '{{json .State.Health}}'   # health status
```

### Test the API

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What did I spend on food?"}'

curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Give me a budget plan"}'

curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What should I invest in?"}'
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `❌ Missing required environment variables` on startup | One of the six required vars (see above) is unset — check `.env` exists and is in the project root |
| `SUPABASE_URL and SUPABASE_KEY must be set` | Same as above, for direct Python runs outside Docker |
| `run_query not found` / RPC errors | You haven't run `scripts/init_db.sql` in the Supabase SQL Editor yet |
| `ModuleNotFoundError: No module named 'src'` | Run commands from the project root, not from inside `src/` or `whatsapp/` |
| No transactions after loading an XML | Confirm the file is an unmodified export from SMS Backup & Restore, and that it actually contains M-Pesa messages |
| Port 8000 already in use | Set `WHATSAPP_API_PORT` to something else, and update `API_URL` and the `docker-compose.yml` port mapping to match |
| WhatsApp QR never appears / hangs | Check `docker compose logs -f pesapilot`; confirm `chromium` is installed in the image (`docker compose exec pesapilot chromium --version`) |
| `Failed to launch the browser process` / `profile already in use` after a crash or forced container kill | `entrypoint.sh` clears the known Chrome lock files (`SingletonLock`, `SingletonSocket`, `SingletonCookie`, `SingletonTab`) on every boot. If it still happens after a *hard* crash (OOM kill, `docker kill`, power loss), stop the container and delete the `sessions/` folder (or the `.wwebjs_auth` volume) once, then restart and re-scan the QR code |
| WhatsApp session keeps getting logged out | Make sure `sessions/` (or your volume) is actually persisted between restarts — check it isn't being wiped by your deploy process |
| `WHATSAPP_PIN not set` | Add `WHATSAPP_PIN` to `.env` |
| Charts not sending / chart errors in logs | `pip install matplotlib seaborn` (already in `requirements.txt`, but confirm your venv has them) |
| "Budget plan" or "invest" questions get treated as a generic AI question instead of the dedicated handler | Check your phrasing includes one of the recognized keywords (e.g. "budget", "invest", "sacco", "MMF", "treasury bill") — see `BUDGET_KEYWORDS`/`INVEST_KEYWORDS` in `whatsapp/whatsapp_api.py` |
| Groq rate limit / empty AI responses | Wait ~60s and retry; consider lowering `LLM_MAX_TOKENS` |
| `streamlit: command not found` | Activate your virtualenv first: `source venv/bin/activate` |
| `balance` column is always empty for some rows | Expected — not every M-Pesa SMS includes a balance figure |
| `pytest` fails on Supabase/Groq tests | Those tests need real, working `SUPABASE_URL`/`SUPABASE_KEY`/`GROQ_API_KEY` and the schema from `scripts/init_db.sql` already applied — see the Testing section above |

---

## Future Improvements

- **Multi-user support** — currently hardcoded to one number/Supabase project.
- **Other mobile money providers** — Airtel Money, T-Kash via pluggable parsers.
- **Smarter anomaly detection** — ML-based, per-user patterns instead of z-score.
- **Budget goals with alerts** — proactive WhatsApp pings near/over budget.
- **Web-based onboarding** — guided setup instead of manual `.env`/SQL/XML steps.
- **Self-hosted/local LLM option** — for privacy-conscious users.
- **CI/CD pipeline** — automated tests + Docker builds via GitHub Actions.
- **Encryption at rest** — for stored SMS content.
- **Native mobile app** — replaces local Streamlit dashboard.

---