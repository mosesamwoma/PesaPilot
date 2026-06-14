# PesaPilot

> AI-powered M-Pesa financial assistant. Parses your SMS transaction history, stores it in the cloud, and gives you real-time spending insights powered by Groq AI.

---

## Features

- **Dashboard** — spending overview, daily trend chart, category breakdown, top merchants, and AI insights on every load
- **Ask AI** — ask questions in plain English; Groq converts them to SQL, runs the query, and explains the results
- **Transactions** — filterable table covering all M-Pesa types: payments, transfers, withdrawals, airtime, credits
- **Anomaly Detection** — Z-score based flagging of unusual transactions above your normal spend pattern
- **Load Data** — upload your XML backup from the browser; auto-parses 15+ SMS formats, deduplicates, and categorizes merchants automatically

---

## Prerequisites

- Python 3.10+
- [Supabase account](https://supabase.com) (free)
- [Groq account](https://console.groq.com) (free)
- [SMS Backup & Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) Android app to export your SMS
- Git

---

## Database Setup

**Do this once before anything else.**

1. Go to [https://supabase.com/dashboard](https://supabase.com/dashboard)
2. Open your project → click **SQL Editor** in the left sidebar
3. Click **New Query**
4. Paste the entire contents of `scripts/init_db.sql`
5. Click **Run** (or press `Ctrl+Enter`)
6. You should see at the bottom: `PesaPilot DB ready`

The script creates:
- `transactions` table with all required columns and indexes
- `run_query()` RPC function (lets Python run SELECT queries safely)
- `daily_summary` view
- `category_summary` view

---

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Open .env and fill in your keys (see below)

# 5. Verify DB setup
python run.py setup

# 6. Load your M-Pesa data
python run.py load data/raw/your-sms-backup.xml

# 7. Run the dashboard
streamlit run app.py
```

---

## Environment Variables

Create a `.env` file at the root of the project:

```env
# Supabase — get from: supabase.com/dashboard → Settings → API
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-publishable-anon-key

# Groq — get from: console.groq.com → API Keys
GROQ_API_KEY=your-groq-api-key

# LLM Config
LLM_MODEL=llama3-70b-8192
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=1000

# App
APP_ENV=development
DEBUG=True
SECRET_KEY=change-this-in-production
BATCH_SIZE=100
```

> Never commit `.env` to GitHub. It is already in `.gitignore`.

---

## Loading Your M-Pesa Data

### Step 1 — Export SMS from Android

1. Install [SMS Backup & Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) on your Android phone
2. Open the app → tap **Back Up** → select **SMS** only
3. Save to phone storage or Google Drive
4. Transfer the XML file to your computer

### Step 2 — Load into PesaPilot

**Option A — Via dashboard (recommended):**
1. Run `streamlit run app.py`
2. Go to **Load Data** in the sidebar
3. Upload your XML file directly, or enter the local file path
4. Click **Load** — it parses, deduplicates, and syncs to Supabase automatically

**Option B — Via CLI:**
```bash
python run.py load data/raw/sms-20260616115048.xml
```

**Option C — With CSV output:**
```bash
python run.py load data/raw/sms-backup.xml --csv data/processed/mpesa_transactions.csv
```

Re-syncing is always safe. Duplicate `transaction_id` values are ignored via `ON CONFLICT DO NOTHING` — no double entries, ever.

---

## Running the App

```bash
# Standard
streamlit run app.py

# Custom port
streamlit run app.py --server.port 8080

# Accessible on local network (e.g. open on your phone)
streamlit run app.py --server.address 0.0.0.0
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Running Tests

```bash
python -m pytest tests/ -v
```

Expected output:

```
39 passed
```

---

## CLI Reference

```bash
# Check Supabase connection and print setup instructions
python run.py setup

# Load an XML SMS backup into the database
python run.py load data/raw/sms-backup.xml
python run.py load data/raw/sms-backup.xml --csv data/processed/output.csv

# Ask a question from the terminal
python run.py ask "What did I spend on food this month?"
python run.py ask "Who did I send the most money to?"
python run.py ask "What is my biggest single transaction?"

# Launch the Streamlit dashboard
python run.py dashboard
python run.py dashboard --port 8080
```