# PesaPilot

AI-powered M-Pesa financial assistant for Kenya. Analyzes your spending, provides insights, integrates with WhatsApp.

---

## Features

- **Dashboard** — spending overview, trends, categories, merchants, AI insights
- **Ask AI** — natural language questions answered in seconds
- **Transactions** — filterable history, all M-Pesa types
- **Anomalies** — unusual spending detection
- **Load Data** — auto-parse SMS backups, dedup, categorize
- **WhatsApp Bot** — ask questions directly via WhatsApp

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- [Supabase account](https://supabase.com) (free)
- [Groq API key](https://console.groq.com) (free)

### 2. Clone and Setup

```bash
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot

# Python
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Node.js
npm install whatsapp-web.js qrcode-terminal axios dotenv
```

### 3. Environment Variables

A `.env.example` file is included in the project. Open it, fill in your keys, and rename it to `.env` — that is all.

```bash
# Fill in your keys
nano .env.example

# Rename it
mv .env.example .env
```

Keys you must fill in:

| Key | Where to get it |
|-----|----------------|
| `SUPABASE_URL` | supabase.com/dashboard → Settings → API |
| `SUPABASE_KEY` | supabase.com/dashboard → Settings → API |
| `GROQ_API_KEY` | console.groq.com → API Keys |
| `WHATSAPP_MAIN_NUMBER` | Your main Safaricom number e.g. `254712345678` |
| `WHATSAPP_LID` | Run the bot, send a message, copy the ID printed next to `From:` in the terminal |

> Never commit `.env` to GitHub. It is already in `.gitignore`.

**Note on `WHATSAPP_MAIN_NUMBER`:** WhatsApp sometimes returns an internal LID instead of your phone number. Run the bot once, send any message from your main number, and check the terminal — it prints the exact sender ID. Copy that value into `.env` as `WHATSAPP_LID`.

### 4. Database Setup

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard)
2. Open your project → SQL Editor → New Query
3. Paste the contents of `scripts/init_db.sql`
4. Click **Run**
5. You should see: `PesaPilot DB ready`

### 5. Get Your M-Pesa Data

Install [SMS Backup & Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) from the Play Store.

1. Open the app
2. Tap **Back Up** → select **SMS** only
3. Save to phone storage or Google Drive
4. Transfer the XML file to your computer
5. Place the file in `data/raw/` inside the project folder

### 6. Load Your Data

```bash
python run.py load data/raw/your-sms-backup.xml
```

Re-loading is always safe — duplicates are ignored automatically.

### 7. Run

**Dashboard only:**
```bash
streamlit run app.py
```

**With WhatsApp bot (two terminals):**
```bash
# Terminal 1
uvicorn whatsapp.whatsapp_api:app --port 8000

# Terminal 2
node whatsapp/whatsapp_bot.js
```

Open [http://localhost:8501](http://localhost:8501)

---

## WhatsApp Bot Setup

The bot runs on your Airtel spare number. You message it from your main Safaricom number. All configuration is read from `.env` — no editing of the JS file needed.

### Step 1 — Set your numbers in .env

```env
# Your main Safaricom number — the number you send questions FROM
WHATSAPP_MAIN_NUMBER=254712345678

# Your WhatsApp LID — internal ID WhatsApp assigns to your number
WHATSAPP_LID=115831308570778
```

**Finding your LID:** Run the bot, send any message from your main number, and the terminal prints:

```
📱 From: 115831308570778
🔑 Allowed LID: 115831308570778
✅ Authorized via LID
```

Copy the value next to `From:` and paste it into `.env` as `WHATSAPP_LID`.

### Step 2 — Run locally

```bash
# Terminal 1 — Python API (Groq + Supabase)
source venv/bin/activate
uvicorn whatsapp.whatsapp_api:app --port 8000

# Terminal 2 — WhatsApp bot
node whatsapp/whatsapp_bot.js
```

### Step 3 — Scan QR code

```
╔════════════════════════════════════════════════════════╗
║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║
║  Go to: Settings → Linked Devices → Link a Device      ║
╚════════════════════════════════════════════════════════╝
```

Session is saved after first scan — no QR needed on future runs.

### Send messages from your main number

```
What did I spend on food this month?
Who did I send the most money to?
What is my biggest transaction?
Summary
Summary 180 days
Help
```

Anyone else who texts the Airtel number gets: `This number is not authorized.`

---

## Commands

### Python CLI

```bash
python run.py setup                        # Test DB connection
python run.py load data/raw/sms.xml       # Load SMS data
python run.py ask "what did I spend?"     # Ask a question
python run.py dashboard                    # Launch dashboard
```

### WhatsApp

```bash
npm run whatsapp:api      # Start Python API on :8000
npm run whatsapp:bot      # Start WhatsApp bot (shows QR on first run)
npm run whatsapp:start    # Start both at once
```

### Tests

```bash
python -m pytest tests/ -v
```

Expected: `39 passed`

---

## Docker

> Docker runs the **FastAPI backend only** — no Streamlit in production.
> The WhatsApp bot runs locally or on a server where the session can persist.

### Build and Run

```bash
# Build the image
docker-compose build

# Start services
docker-compose up -d

# Watch logs and QR code
docker-compose logs -f pesapilot
```

- API: [http://localhost:8000](http://localhost:8000)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

### Management Commands

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f pesapilot

# Stop
docker-compose down

# Restart (session persists)
docker-compose restart

# Rebuild from scratch
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Shell into container
docker-compose exec pesapilot bash

# View container health
docker inspect pesapilot | grep -A 10 "Health"
```

### Test the API

```bash
# Health check
curl http://localhost:8000/health

# Send a test question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What did I spend on food?"}'
```

### Persistent Volumes

| Volume | Purpose |
|--------|---------|
| `pesapilot_auth` | WhatsApp session — no re-scan after first time |
| `pesapilot_data` | Application data |

### Backup and Restore

```bash
# Backup WhatsApp session
docker run --rm -v pesapilot_auth:/source -v $(pwd):/backup alpine cp -r /source /backup/whatsapp_session_backup

# Restore WhatsApp session
docker run --rm -v pesapilot_auth:/dest -v $(pwd)/whatsapp_session_backup:/source alpine cp -r /source/* /dest/
```

### Production Deployment

```bash
# On your server
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot

# Copy your .env
scp user@local:/path/to/.env .env

# Build and run
docker-compose build
docker-compose up -d

# Verify
curl http://localhost:8000/health
```

### Docker Troubleshooting

| Issue | Fix |
|-------|-----|
| Container won't start | `docker-compose logs --tail=50 pesapilot` |
| QR code not showing | `docker-compose logs -f pesapilot` |
| Session lost | `docker volume ls \| grep pesapilot` |
| Port 8000 in use | Change port in `docker-compose.yml` |
| Build takes too long | Use cache — avoid `--no-cache` unless needed |
| Old container conflict | `docker rm -f pesapilot` then `docker-compose up -d` |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `SUPABASE_URL not set` | Check `.env` exists in project root |
| `run_query not found` | Run `scripts/init_db.sql` in Supabase SQL Editor |
| `ModuleNotFoundError: src` | Run all commands from the project root |
| `No M-Pesa transactions found` | Confirm XML is from SMS Backup & Restore app |
| Port 8000 in use | Set `WHATSAPP_API_PORT=8001` in `.env` |
| WhatsApp QR timeout | Increase `protocolTimeout` in `whatsapp_bot.js` |
| Groq rate limit | Wait 60 seconds, reduce request frequency |
| `streamlit: command not found` | Run `source venv/bin/activate` first |
| `balance` column all null | Normal — not all M-Pesa SMS include balance |

---