import os
import re
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

import pandas as pd
import psycopg2
import psycopg2.extensions
from psycopg2 import pool as pg_pool
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values, 'DEC2FLOAT',
    lambda value, curs: float(value) if value is not None else None,
)
psycopg2.extensions.register_type(_DEC2FLOAT)


def _serialize_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _serialize_row(row: dict) -> dict:
    return {k: _serialize_value(v) for k, v in row.items()}


def _since(days: Optional[int]) -> Optional[datetime]:
    """Convert a `days` window into a cutoff datetime. days=None means
    'full history' (used throughout analyzer.py, e.g. build_context_string
    and ask_question default to days=None), so this returns None rather
    than passing None into timedelta(), which raises TypeError."""
    return datetime.now() - timedelta(days=days) if days is not None else None


_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|'
    r'EXEC|EXECUTE|CREATE|ATTACH|REPLACE|MERGE|CALL)\b',
    re.IGNORECASE
)


class PostgresDB:
    def __init__(self):
        dsn = os.getenv('DATABASE_URL')
        if not dsn:
            raise ValueError(
                "DATABASE_URL must be set, e.g. "
                "postgresql://user:password@host:5432/dbname"
            )
        try:
            self._pool = pg_pool.ThreadedConnectionPool(1, 10, dsn=dsn)
        except Exception as e:
            raise ValueError(f"Could not connect to Postgres at DATABASE_URL: {e}")
        logger.info("Postgres connection pool initialized")

    def _fetch_all(self, sql: str, params: tuple = None) -> List[Dict]:
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return [_serialize_row(dict(r)) for r in rows]
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _fetch_one(self, sql: str, params: tuple = None) -> Optional[Dict]:
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
            return _serialize_row(dict(row)) if row else None
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _execute(self, sql: str, params: tuple = None) -> None:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def _execute_values(self, sql: str, values: list) -> None:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def insert_transactions(self, df: pd.DataFrame, batch_size: int = 100) -> int:
        if df.empty:
            return 0
        records = df.where(pd.notnull(df), None).to_dict(orient='records')
        valid_records = []
        for rec in records:
            if rec is None:
                continue
            for k, v in rec.items():
                if isinstance(v, float) and pd.isna(v):
                    rec[k] = None
                if hasattr(v, 'isoformat'):
                    rec[k] = v.isoformat()
            tx_id = rec.get('transaction_id')
            if tx_id is None or str(tx_id).strip() == '':
                logger.warning(f"Skipping transaction with no ID: {rec.get('body')[:80] if rec.get('body') else rec}")
                continue
            rec['transaction_id'] = str(tx_id).strip()
            valid_records.append(rec)

        if not valid_records:
            return 0

        columns = ['transaction_id', 'amount', 'balance', 'type', 'recipient',
                   'merchant_category', 'phone', 'body', 'timestamp',
                   'readable_date', 'raw_date']
        update_cols = [c for c in columns if c != 'transaction_id']
        sql = f"""
            INSERT INTO transactions ({', '.join(columns)})
            VALUES %s
            ON CONFLICT (transaction_id) DO UPDATE SET
                {', '.join(f"{c} = EXCLUDED.{c}" for c in update_cols)}
        """

        inserted = 0
        for i in range(0, len(valid_records), batch_size):
            batch = valid_records[i:i + batch_size]
            values = [
                (
                    rec.get('transaction_id'),
                    float(rec['amount']) if rec.get('amount') is not None else None,
                    float(rec['balance']) if rec.get('balance') is not None else None,
                    rec.get('type'),
                    rec.get('recipient'),
                    rec.get('merchant_category'),
                    rec.get('phone'),
                    rec.get('body'),
                    rec.get('timestamp'),
                    rec.get('readable_date'),
                    rec.get('raw_date'),
                )
                for rec in batch
            ]
            try:
                self._execute_values(sql, values)
                inserted += len(batch)
                logger.info(f"Inserted batch {i // batch_size + 1}, total: {inserted}")
            except Exception as e:
                logger.error(f"Batch insert failed, retrying rows individually: {e}")
                for row in values:
                    try:
                        self._execute_values(sql, [row])
                        inserted += 1
                    except Exception as row_err:
                        logger.error(f"Skipping bad row {row[0]!r}: {row_err}")
        return inserted

    def execute_query(self, sql: str) -> List[Dict]:
        cleaned = (sql or "").strip().rstrip(';')
        if not cleaned.upper().startswith('SELECT') or ';' in cleaned:
            logger.warning(f"execute_query rejected unsafe SQL: {cleaned[:100]!r}")
            return []
        if _FORBIDDEN_SQL_KEYWORDS.search(cleaned):
            logger.warning(f"execute_query rejected SQL with forbidden keyword: {cleaned[:100]!r}")
            return []
        wrapped = f"SELECT * FROM ({cleaned}) AS _llm_query LIMIT 500"
        try:
            return self._fetch_all(wrapped)
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def get_transactions(self, days: Optional[int] = 30, limit: int = 1000) -> List[Dict]:
        since = _since(days)
        try:
            if since is None:
                return self._fetch_all(
                    """
                    SELECT * FROM transactions
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            return self._fetch_all(
                """
                SELECT * FROM transactions
                WHERE timestamp >= %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (since, limit),
            )
        except Exception as e:
            logger.error(f"get_transactions failed: {e}")
            return []

    def get_summary(self) -> Dict:
        try:
            data = self._fetch_all("SELECT amount, type FROM transactions")
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
        try:
            nairobi = ZoneInfo("Africa/Nairobi")
            since = datetime.now(nairobi).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )

            data = self._fetch_all(
                """
                SELECT amount, type, balance, timestamp FROM transactions
                WHERE timestamp >= %s
                ORDER BY timestamp DESC
                """,
                (since,),
            )
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
        try:
            row = self._fetch_one(
                "SELECT balance FROM transactions ORDER BY timestamp DESC LIMIT 1"
            )
            if row and row.get('balance') is not None:
                return float(row['balance'])
            return 0.0
        except Exception as e:
            logger.error(f"_get_latest_balance failed: {e}")
            return 0.0

    def get_range_summary(self, days: Optional[int] = 30) -> Dict:
        since = _since(days)
        try:
            if since is None:
                data = self._fetch_all(
                    """
                    SELECT amount, type, balance, timestamp FROM transactions
                    ORDER BY timestamp DESC
                    """
                )
            else:
                data = self._fetch_all(
                    """
                    SELECT amount, type, balance, timestamp FROM transactions
                    WHERE timestamp >= %s
                    ORDER BY timestamp DESC
                    """,
                    (since,),
                )
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

    def get_spending_by_category(self, days: Optional[int] = 30) -> List[Dict]:
        since = _since(days)
        try:
            if since is None:
                data = self._fetch_all(
                    """
                    SELECT merchant_category, amount, type FROM transactions
                    """
                )
            else:
                data = self._fetch_all(
                    """
                    SELECT merchant_category, amount, type FROM transactions
                    WHERE timestamp >= %s
                    """,
                    (since,),
                )
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

    def get_daily_trend(self, days: Optional[int] = 30) -> List[Dict]:
        since = _since(days)
        try:
            if since is None:
                data = self._fetch_all(
                    """
                    SELECT timestamp, amount, type FROM transactions
                    ORDER BY timestamp
                    """
                )
            else:
                data = self._fetch_all(
                    """
                    SELECT timestamp, amount, type FROM transactions
                    WHERE timestamp >= %s
                    ORDER BY timestamp
                    """,
                    (since,),
                )
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

    def get_top_merchants(self, days: Optional[int] = 30, limit: int = 10) -> List[Dict]:
        since = _since(days)
        try:
            if since is None:
                data = self._fetch_all(
                    """
                    SELECT recipient, amount, type FROM transactions
                    WHERE type != 'credit'
                    """
                )
            else:
                data = self._fetch_all(
                    """
                    SELECT recipient, amount, type FROM transactions
                    WHERE timestamp >= %s AND type != 'credit'
                    """,
                    (since,),
                )
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

    def get_anomalies(self, threshold: float = 2.5, days: Optional[int] = 90) -> List[Dict]:
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

    def get_insights(self, days: Optional[int] = 30) -> Dict:
        try:
            since = _since(days)
            if since is None:
                data = self._fetch_all("SELECT * FROM transactions")
            else:
                data = self._fetch_all(
                    "SELECT * FROM transactions WHERE timestamp >= %s",
                    (since,),
                )

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

    def save_spending_baselines(self, baselines: List[Dict]) -> int:
        if not baselines:
            return 0
        sql = """
            INSERT INTO spending_baselines
                (merchant_category, mean_amount, std_amount, median_amount, mad_amount, sample_size, computed_at)
            VALUES %s
            ON CONFLICT (merchant_category) DO UPDATE SET
                mean_amount = EXCLUDED.mean_amount,
                std_amount = EXCLUDED.std_amount,
                median_amount = EXCLUDED.median_amount,
                mad_amount = EXCLUDED.mad_amount,
                sample_size = EXCLUDED.sample_size,
                computed_at = EXCLUDED.computed_at
        """
        now = datetime.now()
        try:
            values = [
                (
                    b.get('merchant_category'),
                    b.get('mean_amount'),
                    b.get('std_amount'),
                    b.get('median_amount'),
                    b.get('mad_amount'),
                    b.get('sample_size'),
                    now,
                )
                for b in baselines
            ]
            self._execute_values(sql, values)
            return len(values)
        except Exception as e:
            logger.error(f"save_spending_baselines failed: {e}")
            return 0

    def get_spending_baselines(self) -> List[Dict]:
        try:
            return self._fetch_all("SELECT * FROM spending_baselines")
        except Exception as e:
            logger.error(f"get_spending_baselines failed: {e}")
            return []

    def save_anomalies(self, anomalies: List[Dict]) -> int:
        if not anomalies:
            return 0
        sql = """
            INSERT INTO anomalies (transaction_id, model, score)
            VALUES %s
            ON CONFLICT (transaction_id, model) DO UPDATE SET
                score = EXCLUDED.score
        """
        try:
            values = [
                (
                    a['transaction_id'],
                    a.get('model', 'isolation_forest_v1'),
                    a.get('score'),
                )
                for a in anomalies
            ]
            self._execute_values(sql, values)
            return len(values)
        except Exception as e:
            logger.error(f"save_anomalies failed: {e}")
            return 0

    def get_saved_anomalies(self, days: Optional[int] = 90, limit: int = 20) -> List[Dict]:
        try:
            anomaly_rows = self._fetch_all(
                """
                SELECT id, transaction_id, model, score, reviewed, created_at
                FROM anomalies
                ORDER BY score DESC
                LIMIT %s
                """,
                (limit,),
            )
            if not anomaly_rows:
                return []

            tx_ids = [r['transaction_id'] for r in anomaly_rows if r.get('transaction_id')]
            if not tx_ids:
                return []
            since = _since(days)
            if since is None:
                tx_rows = self._fetch_all(
                    """
                    SELECT id, amount, recipient, merchant_category, timestamp, body
                    FROM transactions
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (tx_ids,),
                )
            else:
                tx_rows = self._fetch_all(
                    """
                    SELECT id, amount, recipient, merchant_category, timestamp, body
                    FROM transactions
                    WHERE id = ANY(%s::uuid[]) AND timestamp >= %s
                    """,
                    (tx_ids, since),
                )
            tx_by_id = {t['id']: t for t in tx_rows}

            merged = []
            for a in anomaly_rows:
                tx = tx_by_id.get(a.get('transaction_id'))
                if not tx:
                    continue
                merged.append({**tx, **a})
            return merged
        except Exception as e:
            logger.error(f"get_saved_anomalies failed: {e}")
            return []

    def get_budgets(self, active_only: bool = True) -> List[Dict]:
        try:
            if active_only:
                return self._fetch_all("SELECT * FROM budgets WHERE active = TRUE")
            return self._fetch_all("SELECT * FROM budgets")
        except Exception as e:
            logger.error(f"get_budgets failed: {e}")
            return []

    def upsert_budget(self, category: str, limit_amount: float, period: str = 'monthly',
                       alert_threshold_pct: int = 80) -> Optional[Dict]:
        sql = """
            INSERT INTO budgets (category, period, limit_amount, alert_threshold_pct, active, updated_at)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (category, period) DO UPDATE SET
                limit_amount = EXCLUDED.limit_amount,
                alert_threshold_pct = EXCLUDED.alert_threshold_pct,
                active = TRUE,
                updated_at = EXCLUDED.updated_at
            RETURNING *
        """
        try:
            return self._fetch_one(sql, (
                category.strip().lower(),
                period.strip().lower(),
                limit_amount,
                alert_threshold_pct,
                datetime.now(),
            ))
        except Exception as e:
            logger.error(f"upsert_budget failed: {e}")
            return None

    def get_budget_status(self) -> List[Dict]:
        try:
            return self._fetch_all("SELECT * FROM budget_status")
        except Exception as e:
            logger.error(f"get_budget_status failed: {e}")
            return []

    def get_recent_budget_alerts(self, since_days: int = 45) -> List[Dict]:
        since = date.today() - timedelta(days=since_days)
        try:
            return self._fetch_all(
                """
                SELECT budget_id, period_start, alert_level
                FROM budget_alerts
                WHERE period_start >= %s
                """,
                (since,),
            )
        except Exception as e:
            logger.error(f"get_recent_budget_alerts failed: {e}")
            return []

    def record_budget_alert(self, budget_id: str, period_start: str, alert_level: str,
                             amount_spent: float) -> bool:
        sql = """
            INSERT INTO budget_alerts (budget_id, period_start, alert_level, amount_spent)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (budget_id, period_start, alert_level) DO UPDATE SET
                amount_spent = EXCLUDED.amount_spent
        """
        try:
            self._execute(sql, (budget_id, period_start, alert_level, amount_spent))
            return True
        except Exception as e:
            logger.error(f"record_budget_alert failed: {e}")
            return False

    def get_schema(self) -> str:
        return """
Table: transactions
Columns:
  - id (uuid, primary key)
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