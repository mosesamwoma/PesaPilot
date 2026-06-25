# src/forecasting.py
"""
Spending Forecasting engine for PesaPilot.

Aggregates raw M-Pesa transactions into a daily spending series and uses
Meta's Prophet to project future spending, with an in-memory TTL cache so
the model is not retrained on every request.

This module has no knowledge of Supabase/Groq/Streamlit/FastAPI — it is a
plain function-based engine that `src/analyzer.py` calls into, matching the
existing project pattern (database.py / groq_client.py are similarly
self-contained and orchestrated by MpesaAnalyzer).
"""
import hashlib
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Minimum number of distinct days of spending history required before we'll
# trust Prophet to produce a meaningful forecast.
MIN_HISTORY_DAYS = 14

# How much spending history (in days) the analyzer should pull when building
# the daily series that feeds the model.
TRAIN_HISTORY_DAYS = 180

# How long a trained forecast result stays cached before it can be
# regenerated. New transactions invalidate the cache immediately via
# invalidate_cache(), so this TTL is just a safety net for long-idle data.
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours

TREND_INCREASING = "Increasing"
TREND_DECREASING = "Decreasing"
TREND_STABLE = "Stable"

RISK_LOW = "Low"
RISK_MODERATE = "Moderate"
RISK_HIGH = "High"


# ─────────────────────────────────────────────────────────────
# Lightweight in-memory TTL cache (mirrors the pattern already used by
# GroqClient's _ResponseCache in src/groq_client.py).
# ─────────────────────────────────────────────────────────────
class _ForecastCache:
    """Caches a trained forecast result per (data fingerprint, horizon)."""

    def __init__(self):
        self._store: Dict[str, Dict] = {}

    @staticmethod
    def _key(fingerprint: str, horizon_days: int) -> str:
        return f"{fingerprint}:{horizon_days}"

    def get(self, fingerprint: str, horizon_days: int) -> Optional[Dict]:
        key = self._key(fingerprint, horizon_days)
        entry = self._store.get(key)
        if entry and time.time() < entry["expires_at"]:
            logger.debug(f"Forecast cache HIT [{key}]")
            return entry["result"]
        if entry:
            logger.debug(f"Forecast cache MISS (expired) [{key}]")
            del self._store[key]
        return None

    def set(self, fingerprint: str, horizon_days: int, result: Dict, ttl: int = CACHE_TTL_SECONDS) -> None:
        key = self._key(fingerprint, horizon_days)
        self._store[key] = {"result": result, "expires_at": time.time() + ttl}
        logger.debug(f"Forecast cache SET [{key}] ttl={ttl}s")

    def clear(self) -> None:
        self._store.clear()
        logger.info("Forecast cache cleared")

    @property
    def size(self) -> int:
        now = time.time()
        self._store = {k: v for k, v in self._store.items() if now < v["expires_at"]}
        return len(self._store)


# Module-level singleton — shared across all callers, same pattern as Groq's cache.
_cache = _ForecastCache()


def invalidate_cache() -> None:
    """Clear all cached forecasts. Call whenever new transactions are inserted."""
    _cache.clear()


def cache_size() -> int:
    """Return number of live (non-expired) cached forecasts."""
    return _cache.size


# ─────────────────────────────────────────────────────────────
# Data preparation
# ─────────────────────────────────────────────────────────────
def build_daily_series(transactions: List[Dict]) -> pd.DataFrame:
    """
    Aggregate raw transaction rows (as returned by SupabaseDB.get_transactions)
    into a complete, zero-filled daily spending series.

    Only debit-style transactions count as "spending" (credits are excluded,
    matching the convention used throughout database.py / analyzer.py).

    Returns a DataFrame with columns ['date', 'amount'], one row per calendar
    day in the observed range (including days with zero spend), sorted
    ascending by date.
    """
    if not transactions:
        return pd.DataFrame(columns=["date", "amount"])

    df = pd.DataFrame(transactions)
    if "timestamp" not in df.columns or "amount" not in df.columns:
        return pd.DataFrame(columns=["date", "amount"])

    if "type" in df.columns:
        df = df[df["type"] != "credit"].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "amount"])

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    if df.empty:
        return pd.DataFrame(columns=["date", "amount"])

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["date"] = df["timestamp"].dt.date

    daily = df.groupby("date")["amount"].sum().reset_index()
    daily.columns = ["date", "amount"]
    daily = daily.sort_values("date")

    if daily.empty:
        return daily

    # Zero-fill any missing calendar days so Prophet sees a true daily cadence
    # rather than treating gaps as a coarser frequency.
    full_range = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    daily = daily.set_index(pd.to_datetime(daily["date"]))["amount"]
    daily = daily.reindex(full_range, fill_value=0.0)
    daily = daily.rename_axis("date").reset_index()
    daily["date"] = daily["date"].dt.date
    daily = daily[["date", "amount"]]
    return daily.reset_index(drop=True)


def _fingerprint(daily_df: pd.DataFrame) -> str:
    """
    Stable fingerprint of the training data. This makes the cache
    self-invalidating: as soon as a new day's spend (or a backdated/edited
    transaction) changes the aggregate series, the fingerprint changes and a
    fresh model is trained automatically — on top of the explicit
    invalidate_cache() calls triggered by new transaction inserts.
    """
    if daily_df.empty:
        return "empty"
    raw = (
        f"{len(daily_df)}|{daily_df['date'].min()}|{daily_df['date'].max()}|"
        f"{round(float(daily_df['amount'].sum()), 2)}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────
# Trend / risk classification
# ─────────────────────────────────────────────────────────────
def _classify_trend(predicted_values: List[float]) -> str:
    """Compare the first half vs second half of the forecast horizon."""
    if len(predicted_values) < 2:
        return TREND_STABLE

    midpoint = len(predicted_values) // 2
    first_half = predicted_values[:midpoint] or predicted_values[:1]
    second_half = predicted_values[midpoint:] or predicted_values[-1:]

    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)

    if avg_first <= 0:
        return TREND_STABLE if avg_second <= 0 else TREND_INCREASING

    change_pct = (avg_second - avg_first) / avg_first * 100
    if change_pct > 7:
        return TREND_INCREASING
    if change_pct < -7:
        return TREND_DECREASING
    return TREND_STABLE


