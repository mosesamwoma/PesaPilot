#  PesaPilot

AI-powered M-Pesa financial assistant for Kenya. Analyzes your spending, provides insights, integrates with WhatsApp.

---

## Features

 **Dashboard** — spending overview, trends, categories, merchants, AI insights  
 **Ask AI** — natural language questions answered in seconds  
 **Transactions** — filterable history, all M-Pesa types  
 **Anomalies** — unusual spending detection  
 **Load Data** — auto-parse SMS backups, dedup, categorize  
 **WhatsApp Bot** — ask questions directly via WhatsApp  

---

## Quick Start (5 minutes)

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- [Supabase](https://supabase.com) (free)
- [Groq API](https://console.groq.com) (free)

### 2. Clone & Setup

```bash
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot

# Python
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Node.js
npm init -y
npm install whatsapp-web.js qrcode-terminal axios dotenv
```
### 4. Environment variables

now  set you KEYS into .env.example and set you own keys and rename the .env.example to .env

### 4. Database Setup

Go to [Supabase SQL Editor](https://supabase.com/dashboard) → paste `scripts/init_db.sql` → Run

### 5. Run

**Dashboard:**
```bash
streamlit run app.py
```

**WhatsApp Bot (Terminal 2):**
```bash
uvicorn whatsapp.whatsapp_api:app --port 8000 &
node whatsapp/whatsapp_bot.js
```

Open [http://localhost:8501](http://localhost:8501)

---
---

## Commands

### Python CLI

```bash
python run.py setup                    # Test DB connection
python run.py load data/raw/sms.xml    # Load data
python run.py ask "spending?"          # Ask question
python run.py dashboard                # Launch dashboard
```

### Node.js / WhatsApp

```bash
npm run whatsapp:api       # Start API on :8000
npm run whatsapp:bot       # Start bot (scan QR)
npm run whatsapp:start     # Both at once
```

### Tests

```bash
python -m pytest tests/ -v
```

---

## Docker

### Local Development

```bash
cd docker
docker-compose build
docker-compose up -d
docker-compose logs -f
```

Access:
- Dashboard: [http://localhost:8501](http://localhost:8501)
- API: [http://localhost:8000/health](http://localhost:8000/health)

Stop:
```bash
docker-compose down
```

### Production Build

```bash
docker build -t pesapilot .
docker run -p 8501:8501 -p 8000:8000 --env-file .env pesapilot
```

---

## WhatsApp Bot Setup

### Local Testing

**Terminal 1 — API:**
```bash
source venv/bin/activate
uvicorn whatsapp.whatsapp_api:app --port 8000
```

**Terminal 2 — Bot:**
```bash
node whatsapp/whatsapp_bot.js
```

When QR code appears:
1. Open WhatsApp on your **Airtel phone**
2. Settings → Linked Devices → Link a Device
3. Scan QR code
4. Send message from **main Safaricom number**

### Example Messages
What did I spend on food?
Summary all time
Summary 180 days
Help

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | Streamlit |
| Backend | Python 3.10+, FastAPI |
| Bot | Node.js 18+, whatsapp-web.js |
| Database | Supabase (PostgreSQL) |
| LLM | Groq (Llama 3.3-70b) |
| Deployment | Docker, Fly.io, Render, Oracle Cloud |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `SUPABASE_URL not set` | Check `.env` exists in root |
| `run_query not found` | Run `scripts/init_db.sql` in Supabase |
| `ModuleNotFoundError: src` | Run from project root |
| Port 8000 in use | Change in `.env`: `WHATSAPP_API_PORT=8001` |
| WhatsApp QR timeout | Increase `protocolTimeout` in `whatsapp_bot.js` |
| Groq rate limit | Wait 60s, reduce request frequency |

---
