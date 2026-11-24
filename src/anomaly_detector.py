import logging
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from src.frames import build_frame

logger = logging.getLogger(__name__)

MODEL_NAME = "ensemble_v2"
OBSOLETE_MODELS = ["isolation_forest_v1", "mad_fallback_v1", "category_mad"]

MIN_RECIPIENT_HISTORY = 8
MIN_CATEGORY_HISTORY = 15
MIN_SAMPLES_FOR_ML = 50
STRONG_Z = 3.5
SUPPORTED_Z = 2.5
ML_PERCENTILE = 97.0
MIN_MATERIAL_KES = 200.0
DUPLICATE_WINDOW_MIN = 10
NEW_RECIPIENT_MIN_HISTORY_DAYS = 30
ODD_HOURS = (0, 1, 2, 3, 4)
_MAD_FLOOR_RECIPIENT = 0.15
_MAD_FLOOR_CATEGORY = 0.25
_MAX_SEVERITY = 10.0


def _as_frame(data: Union[pd.DataFrame, List[Dict], None]) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data
    return build_frame(data or [])


def _robust_z(log_amount: pd.Series, group: pd.Series, min_size: int, floor: float):
    sizes = group.map(group.value_counts())
    median = log_amount.groupby(group).transform('median')
    mad = (log_amount - median).abs().groupby(group).transform('median')
    z = 0.6745 * (log_amount - median) / mad.clip(lower=floor)
    z = z.where(sizes >= min_size)
    return z, np.expm1(median).where(sizes >= min_size)


def compute_baselines(data: Union[pd.DataFrame, List[Dict]]) -> List[Dict]:
    df = _as_frame(data)
    if df.empty:
        return []
    spend = df[df['is_spend']]
    baselines = []
    for category, group in spend.groupby('merchant_category'):
        amounts = group['amount'].astype(float)
        median = float(amounts.median())
        mad = float((amounts - median).abs().median())
        std = amounts.std()
        baselines.append({
            "merchant_category": category or "other",
            "mean_amount": round(float(amounts.mean()), 2),
            "std_amount": 0.0 if pd.isna(std) else round(float(std), 2),
            "median_amount": round(median, 2),
            "mad_amount": round(mad, 2),
            "sample_size": int(len(amounts)),
        })
    return baselines


def _ml_percentiles(spend: pd.DataFrame, z: pd.Series) -> pd.Series:
    if len(spend) < MIN_SAMPLES_FOR_ML:
        return pd.Series(np.nan, index=spend.index)
    try:
        ts = spend['timestamp']
        gap = ts.diff().dt.total_seconds().fillna(86400.0).clip(lower=1.0)
        counts = spend.groupby('recipient_key')['amount'].transform('count')
        first_seen = (~spend['recipient_key'].duplicated()).astype(float)
        hour_angle = 2 * np.pi * spend['hour'] / 24.0
        features = np.column_stack([
            np.log1p(spend['amount'].values),
            np.sin(hour_angle.values), np.cos(hour_angle.values),
            spend['dow'].values,
            np.log(gap.values),
            np.log1p(counts.values),
            first_seen.values,
            z.fillna(0.0).clip(-10, 10).values,
        ])
        model = IsolationForest(n_estimators=200, contamination='auto', random_state=42)
        model.fit(features)
        raw = -model.score_samples(features)
        return pd.Series(raw, index=spend.index).rank(pct=True) * 100.0
    except Exception as e:
        logger.error(f"IsolationForest scoring failed: {e}")
        return pd.Series(np.nan, index=spend.index)


