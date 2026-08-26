# src/database.py
import os
import logging
from datetime import datetime, timedelta, date
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

    def get_transactions(self, days: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        """days=None returns full history (no date filter). limit=None returns
        every matching row, paginated past Supabase/PostgREST's default page
        size so large accounts aren't silently truncated."""
        try:
            query = self.client.table('transactions').select('*').order('timestamp', desc=True)
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                query = query.gte('timestamp', since)
            if limit is not None:
                return (query.limit(limit).execute().data or [])
            return self._fetch_all(query)
        except Exception as e:
            logger.error(f"get_transactions failed: {e}")
            return []

    def _fetch_all(self, query, page_size: int = 1000) -> List[Dict]:
        """Page through a PostgREST query with .range() until exhausted, so
        callers asking for 'all' data actually get all of it instead of being
        capped at one page (Supabase's default/max page size is 1000 rows)."""
        rows: List[Dict] = []
        start = 0
        while True:
            page = query.range(start, start + page_size - 1).execute().data or []
            rows.extend(page)
            if len(page) < page_size:
                break
            start += page_size
        return rows

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

    def get_range_summary(self, days: Optional[int] = None) -> Dict:
        """Returns a summary scoped to the last N days, or the full account
        history when days=None, plus the latest known account balance."""
        try:
            query = (self.client.table('transactions')
                     .select('amount, type, balance, timestamp')
                     .order('timestamp', desc=True))
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                query = query.gte('timestamp', since)
            data = self._fetch_all(query)
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
            logger.error(f"get_range_summary failed: {e}")
            return {}

    def get_spending_by_category(self, days: Optional[int] = None) -> List[Dict]:
        try:
            query = self.client.table('transactions').select('merchant_category, amount, type')
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                query = query.gte('timestamp', since)
            data = self._fetch_all(query)
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

    def get_daily_trend(self, days: Optional[int] = None) -> List[Dict]:
        try:
            query = (self.client.table('transactions')
                     .select('timestamp, amount, type')
                     .order('timestamp'))
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                query = query.gte('timestamp', since)
            data = self._fetch_all(query)
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

    def get_top_merchants(self, days: Optional[int] = None, limit: Optional[int] = 10) -> List[Dict]:
        try:
            query = (self.client.table('transactions')
                     .select('recipient, amount, type')
                     .neq('type', 'credit'))
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                query = query.gte('timestamp', since)
            data = self._fetch_all(query)
            df = pd.DataFrame(data)
            if df.empty:
                return []
            top = (df.groupby('recipient')['amount']
                   .agg(['sum', 'count'])
                   .reset_index()
                   .rename(columns={'sum': 'total_amount', 'count': 'transactions'})
                   .sort_values('total_amount', ascending=False))
            if limit is not None:
                top = top.head(limit)
            return top.to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_top_merchants failed: {e}")
            return []

    def get_anomalies(self, threshold: float = 2.5, days: Optional[int] = None) -> List[Dict]:
        try:
            txs = self.get_transactions(days=days, limit=None)
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

    def get_insights(self, days: Optional[int] = None) -> Dict:
        """Generate insights for a specified period, or all-time when days=None."""
        try:
            query = self.client.table('transactions').select('*')
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                query = query.gte('timestamp', since)
            data = self._fetch_all(query)
            
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

    # ── SMARTER ANOMALY DETECTION (NEW) ─────────────────────────────────────
    def save_spending_baselines(self, baselines: List[Dict]) -> int:
        """Upsert per-category stats into spending_baselines (one row per
        merchant_category, unique on merchant_category)."""
        if not baselines:
            return 0
        try:
            records = [{**b, 'computed_at': datetime.now().isoformat()} for b in baselines]
            self.client.table('spending_baselines').upsert(
                records, on_conflict='merchant_category'
            ).execute()
            return len(records)
        except Exception as e:
            logger.error(f"save_spending_baselines failed: {e}")
            return 0

    def get_spending_baselines(self) -> List[Dict]:
        try:
            result = self.client.table('spending_baselines').select('*').execute()
            return result.data or []
        except Exception as e:
            logger.error(f"get_spending_baselines failed: {e}")
            return []

    def save_anomalies(self, anomalies: List[Dict]) -> int:
        """Upsert flagged transactions into the anomalies table, keyed on
        (transaction_id, model) so re-running detection doesn't duplicate
        rows or wipe out a human's `reviewed` flag on unchanged anomalies."""
        if not anomalies:
            return 0
        try:
            records = [
                {
                    'transaction_id': a['transaction_id'],
                    'model': a.get('model', 'isolation_forest_v1'),
                    'score': a.get('score'),
                }
                for a in anomalies
            ]
            self.client.table('anomalies').upsert(
                records, on_conflict='transaction_id,model'
            ).execute()
            return len(records)
        except Exception as e:
            logger.error(f"save_anomalies failed: {e}")
            return 0

    def get_saved_anomalies(self, days: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        """Return recently flagged anomalies joined with their transaction
        details, highest score first. Fetched as two plain queries (anomaly
        rows, then their parent transactions) and merged in Python — kept
        deliberately simple to match how the rest of this class queries
        Supabase, rather than relying on nested/embedded-resource select
        syntax."""
        try:
            anomaly_query = (self.client.table('anomalies')
                              .select('id, transaction_id, model, score, reviewed, created_at')
                              .order('score', desc=True))
            if limit is not None:
                anomaly_rows = anomaly_query.limit(limit).execute().data or []
            else:
                anomaly_rows = self._fetch_all(anomaly_query)
            if not anomaly_rows:
                return []

            tx_ids = [r['transaction_id'] for r in anomaly_rows if r.get('transaction_id')]
            if not tx_ids:
                return []
            tx_query = (self.client.table('transactions')
                        .select('id, amount, recipient, merchant_category, timestamp, body')
                        .in_('id', tx_ids))
            if days is not None:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                tx_query = tx_query.gte('timestamp', since)
            tx_result = tx_query.execute()
            tx_by_id = {t['id']: t for t in (tx_result.data or [])}

            merged = []
            for a in anomaly_rows:
                tx = tx_by_id.get(a.get('transaction_id'))
                if not tx:
                    continue  # transaction outside the `days` window, or since deleted
                merged.append({**tx, **a})
            return merged
        except Exception as e:
            logger.error(f"get_saved_anomalies failed: {e}")
            return []
    # ── END SMARTER ANOMALY DETECTION ───────────────────────────────────────

    # ── BUDGET GOALS + ALERTS (NEW) ──────────────────────────────────────────
    def get_budgets(self, active_only: bool = True) -> List[Dict]:
        try:
            query = self.client.table('budgets').select('*')
            if active_only:
                query = query.eq('active', True)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"get_budgets failed: {e}")
            return []

    def upsert_budget(self, category: str, limit_amount: float, period: str = 'monthly',
                       alert_threshold_pct: int = 80) -> Optional[Dict]:
        """Create or update a budget goal. Unique on (category, period), so
        setting the same category+period again just updates the limit."""
        try:
            record = {
                'category': category.strip().lower(),
                'period': period.strip().lower(),
                'limit_amount': limit_amount,
                'alert_threshold_pct': alert_threshold_pct,
                'active': True,
                'updated_at': datetime.now().isoformat(),
            }
            result = self.client.table('budgets').upsert(
                record, on_conflict='category,period'
            ).execute()
            return (result.data or [None])[0]
        except Exception as e:
            logger.error(f"upsert_budget failed: {e}")
            return None

    def get_budget_status(self) -> List[Dict]:
        """Reads the budget_status VIEW (defined in schema/init_db.sql),
        which computes spent_this_period live against each active budget."""
        try:
            result = self.client.table('budget_status').select('*').execute()
            return result.data or []
        except Exception as e:
            logger.error(f"get_budget_status failed: {e}")
            return []

    def get_recent_budget_alerts(self, since_days: int = 45) -> List[Dict]:
        """Pulls recently-sent alerts so the caller can build the
        (budget_id, period_start, alert_level) de-duplication set without
        re-querying per budget."""
        since = (date.today() - timedelta(days=since_days)).isoformat()
        try:
            result = (self.client.table('budget_alerts')
                      .select('budget_id, period_start, alert_level')
                      .gte('period_start', since)
                      .execute())
            return result.data or []
        except Exception as e:
            logger.error(f"get_recent_budget_alerts failed: {e}")
            return []

    def record_budget_alert(self, budget_id: str, period_start: str, alert_level: str,
                             amount_spent: float) -> bool:
        try:
            self.client.table('budget_alerts').upsert({
                'budget_id': budget_id,
                'period_start': period_start,
                'alert_level': alert_level,
                'amount_spent': amount_spent,
            }, on_conflict='budget_id,period_start,alert_level').execute()
            return True
        except Exception as e:
            logger.error(f"record_budget_alert failed: {e}")
            return False
    # ── END BUDGET GOALS + ALERTS ────────────────────────────────────────────

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