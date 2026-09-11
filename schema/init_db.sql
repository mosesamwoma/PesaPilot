-- ============================================================
-- PesaPilot database schema (self-hosted PostgreSQL)
-- ============================================================
-- BEGINNER NOTE: this whole script is safe to run more than once.
-- Every CREATE TABLE / CREATE INDEX below uses "IF NOT EXISTS", and
-- every function/view uses "CREATE OR REPLACE" — so re-running it
-- (e.g. after `git pull`) will never error out with "already exists".
--
-- With a local/VPS PostgreSQL install (using your POSTGRES_* .env values):
--   PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f schema/init_db.sql
--
-- You should see: PesaPilot DB ready ✅
-- ============================================================

-- Needed for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ------------------------------------------------------------
-- MIGRATION (only needed if you already had a `transactions`
-- table from before transaction_cost existed):
--
--   ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transaction_cost DECIMAL(12,2) NOT NULL DEFAULT 0;
--
-- Safe to run more than once. Existing rows backfill to 0 automatically.
-- Re-import your SMS Backup & Restore XML (or resend past SMS through
-- the WhatsApp bot) afterwards to get REAL fee amounts in place of 0,
-- and to refresh any "Unknown" recipient names from the parser fix.
-- ------------------------------------------------------------

-- ------------------------------------------------------------
-- 1. transactions
-- Core table. `id` is a UUID — the safe, unique identifier used
-- everywhere else. `transaction_id` is the M-Pesa-provided code,
-- used to prevent the same SMS being inserted twice.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
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

CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_transactions_amount ON transactions(amount);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_category);
CREATE INDEX IF NOT EXISTS idx_transactions_recipient ON transactions(recipient);

-- ------------------------------------------------------------
-- 2. budgets
-- One row per category you want to set a spending limit on.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN ('weekly', 'monthly')),
    limit_amount DECIMAL(12,2) NOT NULL CHECK (limit_amount > 0),
    alert_threshold_pct INT NOT NULL DEFAULT 80 CHECK (alert_threshold_pct BETWEEN 1 AND 100),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(category, period)
);

CREATE INDEX IF NOT EXISTS idx_budgets_category ON budgets(category);

-- ------------------------------------------------------------
-- 3. budget_alerts
-- Log of alerts already sent, so the WhatsApp bot never pings
-- you twice for the same budget breach in the same period.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budget_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    budget_id UUID REFERENCES budgets(id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    alert_level TEXT NOT NULL,
    amount_spent DECIMAL(12,2) NOT NULL,
    sent_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(budget_id, period_start, alert_level)
);

CREATE INDEX IF NOT EXISTS idx_budget_alerts_budget ON budget_alerts(budget_id);

