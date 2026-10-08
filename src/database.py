import os
import logging
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional

import pandas as pd
import psycopg2
import psycopg2.extensions
from psycopg2 import pool as pg_pool
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv

from src.constants import SPENDING_TYPES
from src.sql_guard import is_safe_select_sql
from src.timeutil import now_nairobi, since_nairobi, today_nairobi

load_dotenv()
logger = logging.getLogger(__name__)

_DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values, 'DEC2FLOAT',
    lambda value, curs: float(value) if value is not None else None,
)
psycopg2.extensions.register_type(_DEC2FLOAT)

_MAX_SCORE = 999.999
_QUERY_ROW_LIMIT = 500
_QUERY_TIMEOUT_MS = 10000


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


def _clamp_score(score):
    if score is None:
        return None
    try:
        return max(-_MAX_SCORE, min(_MAX_SCORE, float(score)))
    except (TypeError, ValueError):
        return None


def _running_in_docker() -> bool:
    return os.path.exists('/.dockerenv')


def _running_in_podman() -> bool:
    return os.path.exists('/run/.containerenv') or os.getenv('container') == 'podman'


def _resolves(hostname: str) -> bool:
    import socket
    try:
        socket.gethostbyname(hostname)
        return True
    except OSError:
        return False


def _detect_postgres_host() -> str:
    if _running_in_podman():
        return 'host.containers.internal'
    if _running_in_docker():
        if _resolves('host.docker.internal'):
            return 'host.docker.internal'
        logger.warning(
            "host.docker.internal did not resolve; falling back to 172.17.0.1 "
            "(Docker's default bridge gateway). If Postgres still isn't reachable, "
            "set POSTGRES_HOST explicitly."
        )
        return '172.17.0.1'
    return '127.0.0.1'


def _pg_connection_kwargs() -> Dict[str, str]:
    user = os.getenv('POSTGRES_USER')
    password = os.getenv('POSTGRES_PASSWORD')
    db = os.getenv('POSTGRES_DB')
    missing = [name for name, val in (
        ('POSTGRES_USER', user), ('POSTGRES_PASSWORD', password), ('POSTGRES_DB', db)
    ) if not val]
    if missing:
        raise ValueError(
            f"Missing required env var(s): {', '.join(missing)}. "
            "Set POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB in your .env "
            "(POSTGRES_HOST and POSTGRES_PORT are optional, defaulting to "
            "auto-detection and 5432)."
        )

    assert user is not None and password is not None and db is not None

    host_setting = os.getenv('POSTGRES_HOST', 'auto').strip()
    if host_setting.lower() == 'auto' or not host_setting:
        host = _detect_postgres_host()
        logger.info(f"POSTGRES_HOST=auto -> detected '{host}'")
    else:
        host = host_setting

    return {
        'user': user,
        'password': password,
        'dbname': db,
        'host': host,
        'port': os.getenv('POSTGRES_PORT', '5432'),
    }


def _summarize(df: pd.DataFrame, fallback_balance: float) -> Dict:
    empty = {
        'total_transactions': 0,
        'total_spent': 0,
        'total_received': 0,
        'avg_spend': 0,
        'debit_count': 0,
        'credit_count': 0,
        'balance': fallback_balance,
        'total_transaction_cost': 0,
        'span_days': 0,
    }
    if df.empty:
        return empty

    balance = fallback_balance
    if 'balance' in df.columns and df['balance'].notna().any():
        balance = float(df['balance'].dropna().iloc[0])

    debits = df[df['type'].isin(SPENDING_TYPES)]
    credits = df[df['type'] == 'credit']
    total_cost = 0.0
    if not debits.empty and 'transaction_cost' in debits.columns:
        total_cost = float(debits['transaction_cost'].fillna(0).sum())

    stamps = pd.to_datetime(df['timestamp'], format='ISO8601', errors='coerce').dropna()
    span_days = (stamps.max().normalize() - stamps.min().normalize()).days + 1 if not stamps.empty else 0

    return {
        'span_days': span_days,
        'total_transactions': len(df),
        'total_spent': float(debits['amount'].sum()) if not debits.empty else 0,
        'total_received': float(credits['amount'].sum()) if not credits.empty else 0,
        'avg_spend': float(debits['amount'].mean()) if not debits.empty else 0,
        'debit_count': len(debits),
        'credit_count': len(credits),
        'balance': balance,
        'total_transaction_cost': total_cost,
    }


