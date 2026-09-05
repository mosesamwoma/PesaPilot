-- ============================================================
-- Create the database schema (self-hosted PostgreSQL)
-- ============================================================
-- With Docker Compose (docker-compose.yml `db` service):
--   docker exec -i pesapilot-db psql -U pesapilot -d pesapilot < schema/init_db.sql
--
-- With a local/VPS PostgreSQL install:
--   psql "$DATABASE_URL" -f schema/init_db.sql
--
-- You should see: PesaPilot DB ready ✅
-- ============================================================

-- Needed for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ------------------------------------------------------------
-- MIGRATION (run this instead of the CREATE TABLE below if you
-- already have a `transactions` table from before transaction_cost
-- existed):
--
--   ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transaction_cost DECIMAL(12,2) NOT NULL DEFAULT 0;
--
-- Safe to run more than once. Existing rows backfill to 0 automatically
-- (DEFAULT 0 applies retroactively on ADD COLUMN). Re-import your SMS
-- Backup & Restore XML (or resend past SMS through the WhatsApp bot)
-- afterwards to get the REAL fee amounts in place of that 0 backfill.
-- ------------------------------------------------------------

-- ------------------------------------------------------------
-- 1. transactions
-- Core table. `id` is a UUID — the safe, unique identifier used
-- everywhere else (this is your "unique transaction ID").
-- `transaction_id` is the M-Pesa-provided code, used to prevent
-- the same SMS being inserted twice.
-- ------------------------------------------------------------
CREATE TABLE transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id TEXT UNIQUE NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    balance DECIMAL(12,2),
    transaction_cost DECIMAL(12,2) NOT NULL DEFAULT 0,
    type TEXT NOT NULL,
    recipient TEXT,
    merchant_category TEXT,
    phone TEXT,
    body TEXT,
    timestamp TIMESTAMP,
    readable_date TEXT,
    raw_date TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX idx_transactions_type ON transactions(type);
CREATE INDEX idx_transactions_amount ON transactions(amount);
CREATE INDEX idx_transactions_merchant ON transactions(merchant_category);
CREATE INDEX idx_transactions_recipient ON transactions(recipient);

-- ------------------------------------------------------------
-- 2. budgets
-- One row per category you want to set a spending limit on.
-- ------------------------------------------------------------
CREATE TABLE budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT 'monthly',
    limit_amount DECIMAL(12,2) NOT NULL,
    alert_threshold_pct INT NOT NULL DEFAULT 80,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(category, period)
);

CREATE INDEX idx_budgets_category ON budgets(category);

-- ------------------------------------------------------------
-- 3. budget_alerts
-- Log of alerts already sent, so the WhatsApp bot never pings
-- you twice for the same budget breach in the same period.
-- ------------------------------------------------------------
CREATE TABLE budget_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    alert_level TEXT NOT NULL,
    amount_spent DECIMAL(12,2) NOT NULL,
    sent_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(budget_id, period_start, alert_level)
);

CREATE INDEX idx_budget_alerts_budget ON budget_alerts(budget_id);

-- ------------------------------------------------------------
-- 4. spending_baselines
-- One row per merchant_category, holding stats used to judge
-- what's "normal" for THAT category specifically — this is what
-- makes anomaly detection personalized instead of one global
-- threshold across every kind of spending.
-- ------------------------------------------------------------
CREATE TABLE spending_baselines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_category TEXT NOT NULL UNIQUE,
    mean_amount DECIMAL(12,2),
    std_amount DECIMAL(12,2),
    median_amount DECIMAL(12,2),
    mad_amount DECIMAL(12,2),
    sample_size INT,
    computed_at TIMESTAMP DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 5. anomalies
-- Flagged unusual transactions, saved so they don't need to be
-- recalculated every time the dashboard loads.
-- ------------------------------------------------------------
CREATE TABLE anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID REFERENCES transactions(id) ON DELETE CASCADE,
    model TEXT NOT NULL DEFAULT 'category_mad',
    score DECIMAL(6,3),
    reviewed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(transaction_id, model)
);

CREATE INDEX idx_anomalies_tx ON anomalies(transaction_id);
CREATE INDEX idx_anomalies_model ON anomalies(model);

-- ------------------------------------------------------------
-- 6. run_query — lets the Python backend run SELECT-only queries
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION run_query(query TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result JSONB;
BEGIN
    IF UPPER(TRIM(query)) NOT LIKE 'SELECT%' THEN
        RAISE EXCEPTION 'Only SELECT queries are allowed';
    END IF;
    EXECUTE 'SELECT jsonb_agg(row_to_json(t)) FROM (' || query || ') t' INTO result;
    RETURN COALESCE(result, '[]'::JSONB);
END;
$$;

-- ------------------------------------------------------------
-- 7. daily_summary — spend/income totals per day
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW daily_summary AS
SELECT
    DATE(timestamp) as date,
    COUNT(*) as total_transactions,
    SUM(CASE WHEN type != 'credit' THEN amount ELSE 0 END) as total_spent,
    SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) as total_received,
    AVG(CASE WHEN type != 'credit' THEN amount ELSE NULL END) as avg_spend,
    COUNT(CASE WHEN type != 'credit' THEN 1 END) as debit_count,
    COUNT(CASE WHEN type = 'credit' THEN 1 END) as credit_count
FROM transactions
GROUP BY DATE(timestamp)
ORDER BY date DESC;

-- ------------------------------------------------------------
-- 8. category_summary — spend/income totals per category
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW category_summary AS
SELECT
    merchant_category,
    COUNT(*) as transaction_count,
    SUM(amount) as total_amount,
    AVG(amount) as avg_amount,
    SUM(CASE WHEN type != 'credit' THEN amount ELSE 0 END) as total_spent,
    SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) as total_received
FROM transactions
GROUP BY merchant_category
ORDER BY total_amount DESC;

-- ------------------------------------------------------------
-- 9. budget_status — how much you've spent this period vs. limit
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW budget_status AS
SELECT
    b.id as budget_id,
    b.category,
    b.period,
    b.limit_amount,
    b.alert_threshold_pct,
    COALESCE(SUM(t.amount) FILTER (
        WHERE t.type != 'credit'
        AND t.timestamp >= date_trunc(
            CASE WHEN b.period = 'weekly' THEN 'week' ELSE 'month' END, NOW()
        )
    ), 0) as spent_this_period
FROM budgets b
LEFT JOIN transactions t ON t.merchant_category = b.category
WHERE b.active = TRUE
GROUP BY b.id, b.category, b.period, b.limit_amount, b.alert_threshold_pct;

-- ------------------------------------------------------------
-- 10. Confirm it worked
-- ------------------------------------------------------------
SELECT 'PesaPilot DB ready ✅' as status;