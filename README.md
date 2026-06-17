# 💸 PesaPilot

AI-powered M-Pesa financial assistant. Parses SMS backups, stores to Supabase, analyzes with Groq LLM.

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Create .env (fill in your keys)
cp .env.example .env

# 3. Run database setup in Supabase SQL Editor
# Copy entire contents of scripts/init_db.sql and run it
# https://supabase.com/dashboard → SQL Editor → Paste & Run

# 4. Load your M-Pesa SMS backup
python run.py load data/raw/your-backup.xml

# 5. Launch dashboard
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501)

## Environment Variables (.env)

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-publishable-key
GROQ_API_KEY=your-groq-api-key
LLM_MODEL=llama3-70b-8192
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=1000
APP_ENV=development
DEBUG=True
BATCH_SIZE=100
```

Get keys from:
- Supabase: https://supabase.com/dashboard → Settings → API
- Groq: https://console.groq.com → API Keys

## Features

- **📊 Dashboard** — spending overview, trends, categories, top merchants, AI insights
- **💬 Ask AI** — ask questions in plain English, get SQL + analysis
- **📋 Transactions** — filterable transaction history
- **⚠️ Anomalies** — unusual spending detection
- **📤 Load Data** — upload XML from browser or CLI, auto-sync to database

## CLI Commands

```bash
python run.py setup                    # Check DB connection
python run.py load <xml-path>          # Load M-Pesa data
python run.py ask "<question>"         # Ask from terminal
python run.py dashboard                # Launch Streamlit
```

## Run Tests

```bash
pip install pytest
pytest tests/ -v
```
## Deployment

### Streamlit Cloud (Free, Easiest)

1. Push to GitHub (`.env` in `.gitignore`)
2. Go to [https://share.streamlit.io](https://share.streamlit.io)
3. Click **New app** → select repo, set main file to `app.py`
4. Add environment variables in **Advanced settings**
5. Deploy

### Render (Free Web Service)

1. Connect GitHub repo to [https://render.com](https://render.com)
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
4. Add environment variables
5. Deploy

### Docker

```bash
docker build -t pesapilot .
docker run -p 8501:8501 --env-file .env pesapilot
```

## Free Tier Limits

- Supabase: 500MB storage, 2GB bandwidth/month ✅
- Groq: 30 req/min, 14,400 req/day ✅
- Render: 750 hours/month ✅
- Streamlit: 1 free app ✅

## Getting M-Pesa Backup

1. Download [SMS Backup & Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) on Android
2. Open → **Back Up** → select **SMS**
3. Save XML file, transfer to computer
4. Load via dashboard or CLI