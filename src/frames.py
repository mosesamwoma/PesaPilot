import re
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd

from src.constants import SPENDING_TYPES

FRAME_COLUMNS = [
    'id', 'transaction_id', 'amount', 'balance', 'transaction_cost', 'type', 'recipient', 'merchant_category',
    'phone', 'timestamp', 'is_spend', 'is_income', 'date', 'weekday', 'dow', 'hour', 'month', 'recipient_key',
]

DAY_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

_KEY_STRIP_RE = re.compile(r'[^a-z0-9& ]+')
_SPACE_RE = re.compile(r'\s+')


def recipient_key(name) -> str:
    cleaned = _KEY_STRIP_RE.sub(' ', str(name or '').lower())
    return _SPACE_RE.sub(' ', cleaned).strip() or 'unknown'


def empty_frame() -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype='object') for c in FRAME_COLUMNS})
    for col in ('amount', 'balance', 'transaction_cost'):
        frame[col] = frame[col].astype(float)
    frame['timestamp'] = pd.to_datetime(frame['timestamp'])
    frame['date'] = pd.to_datetime(frame['date'])
    frame['month'] = pd.to_datetime(frame['month'])
    frame['is_spend'] = frame['is_spend'].astype(bool)
    frame['is_income'] = frame['is_income'].astype(bool)
    return frame


def build_frame(rows: Iterable[Dict]) -> pd.DataFrame:
    rows = list(rows or [])
    if not rows:
        return empty_frame()

    df = pd.DataFrame(rows)
    if 'timestamp' not in df.columns or 'amount' not in df.columns or 'type' not in df.columns:
        return empty_frame()

    df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601', errors='coerce')
    df = df.dropna(subset=['timestamp']).copy()
    if df.empty:
        return empty_frame()

    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0).astype(float)
    for col in ('balance', 'transaction_cost'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype(float)
        else:
            df[col] = np.nan
    df['transaction_cost'] = df['transaction_cost'].fillna(0.0)

    for col, default in (('recipient', 'Unknown'), ('merchant_category', 'other')):
        if col in df.columns:
            df[col] = df[col].where(df[col].notna(), default).astype(str)
            df[col] = df[col].replace('', default)
        else:
            df[col] = default
    for col in ('id', 'transaction_id', 'phone'):
        if col not in df.columns:
            df[col] = None

    df['type'] = df['type'].astype(str)
    df['is_spend'] = df['type'].isin(SPENDING_TYPES)
    df['is_income'] = df['type'] == 'credit'
    df['date'] = df['timestamp'].dt.normalize()
    df['weekday'] = df['timestamp'].dt.day_name()
    df['dow'] = df['timestamp'].dt.dayofweek
    df['hour'] = df['timestamp'].dt.hour
    df['month'] = df['timestamp'].dt.to_period('M').dt.to_timestamp()
    df['recipient_key'] = df['recipient'].map(recipient_key)

    df = df.sort_values('timestamp', kind='stable').reset_index(drop=True)
    return df[FRAME_COLUMNS]


def spend_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df['is_spend']] if not df.empty else df


def income_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df['is_income']] if not df.empty else df


def daily_spend(df: pd.DataFrame, start=None, end=None) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    spend = df[df['is_spend']]
    if spend.empty:
        return pd.Series(dtype=float)
    series = spend.groupby('date')['amount'].sum()
    first = pd.Timestamp(start).normalize() if start is not None else series.index.min()
    last = pd.Timestamp(end).normalize() if end is not None else series.index.max()
    if last < first:
        return pd.Series(dtype=float)
    return series.reindex(pd.date_range(first, last, freq='D'), fill_value=0.0)


def to_records(df: pd.DataFrame, columns: List[str]) -> List[Dict]:
    return df[columns].to_dict(orient='records') if not df.empty else []
