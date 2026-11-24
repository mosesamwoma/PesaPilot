import hashlib
import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from src.frames import build_frame, daily_spend
from src.timeutil import today_nairobi

logger = logging.getLogger(__name__)

MIN_HISTORY_DAYS = 14
TRAIN_HISTORY_DAYS = 180
MAX_HORIZON_DAYS = 60
CACHE_TTL_SECONDS = 6 * 60 * 60
BACKTEST_FOLDS = 5
CAP_QUANTILE = 0.97

TREND_INCREASING = "Increasing"
TREND_DECREASING = "Decreasing"
TREND_STABLE = "Stable"

RISK_LOW = "Low"
RISK_MODERATE = "Moderate"
RISK_HIGH = "High"

_lock = threading.RLock()
_cache: Dict[str, Dict] = {}


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()
    logger.info("Forecast cache cleared")


def cache_size() -> int:
    with _lock:
        now = time.time()
        for key in [k for k, v in _cache.items() if v['expires_at'] <= now]:
            del _cache[key]
        return len(_cache)


def build_daily_series(transactions: Union[List[Dict], pd.DataFrame]) -> pd.DataFrame:
    frame = transactions if isinstance(transactions, pd.DataFrame) and 'is_spend' in transactions.columns \
        else build_frame(transactions if not isinstance(transactions, pd.DataFrame) else transactions.to_dict('records'))
    today = pd.Timestamp(today_nairobi())
    if frame.empty:
        return pd.DataFrame(columns=["date", "amount"])
    complete = frame[frame['date'] < today]
    series = daily_spend(complete, end=today - pd.Timedelta(days=1)) if not complete.empty else pd.Series(dtype=float)
    if series.empty:
        return pd.DataFrame(columns=["date", "amount"])
    out = series.rename_axis('date').reset_index(name='amount')
    out['date'] = out['date'].dt.date
    return out


def _fingerprint(daily: pd.Series) -> str:
    raw = f"{len(daily)}|{daily.index.min()}|{daily.index.max()}|{round(float(daily.sum()), 2)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cap(series: pd.Series) -> float:
    positive = series[series > 0]
    if len(positive) < 10:
        return float(series.max()) if len(series) else 0.0
    return float(positive.quantile(CAP_QUANTILE))


def _stat_predict(history: pd.Series, horizon: int, with_tail: bool = True) -> pd.Series:
    capped = history.clip(upper=_cap(history))
    level = float(capped.ewm(halflife=21, adjust=False).mean().iloc[-1])
    recent = capped.tail(84)
    overall = float(recent.mean())
    if overall > 0:
        raw = recent.groupby(recent.index.dayofweek).mean().reindex(range(7)).fillna(overall) / overall
        factors = 1 + 0.6 * (raw - 1)
        factors = factors / factors.mean()
    else:
        factors = pd.Series(1.0, index=range(7))
    future = pd.date_range(history.index[-1] + pd.Timedelta(days=1), periods=horizon, freq='D')
    pred = pd.Series([level * float(factors[d.dayofweek]) for d in future], index=future)
    if with_tail:
        tail = float((history - _cap(history)).clip(lower=0).tail(TRAIN_HISTORY_DAYS).mean())
        pred = pred + tail
    return pred


def _prophet_predict(history: pd.Series, horizon: int) -> Optional[pd.Series]:
    try:
        from prophet import Prophet
    except ImportError as e:
        logger.warning(f"Prophet is not installed, using the statistical model only: {e}")
        return None
    try:
        for name in ('cmdstanpy', 'prophet'):
            logging.getLogger(name).setLevel(logging.WARNING)
        capped = history.clip(upper=_cap(history))
        train = pd.DataFrame({'ds': capped.index, 'y': capped.values})
        model = Prophet(
            growth='linear', daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=False,
            interval_width=0.80, changepoint_prior_scale=0.05,
        )
        model.fit(train)
        future = model.make_future_dataframe(periods=horizon, freq='D')
        out = model.predict(future)
        out = out[out['ds'] > history.index[-1]]
        pred = pd.Series(out['yhat'].clip(lower=0.0).values, index=pd.DatetimeIndex(out['ds']))
        tail = float((history - _cap(history)).clip(lower=0).tail(TRAIN_HISTORY_DAYS).mean())
        return pred + tail
    except Exception as e:
        logger.error(f"Prophet training/prediction failed: {e}")
        return None