class PostgresDB:
    def __init__(self):
        conn_kwargs = _pg_connection_kwargs()
        try:
            self._pool = pg_pool.ThreadedConnectionPool(1, 10, **conn_kwargs)
        except Exception as e:
            raise ValueError(f"Could not connect to Postgres: {e}") from e
        logger.info("Postgres connection pool initialized")

    def close(self) -> None:
        try:
            self._pool.closeall()
            logger.info("Postgres connection pool closed")
        except Exception as e:
            logger.error(f"Error closing connection pool: {e}")

    def _fetch_all(self, sql: str, params: Optional[tuple] = None, readonly: bool = False) -> List[Dict]:
        conn = self._pool.getconn()
        try:
            if readonly:
                conn.readonly = True
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if readonly:
                    cur.execute(f"SET LOCAL statement_timeout = {_QUERY_TIMEOUT_MS}")
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            return [_serialize_row(dict(r)) for r in rows]
        except Exception:
            conn.rollback()
            raise
        finally:
            if readonly:
                conn.readonly = False
            self._pool.putconn(conn)

    def _fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Dict]:
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

    def _execute(self, sql: str, params: Optional[tuple] = None) -> None:
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

    def insert_transactions(self, df: pd.DataFrame, batch_size: int = 100, overwrite: bool = True) -> int:
        if df.empty:
            return 0
        records = df.astype(object).where(pd.notnull(df), None).to_dict(orient='records')
        valid_records = []
        for rec in records:
            for k, v in rec.items():
                if isinstance(v, float) and pd.isna(v):
                    rec[k] = None
                elif hasattr(v, 'isoformat'):
                    rec[k] = v.isoformat()
            tx_id = rec.get('transaction_id')
            if tx_id is None or str(tx_id).strip() == '':
                body_preview = str(rec.get('body') or '(no body)')[:80]
                logger.warning(f"Skipping transaction with no ID: {body_preview}")
                continue
            rec['transaction_id'] = str(tx_id).strip()
            valid_records.append(rec)

        if not valid_records:
            return 0

        columns = ['transaction_id', 'amount', 'balance', 'transaction_cost', 'type', 'recipient',
                   'merchant_category', 'phone', 'body', 'timestamp',
                   'readable_date', 'raw_date']
        update_cols = [c for c in columns if c != 'transaction_id']
        conflict = (
            f"DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in update_cols)}"
            if overwrite else "DO NOTHING"
        )
        sql = f"""
            INSERT INTO transactions ({', '.join(columns)})
            VALUES %s
            ON CONFLICT (transaction_id) {conflict}
        """

        inserted = 0
        for i in range(0, len(valid_records), batch_size):
            batch = valid_records[i:i + batch_size]
            values = [
                (
                    rec.get('transaction_id'),
                    float(rec['amount']) if rec.get('amount') is not None else None,
                    float(rec['balance']) if rec.get('balance') is not None else None,
                    float(rec.get('transaction_cost') or 0),
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

    def transaction_exists(self, transaction_id: str) -> bool:
        try:
            row = self._fetch_one(
                "SELECT 1 AS found FROM transactions WHERE transaction_id = %s",
                (transaction_id,),
            )
            return row is not None
        except Exception as e:
            logger.error(f"transaction_exists failed: {e}")
            return False

    def execute_query(self, sql: str) -> List[Dict]:
        if not is_safe_select_sql(sql):
            logger.warning(f"execute_query rejected unsafe SQL: {(sql or '')[:100]!r}")
            return []
        cleaned = sql.strip().rstrip(';').strip()
        wrapped = f"SELECT * FROM ({cleaned}) AS _llm_query LIMIT {_QUERY_ROW_LIMIT}"
        try:
            return self._fetch_all(wrapped, readonly=True)
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def get_transactions(self, days: Optional[int] = 30, limit: Optional[int] = 1000) -> List[Dict]:
        since = since_nairobi(days)
        try:
            if since is None:
                return self._fetch_all(
                    "SELECT * FROM transactions ORDER BY timestamp DESC LIMIT %s",
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

    def get_transactions_range(self, date_from: Optional[str] = None,
                               date_to: Optional[str] = None, limit: int = 20000) -> List[Dict]:
        conditions = []
        params: list = []
        if date_from:
            conditions.append("timestamp >= %s")
            params.append(date_from)
        if date_to:
            try:
                upper = (datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)).isoformat()
                conditions.append("timestamp < %s")
                params.append(upper)
            except ValueError:
                logger.warning(f"Ignoring invalid date_to: {date_to!r}")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT * FROM transactions
            {where_clause}
            ORDER BY timestamp ASC
            LIMIT %s
        """
        params.append(limit)
        try:
            return self._fetch_all(sql, tuple(params))
        except Exception as e:
            logger.error(f"get_transactions_range failed: {e}")
            return []

    def _get_latest_balance(self) -> float:
        try:
            row = self._fetch_one(
                "SELECT balance FROM transactions WHERE balance IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 1"
            )
            if row and row.get('balance') is not None:
                return float(row['balance'])
            return 0.0
        except Exception as e:
            logger.error(f"_get_latest_balance failed: {e}")
            return 0.0

    def _summary_since(self, since: Optional[datetime]) -> Dict:
        if since is None:
            data = self._fetch_all(
                "SELECT amount, type, balance, transaction_cost, timestamp FROM transactions "
                "ORDER BY timestamp DESC"
            )
        else:
            data = self._fetch_all(
                "SELECT amount, type, balance, transaction_cost, timestamp FROM transactions "
                "WHERE timestamp >= %s ORDER BY timestamp DESC",
                (since,),
            )
        df = pd.DataFrame(data)
        fallback = self._get_latest_balance() if df.empty or df['balance'].isna().all() else 0.0
        return _summarize(df, fallback)

    def get_today_summary(self) -> Dict:
        try:
            start = now_nairobi().replace(hour=0, minute=0, second=0, microsecond=0)
            return self._summary_since(start)
        except Exception as e:
            logger.error(f"get_today_summary failed: {e}")
            return {}

    def get_range_summary(self, days: Optional[int] = 30) -> Dict:
        try:
            return self._summary_since(since_nairobi(days))
        except Exception as e:
            logger.error(f"get_range_summary failed: {e}")
            return {}

    def get_spending_by_category(self, days: Optional[int] = 30) -> List[Dict]:
        since = since_nairobi(days)
        try:
            if since is None:
                data = self._fetch_all(
                    "SELECT merchant_category, amount, transaction_cost, type FROM transactions"
                )
            else:
                data = self._fetch_all(
                    "SELECT merchant_category, amount, transaction_cost, type FROM transactions "
                    "WHERE timestamp >= %s",
                    (since,),
                )
            df = pd.DataFrame(data)
            if df.empty:
                return []
            debits = df[df['type'].isin(SPENDING_TYPES)].copy()
            if debits.empty:
                return []
            debits['merchant_category'] = debits['merchant_category'].fillna('other')
            debits['transaction_cost'] = debits['transaction_cost'].fillna(0)
            grouped = (debits.groupby('merchant_category')
                       .agg(total_amount=('amount', 'sum'),
                            transaction_count=('amount', 'count'),
                            avg_amount=('amount', 'mean'),
                            total_transaction_cost=('transaction_cost', 'sum'))
                       .reset_index())
            grouped = grouped.sort_values('total_amount', ascending=False)
            return grouped.to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_spending_by_category failed: {e}")
            return []

    def get_daily_trend(self, days: Optional[int] = 30) -> List[Dict]:
        since = since_nairobi(days)
        try:
            if since is None:
                data = self._fetch_all(
                    "SELECT timestamp, amount, type FROM transactions ORDER BY timestamp"
                )
            else:
                data = self._fetch_all(
                    "SELECT timestamp, amount, type FROM transactions "
                    "WHERE timestamp >= %s ORDER BY timestamp",
                    (since,),
                )
            df = pd.DataFrame(data)
            if df.empty:
                return []
            df['date'] = pd.to_datetime(df['timestamp'], format='ISO8601', errors='coerce').dt.date
            df = df.dropna(subset=['date'])
            if df.empty:
                return []
            debits = df[df['type'].isin(SPENDING_TYPES)]
            credits = df[df['type'] == 'credit']
            daily = (debits.groupby('date')['amount'].sum()
                     .reset_index().rename(columns={'amount': 'total_spent'}))
            daily_recv = (credits.groupby('date')['amount'].sum()
                          .reset_index().rename(columns={'amount': 'total_received'}))
            merged = pd.merge(daily, daily_recv, on='date', how='outer').fillna(0).sort_values('date')
            merged['date'] = merged['date'].astype(str)
            return merged.to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_daily_trend failed: {e}")
            return []

    def get_top_merchants(self, days: Optional[int] = 30, limit: Optional[int] = 10) -> List[Dict]:
        since = since_nairobi(days)
        try:
            if since is None:
                data = self._fetch_all(
                    "SELECT recipient, amount FROM transactions WHERE type = ANY(%s)",
                    (list(SPENDING_TYPES),),
                )
            else:
                data = self._fetch_all(
                    "SELECT recipient, amount FROM transactions "
                    "WHERE timestamp >= %s AND type = ANY(%s)",
                    (since, list(SPENDING_TYPES)),
                )
            df = pd.DataFrame(data)
            if df.empty:
                return []
            df['recipient'] = df['recipient'].fillna('Unknown')
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

    def get_anomalies(self, threshold: float = 2.5, days: Optional[int] = 90) -> List[Dict]:
        try:
            txs = self.get_transactions(days=days, limit=5000)
            df = pd.DataFrame(txs)
            if df.empty or 'amount' not in df.columns:
                return []
            debits = df[df['type'].isin(SPENDING_TYPES)].copy()
            if len(debits) < 2:
                return []
            mean = debits['amount'].mean()
            std = debits['amount'].std()
            if pd.isna(std) or std == 0:
                return []
            debits['zscore'] = (debits['amount'] - mean) / std
            anomalies = debits[debits['zscore'].abs() > threshold]
            return anomalies[['transaction_id', 'amount', 'recipient', 'timestamp', 'zscore']].to_dict(orient='records')
        except Exception as e:
            logger.error(f"get_anomalies failed: {e}")
            return []

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
        now = now_nairobi()
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
            unique = {}
            for a in anomalies:
                unique[(a['transaction_id'], a.get('model', 'isolation_forest_v1'))] = _clamp_score(a.get('score'))
            values = [(tx_id, model, score) for (tx_id, model), score in unique.items()]
            self._execute_values(sql, values)
            return len(values)
        except Exception as e:
            logger.error(f"save_anomalies failed: {e}")
            return 0

    def get_saved_anomalies(self, days: Optional[int] = 90, limit: Optional[int] = 20) -> List[Dict]:
        since = since_nairobi(days)
        try:
            return self._fetch_all(
                """
                SELECT a.id, a.transaction_id AS tx_uuid, t.transaction_id AS transaction_id,
                       a.model, a.score, a.reviewed, a.created_at,
                       t.amount, t.recipient, t.merchant_category, t.timestamp, t.body
                FROM anomalies a
                JOIN transactions t ON t.id = a.transaction_id
                WHERE (%s::timestamp IS NULL OR t.timestamp >= %s::timestamp)
                ORDER BY a.score DESC
                LIMIT %s
                """,
                (since, since, limit),
            )
        except Exception as e:
            logger.error(f"get_saved_anomalies failed: {e}")
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
                now_nairobi(),
            ))
        except Exception as e:
            logger.error(f"upsert_budget failed: {e}")
            return None

    def get_budget_status(self) -> List[Dict]:
        try:
            return self._fetch_all("SELECT * FROM budget_status ORDER BY category, period")
        except Exception as e:
            logger.error(f"get_budget_status failed: {e}")
            return []

    def get_recent_budget_alerts(self, since_days: int = 45) -> List[Dict]:
        since = today_nairobi() - timedelta(days=since_days)
        try:
            return self._fetch_all(
                "SELECT budget_id, period_start, alert_level FROM budget_alerts WHERE period_start >= %s",
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
  - transaction_id (text, unique) - the M-Pesa reference code
  - amount (decimal) - transaction amount in KES
  - balance (decimal) - M-Pesa balance after the transaction
  - transaction_cost (decimal, NOT NULL, default 0) - M-Pesa fee charged on top of the amount; 0 when the SMS stated no fee
  - type (text) - 'credit' (money in: received, cash deposit, reversal credit), 'payment' (paid or sent to a till, paybill or person), 'withdrawal' (cash withdrawn at an agent), 'airtime' (airtime bought), 'transfer', 'debit' (other money out)
  - recipient (text) - person, merchant or sender name
  - merchant_category (text) - food, transport, utilities, banking, shopping, health, education, entertainment, savings, business, personal (money sent to or received from a person's phone number), other
  - phone (text) - phone number, may be partly masked with ***
  - body (text) - original SMS text
  - timestamp (timestamp) - transaction time in Africa/Nairobi local time, stored without a timezone
  - readable_date (text)
  - raw_date (text)
  - created_at (timestamp)

Spending means type != 'credit'. Income means type = 'credit'. Compare timestamps with
(NOW() AT TIME ZONE 'Africa/Nairobi') so dates line up with local Kenyan time.

Table: budgets (id, category, period 'weekly' or 'monthly', limit_amount, alert_threshold_pct, active)
View: budget_status (budget_id, category, period, limit_amount, alert_threshold_pct, spent_this_period)

Analytics functions (call with SELECT * FROM function_name(...) - all
parameters are optional and default to full history / no limit):
  - daily_trend_running(days INT) -> day, total_spent, total_received,
    cumulative_spent, spend_7day_avg, spend_change_from_prev_day
  - category_month_trend(months_back INT) -> month, merchant_category,
    total_amount, category_rank_in_month, prev_month_amount, mom_pct_change
  - top_merchants_ranked(days INT, limit_count INT) -> recipient,
    total_amount, transaction_count, merchant_rank, pct_of_total_spend,
    cumulative_pct
  - detect_category_anomalies(z_threshold NUMERIC, lookback_days INT) ->
    id, transaction_id, amount, recipient, merchant_category,
    tx_timestamp, category_mean, category_stddev, zscore
  - budget_pace() -> budget_id, category, period, limit_amount,
    period_start, period_end, spent_so_far, days_elapsed,
    avg_daily_spend, projected_period_spend, pct_of_limit_used, risk_rank
  - recipient_gaps(days INT) -> recipient, tx_timestamp, amount,
    prev_timestamp, days_since_prev
"""