def _classify_risk(
    forecast_total: float,
    historical_avg_daily: float,
    horizon_days: int,
    volatility_ratio: float,
) -> str:
    """
    Risk reflects how far the projected spend overshoots what the user's own
    historical pace would predict, plus how volatile their daily spending is.
    """
    baseline_total = historical_avg_daily * horizon_days
    if baseline_total <= 0:
        return RISK_LOW

    overshoot_pct = (forecast_total - baseline_total) / baseline_total * 100

    if overshoot_pct > 25 or volatility_ratio > 0.9:
        return RISK_HIGH
    if overshoot_pct > 10 or volatility_ratio > 0.6:
        return RISK_MODERATE
    return RISK_LOW


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
def generate_forecast(transactions: List[Dict], horizon_days: int = 7) -> Dict:
    """
    Train (or reuse a cached) Prophet model on daily spending history and
    return historical + forecast series, a confidence band, summary metrics,
    a trend classification, and a risk level.

    Returns a dict. When there isn't enough history, 'sufficient_data' is
    False and a human-readable 'message' explains why — callers should
    surface that message rather than attempting to read forecast fields.
    """
    daily_df = build_daily_series(transactions)

    if daily_df.empty or len(daily_df) < MIN_HISTORY_DAYS:
        history_days = len(daily_df)
        return {
            "sufficient_data": False,
            "history_days": history_days,
            "min_required_days": MIN_HISTORY_DAYS,
            "message": (
                f"Only {history_days} day(s) of spending history found — "
                f"at least {MIN_HISTORY_DAYS} days are needed for a reliable forecast. "
                f"Keep logging your M-Pesa transactions and check back soon."
            ),
        }

    fingerprint = _fingerprint(daily_df)
    cached = _cache.get(fingerprint, horizon_days)
    if cached is not None:
        return cached

    try:
        from prophet import Prophet
    except ImportError as e:
        logger.error(f"Prophet is not installed: {e}")
        return {
            "sufficient_data": False,
            "history_days": len(daily_df),
            "min_required_days": MIN_HISTORY_DAYS,
            "message": "The forecasting engine is temporarily unavailable. Please try again later.",
        }

    prophet_df = daily_df.rename(columns={"date": "ds", "amount": "y"}).copy()
    prophet_df["ds"] = pd.to_datetime(prophet_df["ds"])
    # Spending is non-negative by construction; guard against any artifacts.
    prophet_df["y"] = prophet_df["y"].clip(lower=0.0)

    try:
        weekly_seasonality = len(prophet_df) >= 14
        model = Prophet(
            growth="linear",
            daily_seasonality=False,
            weekly_seasonality=weekly_seasonality,
            yearly_seasonality=False,
            interval_width=0.80,
            changepoint_prior_scale=0.1,
        )
        model.fit(prophet_df)

        future = model.make_future_dataframe(periods=horizon_days, freq="D")
        forecast = model.predict(future)
    except Exception as e:
        logger.error(f"Prophet training/prediction failed: {e}")
        return {
            "sufficient_data": False,
            "history_days": len(daily_df),
            "min_required_days": MIN_HISTORY_DAYS,
            "message": "Could not generate a forecast from the current data. Please try again later.",
        }

    forecast["yhat"] = forecast["yhat"].clip(lower=0.0)
    forecast["yhat_lower"] = forecast["yhat_lower"].clip(lower=0.0)
    forecast["yhat_upper"] = forecast["yhat_upper"].clip(lower=0.0)

    last_history_date = prophet_df["ds"].max()
    future_forecast = forecast[forecast["ds"] > last_history_date].copy()

    historical_points = [
        {"date": str(row.date), "amount": round(float(row.amount), 2)}
        for row in daily_df.itertuples(index=False)
    ]
    forecast_points = [
        {
            "date": row.ds.strftime("%Y-%m-%d"),
            "predicted": round(float(row.yhat), 2),
            "lower": round(float(row.yhat_lower), 2),
            "upper": round(float(row.yhat_upper), 2),
        }
        for row in future_forecast.itertuples(index=False)
    ]

    predicted_values = [p["predicted"] for p in forecast_points]
    forecast_total = float(sum(predicted_values))
    historical_avg_daily = float(daily_df["amount"].mean())
    historical_std_daily = float(daily_df["amount"].std() or 0.0)
    volatility_ratio = (historical_std_daily / historical_avg_daily) if historical_avg_daily > 0 else 0.0

    trend = _classify_trend(predicted_values)
    risk_level = _classify_risk(forecast_total, historical_avg_daily, horizon_days, volatility_ratio)

    result: Dict = {
        "sufficient_data": True,
        "history_days": len(daily_df),
        "horizon_days": horizon_days,
        "historical": historical_points,
        "forecast": forecast_points,
        "total_predicted": round(forecast_total, 2),
        "avg_predicted_daily": round(forecast_total / horizon_days, 2) if horizon_days else 0.0,
        "historical_avg_daily": round(historical_avg_daily, 2),
        "historical_std_daily": round(historical_std_daily, 2),
        "trend": trend,
        "risk_level": risk_level,
        "generated_at": datetime.utcnow().isoformat(),
    }

    _cache.set(fingerprint, horizon_days, result)
    return result