def _backtest(daily: pd.Series, use_prophet: bool) -> Dict:
    n = len(daily)
    stat_err, prophet_err, actuals, stat_preds, prophet_preds = 0.0, 0.0, 0.0, [], []
    folds = 0
    for k in range(1, BACKTEST_FOLDS + 1):
        origin = n - 7 * k
        if origin < MIN_HISTORY_DAYS:
            break
        history, actual = daily.iloc[:origin], float(daily.iloc[origin:origin + 7].sum())
        sp = float(_stat_predict(history, 7).sum())
        stat_err += abs(sp - actual)
        actuals += actual
        stat_preds.append(sp)
        if use_prophet:
            pp = _prophet_predict(history, 7)
            if pp is None:
                use_prophet = False
            else:
                prophet_err += abs(float(pp.sum()) - actual)
                prophet_preds.append(float(pp.sum()))
        folds += 1
    if folds == 0 or actuals <= 0:
        return {'folds': 0, 'stat_error_pct': None, 'prophet_error_pct': None, 'use_prophet': use_prophet}
    return {
        'folds': folds,
        'stat_error_pct': stat_err / actuals * 100,
        'prophet_error_pct': (prophet_err / actuals * 100) if use_prophet and len(prophet_preds) == folds else None,
        'use_prophet': use_prophet and len(prophet_preds) == folds,
    }


def _blend_weights(backtest: Dict) -> Dict[str, float]:
    stat, prophet = backtest.get('stat_error_pct'), backtest.get('prophet_error_pct')
    if prophet is None:
        return {'stat': 1.0, 'prophet': 0.0}
    if stat is None:
        return {'stat': 0.0, 'prophet': 1.0}
    inv_s, inv_p = 1 / max(stat, 5.0) ** 2, 1 / max(prophet, 5.0) ** 2
    w_p = min(0.8, max(0.2, inv_p / (inv_s + inv_p)))
    return {'stat': 1 - w_p, 'prophet': w_p}


def _error_distribution(daily: pd.Series, horizons: List[int]) -> Dict:
    n = len(daily)
    ratios: Dict[int, List[float]] = {h: [] for h in horizons}
    residuals: List[float] = []
    longest = max(horizons)
    for origin in range(max(MIN_HISTORY_DAYS, 28), n, 2):
        history = daily.iloc[:origin]
        pred = _stat_predict(history, min(longest, n - origin) or 1)
        residuals.append(float(daily.iloc[origin]) - float(pred.iloc[0]))
        for h in horizons:
            if origin + h <= n:
                total = float(_stat_predict(history, h).sum())
                if total > 0:
                    ratios[h].append(float(daily.iloc[origin:origin + h].sum()) / total)
    out: Dict = {'ratios': {}, 'daily_lo': None, 'daily_hi': None}
    for h, values in ratios.items():
        if len(values) >= 8:
            out['ratios'][h] = (float(np.quantile(values, 0.10)), float(np.quantile(values, 0.90)))
    if len(residuals) >= 20:
        out['daily_lo'], out['daily_hi'] = float(np.quantile(residuals, 0.10)), float(np.quantile(residuals, 0.90))
    return out


def _classify_trend(forecast_avg_daily: float, recent_avg_daily: float) -> str:
    if recent_avg_daily <= 0:
        return TREND_STABLE if forecast_avg_daily <= 0 else TREND_INCREASING
    change = (forecast_avg_daily - recent_avg_daily) / recent_avg_daily * 100
    if change > 10:
        return TREND_INCREASING
    if change < -10:
        return TREND_DECREASING
    return TREND_STABLE


def _classify_risk(forecast_avg_daily: float, baseline_daily: float, weekly_cv: float) -> str:
    if baseline_daily <= 0:
        return RISK_LOW
    overshoot = (forecast_avg_daily - baseline_daily) / baseline_daily * 100
    if overshoot > 25 or weekly_cv > 1.0:
        return RISK_HIGH
    if overshoot > 10 or weekly_cv > 0.6:
        return RISK_MODERATE
    return RISK_LOW


def _insufficient(history_days: int, message: str) -> Dict:
    return {"sufficient_data": False, "history_days": history_days, "min_required_days": MIN_HISTORY_DAYS,
            "message": message}


