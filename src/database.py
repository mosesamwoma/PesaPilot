# src/database.py
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class SupabaseDB:
    def __init__(self):
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
        self.client: Client = create_client(url, key)
        logger.info("Supabase client initialized")

    def insert_transactions(self, df: pd.DataFrame, batch_size: int = 100) -> int:
        if df.empty:
            return 0
        records = df.where(pd.notnull(df), None).to_dict(orient='records')
        for rec in records:
            for k, v in rec.items():
                if isinstance(v, float) and pd.isna(v):
                    rec[k] = None
                if hasattr(v, 'isoformat'):
                    rec[k] = v.isoformat()

        inserted = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            try:
                self.client.table('transactions').upsert(batch, on_conflict='transaction_id').execute()
                inserted += len(batch)
                logger.info(f"Inserted batch {i//batch_size + 1}, total: {inserted}")
            except Exception as e:
                logger.error(f"Batch insert failed: {e}")
        return inserted

    def execute_query(self, sql: str) -> List[Dict]:
        try:
            result = self.client.rpc('run_query', {'query': sql}).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def get_transactions(self, days: int = 30, limit: int = 1000) -> List[Dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            result = (self.client.table('transactions')
                      .select('*')
                      .gte('timestamp', since)
                      .order('timestamp', desc=True)
                      .limit(limit)
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error(f"get_transactions failed: {e}")
            return []

    def get_summary(self) -> Dict:
        try:
            result = self.client.table('transactions').select('amount, type').execute()
            data = result.data or []
            df = pd.DataFrame(data)
            if df.empty:
                return {}
            debits = df[df['type'].isin(['debit', 'payment', 'withdrawal', 'transfer', 'airtime'])]
            credits = df[df['type'] == 'credit']
            return {
                'total_transactions': len(df),
                'total_spent': float(debits['amount'].sum()),
                'total_received': float(credits['amount'].sum()),
                'avg_spend': float(debits['amount'].mean()) if not debits.empty else 0,
                'debit_count': len(debits),
                'credit_count': len(credits),
            }
        except Exception as e:
            logger.error(f"get_summary failed: {e}")
            return {}

    def get_spending_by_category(self, days: int = 30) -> List[Dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            result = (self.client.table('transactions')
                      .select('merchant_category, amount, type')
                      .gte('timestamp', since)
                      .execute())
            data = result.data or []
            df = pd.DataFrame(data)
            if df.empty:
                return []
            debits = df[df['type'] != 'credit']
            grouped = (debits.groupby('merchant_category')['amount']
                       .agg(['sum', 'count', 'mean'])
                       .reset_index()
                       .rename(columns={'sum': 'total_amount', 'count': 'transaction_count', 'mean': 'avg_amount'}))
            grouped = grouped.sort_values('total_amount', ascending=False)
            return grouped.to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_spending_by_category failed: {e}")
            return []

    def get_daily_trend(self, days: int = 30) -> List[Dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            result = (self.client.table('transactions')
                      .select('timestamp, amount, type')
                      .gte('timestamp', since)
                      .order('timestamp')
                      .execute())
            data = result.data or []
            df = pd.DataFrame(data)
            if df.empty:
                return []
            df['date'] = pd.to_datetime(df['timestamp']).dt.date
            debits = df[df['type'] != 'credit']
            credits = df[df['type'] == 'credit']
            daily = (debits.groupby('date')['amount'].sum()
                     .reset_index().rename(columns={'amount': 'total_spent'}))
            daily_recv = (credits.groupby('date')['amount'].sum()
                          .reset_index().rename(columns={'amount': 'total_received'}))
            merged = pd.merge(daily, daily_recv, on='date', how='outer').fillna(0)
            merged['date'] = merged['date'].astype(str)
            return merged.to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_daily_trend failed: {e}")
            return []

    def get_top_merchants(self, days: int = 30, limit: int = 10) -> List[Dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            result = (self.client.table('transactions')
                      .select('recipient, amount, type')
                      .gte('timestamp', since)
                      .neq('type', 'credit')
                      .execute())
            data = result.data or []
            df = pd.DataFrame(data)
            if df.empty:
                return []
            top = (df.groupby('recipient')['amount']
                   .agg(['sum', 'count'])
                   .reset_index()
                   .rename(columns={'sum': 'total_amount', 'count': 'transactions'})
                   .sort_values('total_amount', ascending=False)
                   .head(limit))
            return top.to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_top_merchants failed: {e}")
            return []

    def get_anomalies(self, threshold: float = 2.5, days: int = 90) -> List[Dict]:
        try:
            txs = self.get_transactions(days=days, limit=5000)
            df = pd.DataFrame(txs)
            if df.empty or 'amount' not in df.columns:
                return []
            debits = df[df['type'] != 'credit'].copy()
            mean = debits['amount'].mean()
            std = debits['amount'].std()
            if std == 0:
                return []
            debits['zscore'] = (debits['amount'] - mean) / std
            anomalies = debits[debits['zscore'].abs() > threshold]
            return anomalies[['transaction_id', 'amount', 'recipient', 'timestamp', 'zscore']].to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_anomalies failed: {e}")
            return []

    def get_schema(self) -> str:
        return """
Table: transactions
Columns:
  - id (integer, primary key)
  - transaction_id (text, unique)
  - amount (decimal) - transaction amount in KES
  - balance (decimal) - account balance after transaction
  - type (text) - 'credit', 'debit', 'payment', 'withdrawal', 'transfer', 'airtime'
  - recipient (text) - person or merchant name
  - merchant_category (text) - food, transport, utilities, banking, shopping, health, education, entertainment, savings, business, other
  - phone (text) - phone number
  - body (text) - original SMS text
  - timestamp (timestamp) - transaction datetime
  - readable_date (text)
  - raw_date (text)
  - created_at (timestamp)
"""