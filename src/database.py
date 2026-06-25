# src/database.py
import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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

    def get_today_summary(self) -> Dict:
        """Returns a summary scoped to TODAY only (Africa/Nairobi calendar day),
        plus the latest known account balance. Used by the 9PM daily summary cron."""
        try:
            nairobi = ZoneInfo("Africa/Nairobi")
            start_of_day_nairobi = datetime.now(nairobi).replace(hour=0, minute=0, second=0, microsecond=0)
            since = start_of_day_nairobi.astimezone(ZoneInfo("UTC")).isoformat()

            result = (self.client.table('transactions')
                      .select('amount, type, balance, timestamp')
                      .gte('timestamp', since)
                      .order('timestamp', desc=True)
                      .execute())
            data = result.data or []
            df = pd.DataFrame(data)

            latest_balance = 0.0
            if not df.empty and 'balance' in df.columns and df['balance'].notna().any():
                latest_balance = float(df['balance'].iloc[0])
            else:
                latest_balance = self._get_latest_balance()

            if df.empty:
                return {
                    'total_transactions': 0,
                    'total_spent': 0,
                    'total_received': 0,
                    'avg_spend': 0,
                    'debit_count': 0,
                    'credit_count': 0,
                    'balance': latest_balance,
                }

            debits = df[df['type'].isin(['debit', 'payment', 'withdrawal', 'transfer', 'airtime'])]
            credits = df[df['type'] == 'credit']
            return {
                'total_transactions': len(df),
                'total_spent': float(debits['amount'].sum()) if not debits.empty else 0,
                'total_received': float(credits['amount'].sum()) if not credits.empty else 0,
                'avg_spend': float(debits['amount'].mean()) if not debits.empty else 0,
                'debit_count': len(debits),
                'credit_count': len(credits),
                'balance': latest_balance,
            }
        except Exception as e:
            logger.error(f"get_today_summary failed: {e}")
            return {}

    def _get_latest_balance(self) -> float:
        """Fallback: fetch the balance from the single most recent transaction,
        regardless of date, in case today has no transactions yet."""
        try:
            result = (self.client.table('transactions')
                      .select('balance')
                      .order('timestamp', desc=True)
                      .limit(1)
                      .execute())
            data = result.data or []
            if data and data[0].get('balance') is not None:
                return float(data[0]['balance'])
            return 0.0
        except Exception as e:
            logger.error(f"_get_latest_balance failed: {e}")
            return 0.0

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

    def get_insights(self, days: int = 30) -> Dict:
        """Generate insights for today or specified period"""
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            result = (self.client.table('transactions')
                      .select('*')
                      .gte('timestamp', since)
                      .execute())
            data = result.data or []
            
            if not data:
                return {
                    'total_spent': 0,
                    'total_received': 0,
                    'transaction_count': 0,
                    'top_merchant': 'N/A',
                    'top_category': 'N/A',
                    'avg_transaction': 0
                }
            
            df = pd.DataFrame(data)
            debits = df[df['type'].isin(['debit', 'payment', 'withdrawal', 'transfer', 'airtime'])]
            credits = df[df['type'] == 'credit']
            
            total_spent = float(debits['amount'].sum()) if not debits.empty else 0
            total_received = float(credits['amount'].sum()) if not credits.empty else 0
            
            top_merchant = 'N/A'
            if not debits.empty and 'recipient' in debits.columns:
                top_merchant = debits.groupby('recipient')['amount'].sum().idxmax()
            
            top_category = 'N/A'
            if not debits.empty and 'merchant_category' in debits.columns:
                top_category = debits.groupby('merchant_category')['amount'].sum().idxmax()
            
            avg_transaction = float(debits['amount'].mean()) if not debits.empty else 0
            
            return {
                'total_spent': total_spent,
                'total_received': total_received,
                'transaction_count': len(df),
                'top_merchant': str(top_merchant),
                'top_category': str(top_category),
                'avg_transaction': avg_transaction
            }
        except Exception as e:
            logger.error(f"get_insights failed: {e}")
            return {
                'total_spent': 0,
                'total_received': 0,
                'transaction_count': 0,
                'top_merchant': 'N/A',
                'top_category': 'N/A',
                'avg_transaction': 0
            }

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