-- ============================================================
-- PesaPilot Database Schema
-- Run this in Supabase SQL Editor: https://supabase.com/dashboard
-- ============================================================

-- 1. Main transactions table
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    transaction_id TEXT UNIQUE,
    amount DECIMAL(12,2) NOT NULL,
    balance DECIMAL(12,2),
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

-- 2. Indexes
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_transactions_amount ON transactions(amount);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_category);
CREATE INDEX IF NOT EXISTS idx_transactions_recipient ON transactions(recipient);

-- 3. RPC function so Python can run arbitrary SELECT queries
CREATE OR REPLACE FUNCTION run_query(query TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result JSONB;
BEGIN
    -- Safety: only allow SELECT
    IF UPPER(TRIM(query)) NOT LIKE 'SELECT%' THEN
        RAISE EXCEPTION 'Only SELECT queries are allowed';
    END IF;
    EXECUTE 'SELECT jsonb_agg(row_to_json(t)) FROM (' || query || ') t' INTO result;
    RETURN COALESCE(result, '[]'::JSONB);
END;
$$;

-- 4. Daily summary view
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

-- 5. Category summary view
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

-- 6. Verify setup
SELECT 'PesaPilot DB ready ✅' as status;