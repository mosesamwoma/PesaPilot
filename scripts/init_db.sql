-- Create transactions table
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    transaction_id TEXT UNIQUE,
    amount DECIMAL(10,2) NOT NULL,
    balance DECIMAL(10,2),
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

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_transactions_amount ON transactions(amount);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant_category);
CREATE INDEX IF NOT EXISTS idx_transactions_recipient ON transactions(recipient);

-- Create view for daily summary
CREATE OR REPLACE VIEW daily_summary AS
SELECT 
    DATE(timestamp) as date,
    COUNT(*) as total_transactions,
    SUM(CASE WHEN type = 'debit' THEN amount ELSE 0 END) as total_spent,
    SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) as total_received,
    AVG(CASE WHEN type = 'debit' THEN amount ELSE NULL END) as avg_spend,
    COUNT(CASE WHEN type = 'debit' THEN 1 END) as debit_count,
    COUNT(CASE WHEN type = 'credit' THEN 1 END) as credit_count
FROM transactions
GROUP BY DATE(timestamp)
ORDER BY date DESC;

-- Create view for category summary
CREATE OR REPLACE VIEW category_summary AS
SELECT 
    merchant_category,
    COUNT(*) as transaction_count,
    SUM(amount) as total_amount,
    AVG(amount) as avg_amount,
    SUM(CASE WHEN type = 'debit' THEN amount ELSE 0 END) as total_spent,
    SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) as total_received
FROM transactions
GROUP BY merchant_category
ORDER BY total_amount DESC;