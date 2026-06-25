# tests/test_forecasting.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
import pytest
from src import forecasting


def _make_transactions(num_days: int, start: datetime.date = datetime.date(2026, 1, 1)):
    """Build synthetic debit transactions spanning `num_days` distinct days."""
    txs = []
    for i in range(num_days):
        d = start + datetime.timedelta(days=i)
        txs.append({
            'timestamp': f'{d}T12:00:00',
            'amount': 100 + i,
            'type': 'debit',
        })
    return txs


def test_build_daily_series_empty():
    df = forecasting.build_daily_series([])
    assert df.empty


def test_build_daily_series_excludes_credits():
    txs = [
        {'timestamp': '2026-01-01T10:00:00', 'amount': 500, 'type': 'credit'},
        {'timestamp': '2026-01-01T11:00:00', 'amount': 200, 'type': 'debit'},
    ]
    df = forecasting.build_daily_series(txs)
    assert len(df) == 1
    assert float(df.iloc[0]['amount']) == 200.0


def test_build_daily_series_zero_fills_gaps():
    txs = [
        {'timestamp': '2026-01-01T10:00:00', 'amount': 100, 'type': 'debit'},
        {'timestamp': '2026-01-03T10:00:00', 'amount': 200, 'type': 'debit'},
    ]
    df = forecasting.build_daily_series(txs)
    assert len(df) == 3
    assert float(df.iloc[1]['amount']) == 0.0


def test_generate_forecast_insufficient_data():
    txs = _make_transactions(5)
    result = forecasting.generate_forecast(txs, horizon_days=7)
    assert result['sufficient_data'] is False
    assert result['history_days'] == 5
    assert 'message' in result


def test_generate_forecast_no_transactions():
    result = forecasting.generate_forecast([], horizon_days=7)
    assert result['sufficient_data'] is False


def test_classify_trend_increasing():
    assert forecasting._classify_trend([10, 10, 20, 20]) == forecasting.TREND_INCREASING


def test_classify_trend_decreasing():
    assert forecasting._classify_trend([20, 20, 10, 10]) == forecasting.TREND_DECREASING


def test_classify_trend_stable():
    assert forecasting._classify_trend([10, 10, 10, 10]) == forecasting.TREND_STABLE


def test_classify_trend_too_short():
    assert forecasting._classify_trend([10]) == forecasting.TREND_STABLE


def test_classify_risk_low():
    risk = forecasting._classify_risk(forecast_total=700, historical_avg_daily=100, horizon_days=7, volatility_ratio=0.1)
    assert risk == forecasting.RISK_LOW


def test_classify_risk_high_overshoot():
    risk = forecasting._classify_risk(forecast_total=1000, historical_avg_daily=100, horizon_days=7, volatility_ratio=0.1)
    assert risk == forecasting.RISK_HIGH


def test_classify_risk_high_volatility():
    risk = forecasting._classify_risk(forecast_total=700, historical_avg_daily=100, horizon_days=7, volatility_ratio=0.95)
    assert risk == forecasting.RISK_HIGH


def test_classify_risk_zero_baseline():
    risk = forecasting._classify_risk(forecast_total=500, historical_avg_daily=0, horizon_days=7, volatility_ratio=0.5)
    assert risk == forecasting.RISK_LOW


def test_cache_roundtrip():
    forecasting.invalidate_cache()
    fake_result = {'sufficient_data': True, 'total_predicted': 123.0}
    forecasting._cache.set('fingerprint-abc', 7, fake_result)
    cached = forecasting._cache.get('fingerprint-abc', 7)
    assert cached == fake_result
    forecasting.invalidate_cache()
    assert forecasting._cache.get('fingerprint-abc', 7) is None


@pytest.mark.skipif(
    not pytest.importorskip("prophet", reason="prophet not installed"),
    reason="prophet not installed"
)
def test_generate_forecast_with_prophet():
    """Full end-to-end forecast when Prophet is available in the environment."""
    txs = _make_transactions(40)
    result = forecasting.generate_forecast(txs, horizon_days=7)
    assert result['sufficient_data'] is True
    assert len(result['forecast']) == 7
    assert result['trend'] in (
        forecasting.TREND_INCREASING, forecasting.TREND_DECREASING, forecasting.TREND_STABLE
    )
    assert result['risk_level'] in (
        forecasting.RISK_LOW, forecasting.RISK_MODERATE, forecasting.RISK_HIGH
    )