import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

MIN_SAMPLES_FOR_ML = 8

CONTAMINATION = 0.08

MAD_FLAG_THRESHOLD = 3.5

MODEL_NAME = "isolation_forest_v1"
FALLBACK_MODEL_NAME = "mad_fallback_v1"

DEBIT_TYPES = {"debit", "payment", "withdrawal", "transfer", "airtime"}


def _feature_matrix(df: pd.DataFrame) -> np.ndarray:
    amount = df["amount"].astype(float)
    median = amount.median() or 1.0
    hour = df["timestamp"].dt.hour.fillna(12)
    dow = df["timestamp"].dt.dayofweek.fillna(0)
    ratio = amount / median

    return np.column_stack([
        amount.values,
        np.log1p(amount.values),
        hour.values,
        dow.values,
        ratio.values,
    ])


def _mad_scores(amounts: pd.Series) -> Tuple[pd.Series, float, float]:
    median = amounts.median()
    mad = (amounts - median).abs().median()
    if mad == 0:
        return pd.Series([0.0] * len(amounts), index=amounts.index), median, mad
    modified_z = 0.6745 * (amounts - median).abs() / mad
    return modified_z, median, mad


def compute_baselines(transactions: List[Dict]) -> List[Dict]:
    if not transactions:
        return []

    df = pd.DataFrame(transactions)
    if df.empty or "amount" not in df.columns or "type" not in df.columns:
        return []

    df = df[df["type"].isin(DEBIT_TYPES)].copy()
    df["merchant_category"] = df.get("merchant_category", "other").fillna("other")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["amount"])

    baselines = []
    for category, group in df.groupby("merchant_category"):
        amounts = group["amount"]
        _, median, mad = _mad_scores(amounts)
        baselines.append({
            "merchant_category": category or "other",
            "mean_amount": round(float(amounts.mean()), 2),
            "std_amount": round(float(amounts.std() or 0), 2),
            "median_amount": round(float(median), 2),
            "mad_amount": round(float(mad), 2),
            "sample_size": int(len(amounts)),
        })
    return baselines


def detect_anomalies(transactions: List[Dict]) -> List[Dict]:
    if not transactions:
        return []

    df = pd.DataFrame(transactions)
    required_cols = {"amount", "type", "id"}
    if df.empty or not required_cols.issubset(df.columns):
        return []

    df = df[df["type"].isin(DEBIT_TYPES)].copy()
    if df.empty:
        return []

    df["merchant_category"] = df.get("merchant_category", "other").fillna("other")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df.get("timestamp"), format='ISO8601', errors="coerce")
    df = df.dropna(subset=["amount", "timestamp"])
    if df.empty:
        return []

    flagged: List[Dict] = []

    for category, group in df.groupby("merchant_category"):
        group = group.reset_index(drop=True)

        if len(group) >= MIN_SAMPLES_FOR_ML:
            try:
                X = _feature_matrix(group)
                model = IsolationForest(
                    n_estimators=150,
                    contamination=CONTAMINATION,
                    random_state=42,
                )
                model.fit(X)
                predictions = model.predict(X)
                raw_scores = model.decision_function(X)

                for i, is_outlier in enumerate(predictions):
                    if is_outlier != -1:
                        continue
                    row = group.iloc[i]
                    anomaly_score = round(float(-raw_scores[i] * 10), 3)
                    flagged.append({
                        "transaction_id": row["id"],
                        "amount": float(row["amount"]),
                        "recipient": row.get("recipient", "Unknown"),
                        "merchant_category": category,
                        "timestamp": row["timestamp"].isoformat() if pd.notna(row["timestamp"]) else None,
                        "score": anomaly_score,
                        "model": MODEL_NAME,
                    })
            except Exception as e:
                logger.error(f"IsolationForest failed for category={category}: {e}")
        else:
            modified_z, _, _ = _mad_scores(group["amount"])
            for i, z in modified_z.items():
                if z <= MAD_FLAG_THRESHOLD:
                    continue
                row = group.iloc[i]
                flagged.append({
                    "transaction_id": row["id"],
                    "amount": float(row["amount"]),
                    "recipient": row.get("recipient", "Unknown"),
                    "merchant_category": category,
                    "timestamp": row["timestamp"].isoformat() if pd.notna(row["timestamp"]) else None,
                    "score": round(float(z), 3),
                    "model": FALLBACK_MODEL_NAME,
                })

    flagged.sort(key=lambda a: a["score"], reverse=True)
    return flagged