def detect_anomalies(data: Union[pd.DataFrame, List[Dict]], since: Optional[pd.Timestamp] = None) -> List[Dict]:
    df = _as_frame(data)
    if df.empty or 'id' not in df.columns:
        return []
    spend = df[df['is_spend'] & (df['amount'] > 0)].sort_values('timestamp', kind='stable')
    if spend.empty:
        return []
    spend = spend.reset_index(drop=True)

    material = max(MIN_MATERIAL_KES, float(spend['amount'].quantile(0.90)) * 1.5)
    big = max(material, float(spend['amount'].quantile(0.98)))
    sorted_amounts = np.sort(spend['amount'].values)
    log_amount = np.log1p(spend['amount'])

    z_recipient, typical_recipient = _robust_z(log_amount, spend['recipient_key'], MIN_RECIPIENT_HISTORY, _MAD_FLOOR_RECIPIENT)
    z_category, typical_category = _robust_z(log_amount, spend['merchant_category'], MIN_CATEGORY_HISTORY, _MAD_FLOOR_CATEGORY)
    use_recipient = z_recipient.notna()
    z = z_recipient.where(use_recipient, z_category)
    typical = typical_recipient.where(use_recipient, typical_category)
    basis = np.where(use_recipient, 'recipient', 'category')

    ml_pct = _ml_percentiles(spend, z)

    first_day = spend['timestamp'].min()
    hour_share = spend['hour'].value_counts(normalize=True)
    flagged: Dict[int, Dict] = {}

    def add(idx: int, severity: float, reason: str, rule: str) -> None:
        severity = float(min(_MAX_SEVERITY, max(0.0, severity)))
        entry = flagged.get(idx)
        if entry is None:
            flagged[idx] = {'severity': severity, 'reasons': [reason], 'rules': [rule]}
        else:
            entry['severity'] = max(entry['severity'], severity) + 0.5
            entry['reasons'].append(reason)
            entry['rules'].append(rule)

    for idx in spend.index[spend['amount'] >= material]:
        zi = z.at[idx]
        if pd.isna(zi) or zi < SUPPORTED_Z:
            continue
        corroborated = (not pd.isna(ml_pct.at[idx])) and ml_pct.at[idx] >= ML_PERCENTILE
        if zi < STRONG_Z and not corroborated:
            continue
        amount = float(spend.at[idx, 'amount'])
        usual = float(typical.at[idx])
        subject = (f"to {spend.at[idx, 'recipient']}" if basis[idx] == 'recipient'
                   else f"for {spend.at[idx, 'merchant_category']} payments")
        multiple = amount / usual if usual > 0 else float('inf')
        add(idx, zi + (1.5 if corroborated else 0.0),
            f"KES {amount:,.0f} is {multiple:.1f}x your usual KES {usual:,.0f} {subject}", 'amount_outlier')

    last_seen: Dict[tuple, pd.Timestamp] = {}
    seen_recipients: set = set()
    for idx, row in spend.iterrows():
        key = (row['recipient_key'], round(float(row['amount']), 2))
        previous = last_seen.get(key)
        if previous is not None and row['amount'] >= 100:
            minutes = (row['timestamp'] - previous).total_seconds() / 60.0
            if 0 <= minutes <= DUPLICATE_WINDOW_MIN:
                add(idx, 6.0, f"Possible duplicate: KES {row['amount']:,.0f} to {row['recipient']} paid again "
                              f"{minutes:.0f} min after an identical payment", 'possible_duplicate')
        last_seen[key] = row['timestamp']

        is_new = row['recipient_key'] not in seen_recipients
        seen_recipients.add(row['recipient_key'])
        history_days = (row['timestamp'] - first_day).days
        if (is_new and history_days >= NEW_RECIPIENT_MIN_HISTORY_DAYS
                and row['amount'] >= big and row['recipient_key'] != 'unknown'):
            rank = np.searchsorted(sorted_amounts, row['amount'], side='left') / len(sorted_amounts) * 100
            add(idx, 5.0 + min(row['amount'] / max(big, 1.0), 5.0) * 0.5,
                f"First payment ever to {row['recipient']}, and larger than {rank:.0f}% of your payments", 'new_large_recipient')

        if (row['hour'] in ODD_HOURS and row['amount'] >= big
                and hour_share.get(row['hour'], 0.0) < 0.02):
            add(idx, 4.0, f"KES {row['amount']:,.0f} paid at {int(row['hour']):02d}:{row['timestamp'].minute:02d}, "
                          f"an hour you rarely spend in", 'odd_hour')

    results: List[Dict] = []
    for idx, info in flagged.items():
        row = spend.loc[idx]
        if since is not None and row['timestamp'] < pd.Timestamp(since):
            continue
        results.append({
            "transaction_id": row['id'],
            "amount": float(row['amount']),
            "recipient": row['recipient'],
            "merchant_category": row['merchant_category'],
            "timestamp": row['timestamp'].isoformat(),
            "score": round(float(min(_MAX_SEVERITY, info['severity'])), 3),
            "model": MODEL_NAME,
            "reasons": info['reasons'],
            "rules": info['rules'],
        })
    results.sort(key=lambda a: (a["score"], a["amount"]), reverse=True)
    return results