def generate_forecast(transactions: Union[List[Dict], pd.DataFrame], horizon_days: int = 7) -> Dict:
    horizon_days = max(1, min(int(horizon_days), MAX_HORIZON_DAYS))
    table = build_daily_series(transactions)
    if table.empty or len(table) < MIN_HISTORY_DAYS:
        n = len(table)
        return _insufficient(n, (
            f"Only {n} day(s) of spending history found: at least {MIN_HISTORY_DAYS} days are needed for a "
            f"reliable forecast. Keep logging your M-Pesa transactions and check back soon."))

    daily = pd.Series(table['amount'].astype(float).values, index=pd.to_datetime(table['date']))
    daily = daily.tail(TRAIN_HISTORY_DAYS)
    fingerprint = _fingerprint(daily)

    with _lock:
        entry = _cache.get(fingerprint)
        if entry is not None and entry['expires_at'] <= time.time():
            del _cache[fingerprint]
            entry = None
        if entry is None:
            backtest = _backtest(daily, use_prophet=True)
            weights = _blend_weights(backtest)
            stat_future = _stat_predict(daily, MAX_HORIZON_DAYS)
            prophet_future = _prophet_predict(daily, MAX_HORIZON_DAYS) if weights['prophet'] > 0 else None
            if prophet_future is None:
                weights = {'stat': 1.0, 'prophet': 0.0}
            blended = stat_future * weights['stat'] + (prophet_future * weights['prophet'] if prophet_future is not None else 0.0)
            entry = {
                'blended': blended, 'weights': weights, 'backtest': backtest,
                'errors': _error_distribution(daily, [7, 14, 30, horizon_days] if horizon_days not in (7, 14, 30) else [7, 14, 30]),
                'expires_at': time.time() + CACHE_TTL_SECONDS,
                'horizons_done': {7, 14, 30} | {horizon_days},
            }
            _cache[fingerprint] = entry
        elif horizon_days not in entry['horizons_done']:
            extra = _error_distribution(daily, [horizon_days])
            entry['errors']['ratios'].update(extra['ratios'])
            entry['horizons_done'].add(horizon_days)

    future = entry['blended'].iloc[:horizon_days]
    errors = entry['errors']
    total = float(future.sum())

    lo_hi = errors['ratios'].get(horizon_days)
    if lo_hi is None:
        std = float(daily.std() or 0.0) * math.sqrt(horizon_days)
        total_lower, total_upper = max(0.0, total - 1.28 * std), total + 1.28 * std
    else:
        total_lower, total_upper = total * lo_hi[0], total * max(lo_hi[1], 1.0)
    d_lo, d_hi = errors['daily_lo'], errors['daily_hi']

    forecast_points = []
    for stamp, value in future.items():
        lower = max(0.0, value + d_lo) if d_lo is not None else 0.0
        upper = value + d_hi if d_hi is not None else value * 2
        forecast_points.append({
            "date": stamp.strftime("%Y-%m-%d"),
            "predicted": round(float(value), 2),
            "lower": round(float(min(lower, value)), 2),
            "upper": round(float(max(upper, value)), 2),
        })
    historical_points = [{"date": idx.strftime("%Y-%m-%d"), "amount": round(float(v), 2)} for idx, v in daily.items()]

    forecast_avg = total / horizon_days
    recent_avg = float(daily.tail(28).mean())
    baseline_avg = float(daily.tail(90).mean())
    weekly = daily.resample('W-SUN').sum().iloc[:-1] if len(daily) >= 35 else daily.resample('W-SUN').sum()
    weekly_cv = float(weekly.std() / weekly.mean()) if len(weekly) >= 3 and weekly.mean() > 0 else 0.0

    backtest = entry['backtest']
    weights = entry['weights']
    scores = {'statistical': backtest.get('stat_error_pct'), 'prophet': backtest.get('prophet_error_pct')}
    errors_known = [v for v in (scores['statistical'], scores['prophet']) if v is not None]
    best_error = min(errors_known) if errors_known else None
    if best_error is None or backtest.get('folds', 0) < 3 or len(daily) < 28:
        confidence = "Low"
    else:
        confidence = "High" if best_error <= 25 else "Medium" if best_error <= 45 else "Low"
    model_used = 'Prophet + seasonal model ensemble' if weights['prophet'] > 0 else 'Robust seasonal model'

    return {
        "sufficient_data": True,
        "history_days": len(daily),
        "horizon_days": horizon_days,
        "historical": historical_points,
        "forecast": forecast_points,
        "total_predicted": round(total, 2),
        "total_lower": round(float(total_lower), 2),
        "total_upper": round(float(total_upper), 2),
        "avg_predicted_daily": round(forecast_avg, 2),
        "historical_avg_daily": round(float(daily.mean()), 2),
        "recent_avg_daily": round(recent_avg, 2),
        "historical_std_daily": round(float(daily.std() or 0.0), 2),
        "trend": _classify_trend(forecast_avg, recent_avg),
        "risk_level": _classify_risk(forecast_avg, baseline_avg, weekly_cv),
        "confidence": confidence,
        "model": model_used,
        "model_weights": {k: round(v, 2) for k, v in weights.items()},
        "backtest": {
            "folds": backtest.get('folds', 0),
            "error_pct_7d": None if best_error is None else round(best_error, 1),
            "statistical_error_pct": None if scores['statistical'] is None else round(scores['statistical'], 1),
            "prophet_error_pct": None if scores['prophet'] is None else round(scores['prophet'], 1),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