-- ------------------------------------------------------------
-- 4. spending_baselines
-- One row per merchant_category, holding stats used to judge
-- what's "normal" for THAT category specifically — this is what
-- makes anomaly detection personalized instead of one global
-- threshold across every kind of spending.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spending_baselines (
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
CREATE TABLE IF NOT EXISTS anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID REFERENCES transactions(id) ON DELETE CASCADE,
    model TEXT NOT NULL DEFAULT 'category_mad',
    score DECIMAL(6,3),
    reviewed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(transaction_id, model)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_tx ON anomalies(transaction_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_model ON anomalies(model);

-- ------------------------------------------------------------
-- 6. run_query — lets the Python backend (and the "ask AI about
-- your spending" feature) run SELECT-only queries. Only SELECT
-- is allowed: anything else raises an exception before it runs.
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

-- ============================================================
-- ANALYTICS EXTENSION — window functions + CTEs
-- Everything below is additive: new functions only, nothing
-- above is touched. Safe to re-run (CREATE OR REPLACE FUNCTION
-- throughout).
-- ============================================================

-- ------------------------------------------------------------
-- 10. daily_trend_running(days)
-- Running cumulative spend, a 7-day rolling average, and
-- day-over-day change. days = NULL means full history.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION daily_trend_running(days INT DEFAULT NULL)
RETURNS TABLE (
    day DATE,
    total_spent DECIMAL,
    total_received DECIMAL,
    cumulative_spent DECIMAL,
    spend_7day_avg DECIMAL,
    spend_change_from_prev_day DECIMAL
)
LANGUAGE sql
STABLE
AS $$
    WITH daily AS (
        SELECT
            DATE(timestamp) AS day,
            SUM(CASE WHEN type != 'credit' THEN amount ELSE 0 END) AS total_spent,
            SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) AS total_received
        FROM transactions
        WHERE days IS NULL OR timestamp >= NOW() - (days || ' days')::interval
        GROUP BY DATE(timestamp)
    )
    SELECT
        d.day,
        d.total_spent,
        d.total_received,
        SUM(d.total_spent) OVER (ORDER BY d.day) AS cumulative_spent,
        ROUND(
            AVG(d.total_spent) OVER (ORDER BY d.day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
            2
        ) AS spend_7day_avg,
        d.total_spent - LAG(d.total_spent) OVER (ORDER BY d.day) AS spend_change_from_prev_day
    FROM daily d
    ORDER BY d.day;
$$;

-- ------------------------------------------------------------
-- 11. category_month_trend(months_back)
-- Monthly total per category, per-month rank (ties share a
-- place), and month-over-month % change. months_back = NULL
-- means full history.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION category_month_trend(months_back INT DEFAULT NULL)
RETURNS TABLE (
    month DATE,
    merchant_category TEXT,
    total_amount DECIMAL,
    category_rank_in_month BIGINT,
    prev_month_amount DECIMAL,
    mom_pct_change DECIMAL
)
LANGUAGE sql
STABLE
AS $$
    WITH monthly_category AS (
        SELECT
            date_trunc('month', timestamp)::date AS month,
            merchant_category,
            SUM(amount) AS total_amount
        FROM transactions
        WHERE type != 'credit'
          AND (
              months_back IS NULL
              OR timestamp >= date_trunc('month', NOW()) - (months_back || ' months')::interval
          )
        GROUP BY date_trunc('month', timestamp), merchant_category
    )
    SELECT
        mc.month,
        mc.merchant_category,
        mc.total_amount,
        RANK() OVER (PARTITION BY mc.month ORDER BY mc.total_amount DESC) AS category_rank_in_month,
        LAG(mc.total_amount) OVER (PARTITION BY mc.merchant_category ORDER BY mc.month) AS prev_month_amount,
        ROUND(
            (mc.total_amount - LAG(mc.total_amount) OVER (PARTITION BY mc.merchant_category ORDER BY mc.month))
            / NULLIF(LAG(mc.total_amount) OVER (PARTITION BY mc.merchant_category ORDER BY mc.month), 0) * 100,
            1
        ) AS mom_pct_change
    FROM monthly_category mc
    ORDER BY mc.month DESC, category_rank_in_month;
$$;

-- ------------------------------------------------------------
-- 12. top_merchants_ranked(days, limit_count)
-- DENSE_RANK, each merchant's % share of total spend, and a
-- running cumulative % (a Pareto view — "these N merchants are
-- 80% of spend"). NULL = full history / no limit.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION top_merchants_ranked(days INT DEFAULT NULL, limit_count INT DEFAULT NULL)
RETURNS TABLE (
    recipient TEXT,
    total_amount DECIMAL,
    transaction_count BIGINT,
    merchant_rank BIGINT,
    pct_of_total_spend DECIMAL,
    cumulative_pct DECIMAL
)
LANGUAGE sql
STABLE
AS $$
    WITH merchant_totals AS (
        SELECT
            t.recipient,
            SUM(t.amount) AS total_amount,
            COUNT(*) AS transaction_count
        FROM transactions t
        WHERE t.type != 'credit'
          AND t.recipient IS NOT NULL
          AND (days IS NULL OR t.timestamp >= NOW() - (days || ' days')::interval)
        GROUP BY t.recipient
    ),
    grand_total AS (
        SELECT SUM(mt.total_amount) AS overall_total FROM merchant_totals mt
    )
    SELECT
        mt.recipient,
        mt.total_amount,
        mt.transaction_count,
        DENSE_RANK() OVER (ORDER BY mt.total_amount DESC) AS merchant_rank,
        ROUND(mt.total_amount / NULLIF(gt.overall_total, 0) * 100, 1) AS pct_of_total_spend,
        ROUND(
            SUM(mt.total_amount) OVER (ORDER BY mt.total_amount DESC)
            / NULLIF(gt.overall_total, 0) * 100,
            1
        ) AS cumulative_pct
    FROM merchant_totals mt
    CROSS JOIN grand_total gt
    ORDER BY mt.total_amount DESC
    LIMIT limit_count;
$$;

-- ------------------------------------------------------------
-- 13. detect_category_anomalies(z_threshold, lookback_days)
-- Per-category z-score anomaly detection: mean/stddev computed
-- PER merchant_category, so a KES 3,000 "food" transaction and
-- a KES 3,000 "transport" transaction are judged against
-- different baselines instead of one blended global one.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION detect_category_anomalies(
    z_threshold NUMERIC DEFAULT 2.5,
    lookback_days INT DEFAULT 90
)
RETURNS TABLE (
    id UUID,
    transaction_id TEXT,
    amount DECIMAL,
    recipient TEXT,
    merchant_category TEXT,
    tx_timestamp TIMESTAMP,
    category_mean DECIMAL,
    category_stddev DECIMAL,
    zscore DECIMAL
)
LANGUAGE sql
STABLE
AS $$
    WITH scoped AS (
        SELECT
            t.id, t.transaction_id, t.amount, t.recipient, t.merchant_category, t.timestamp
        FROM transactions t
        WHERE t.type != 'credit'
          AND (lookback_days IS NULL OR t.timestamp >= NOW() - (lookback_days || ' days')::interval)
    ),
    scored AS (
        SELECT
            s.id, s.transaction_id, s.amount, s.recipient, s.merchant_category, s.timestamp,
            AVG(s.amount) OVER (PARTITION BY s.merchant_category) AS category_mean,
            STDDEV(s.amount) OVER (PARTITION BY s.merchant_category) AS category_stddev
        FROM scoped s
    )
    SELECT
        sc.id,
        sc.transaction_id,
        sc.amount,
        sc.recipient,
        sc.merchant_category,
        sc.timestamp AS tx_timestamp,
        ROUND(sc.category_mean, 2) AS category_mean,
        ROUND(sc.category_stddev, 2) AS category_stddev,
        ROUND((sc.amount - sc.category_mean) / NULLIF(sc.category_stddev, 0), 3) AS zscore
    FROM scored sc
    WHERE sc.category_stddev > 0
      AND ABS((sc.amount - sc.category_mean) / NULLIF(sc.category_stddev, 0)) > z_threshold
    ORDER BY ABS((sc.amount - sc.category_mean) / NULLIF(sc.category_stddev, 0)) DESC;
$$;

-- ------------------------------------------------------------
-- 14. budget_pace()
-- For every active budget: % of period elapsed, average daily
-- spend so far, a straight-line projection of the full-period
-- spend, % of limit used, and a RANK so the most at-risk budget
-- surfaces first.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION budget_pace()
RETURNS TABLE (
    budget_id UUID,
    category TEXT,
    period TEXT,
    limit_amount DECIMAL,
    period_start TIMESTAMP,
    period_end TIMESTAMP,
    spent_so_far DECIMAL,
    days_elapsed NUMERIC,
    avg_daily_spend DECIMAL,
    projected_period_spend DECIMAL,
    pct_of_limit_used DECIMAL,
    risk_rank BIGINT
)
LANGUAGE sql
STABLE
AS $$
    WITH period_bounds AS (
        SELECT
            b.id AS budget_id,
            b.category,
            b.period,
            b.limit_amount,
            date_trunc(CASE WHEN b.period = 'weekly' THEN 'week' ELSE 'month' END, NOW()) AS period_start,
            CASE
                WHEN b.period = 'weekly' THEN date_trunc('week', NOW()) + INTERVAL '7 days'
                ELSE date_trunc('month', NOW()) + INTERVAL '1 month'
            END AS period_end
        FROM budgets b
        WHERE b.active = TRUE
    ),
    spend_totals AS (
        SELECT
            pb.budget_id,
            pb.category,
            pb.period,
            pb.limit_amount,
            pb.period_start,
            pb.period_end,
            COALESCE(SUM(t.amount), 0) AS spent_so_far
        FROM period_bounds pb
        LEFT JOIN transactions t
            ON t.merchant_category = pb.category
           AND t.type != 'credit'
           AND t.timestamp >= pb.period_start
           AND t.timestamp < pb.period_end
        GROUP BY pb.budget_id, pb.category, pb.period, pb.limit_amount, pb.period_start, pb.period_end
    ),
    paced AS (
        SELECT
            st.budget_id,
            st.category,
            st.period,
            st.limit_amount,
            st.period_start,
            st.period_end,
            st.spent_so_far,
            GREATEST(EXTRACT(EPOCH FROM (LEAST(NOW(), st.period_end) - st.period_start)) / 86400.0, 1) AS days_elapsed,
            EXTRACT(EPOCH FROM (st.period_end - st.period_start)) / 86400.0 AS period_total_days
        FROM spend_totals st
    )
    SELECT
        p.budget_id,
        p.category,
        p.period,
        p.limit_amount,
        p.period_start,
        p.period_end,
        p.spent_so_far,
        ROUND(p.days_elapsed, 1) AS days_elapsed,
        ROUND(p.spent_so_far / p.days_elapsed, 2) AS avg_daily_spend,
        ROUND((p.spent_so_far / p.days_elapsed) * p.period_total_days, 2) AS projected_period_spend,
        ROUND(p.spent_so_far / NULLIF(p.limit_amount, 0) * 100, 1) AS pct_of_limit_used,
        RANK() OVER (ORDER BY p.spent_so_far / NULLIF(p.limit_amount, 0) DESC) AS risk_rank
    FROM paced p
    ORDER BY risk_rank;
$$;

-- ------------------------------------------------------------
-- 15. recipient_gaps(days)
-- Days between consecutive transactions to the SAME recipient —
-- good for spotting recurring/subscription-like payments (a
-- merchant whose gaps cluster around ~30 days is probably a
-- monthly bill) without a separate subscriptions table.
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION recipient_gaps(days INT DEFAULT NULL)
RETURNS TABLE (
    recipient TEXT,
    tx_timestamp TIMESTAMP,
    amount DECIMAL,
    prev_timestamp TIMESTAMP,
    days_since_prev NUMERIC
)
LANGUAGE sql
STABLE
AS $$
    WITH tx AS (
        SELECT
            t.recipient,
            t.timestamp,
            t.amount,
            LAG(t.timestamp) OVER (PARTITION BY t.recipient ORDER BY t.timestamp) AS prev_timestamp
        FROM transactions t
        WHERE t.type != 'credit'
          AND t.recipient IS NOT NULL
          AND (days IS NULL OR t.timestamp >= NOW() - (days || ' days')::interval)
    )
    SELECT
        tx.recipient,
        tx.timestamp AS tx_timestamp,
        tx.amount,
        tx.prev_timestamp,
        ROUND(EXTRACT(EPOCH FROM (tx.timestamp - tx.prev_timestamp)) / 86400.0, 1) AS days_since_prev
    FROM tx
    WHERE tx.prev_timestamp IS NOT NULL
    ORDER BY tx.recipient, tx.timestamp;
$$;

-- ------------------------------------------------------------
-- 16. Confirm it worked
-- ------------------------------------------------------------
SELECT 'PesaPilot DB ready ✅' as status;