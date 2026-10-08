import pytest

from src import analyzer as analyzer_module
from src.analyzer import MpesaAnalyzer, _aggregate_query_results, _anomaly_fallback_text


class _DB:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.inserted = []
        self.budgets = []

    def transaction_exists(self, tx_id):
        return tx_id in self.existing

    def insert_transactions(self, df, overwrite=True):
        self.inserted.append((df, overwrite))
        return len(df)

    def upsert_budget(self, category, limit_amount, period, alert_threshold_pct):
        self.budgets.append((category, limit_amount, period, alert_threshold_pct))
        return {'category': category}


class _Groq:
    def invalidate_cache(self):
        pass


@pytest.fixture
def analyzer():
    instance = MpesaAnalyzer.__new__(MpesaAnalyzer)
    instance.db = _DB()
    instance.groq = _Groq()
    instance._cache = {}
    return instance


SMS = (
    "AB12CD34EF Confirmed. Ksh1,500.00 sent to JANE  DOE 0712345678 on 3/10/24 at 12:40 PM. "
    "New M-PESA balance is Ksh2,340.50. Transaction cost, Ksh23.00."
)


def test_manual_sms_is_inserted_without_overwriting(analyzer):
    result = analyzer.parse_and_insert_sms(SMS)
    assert result['success'] is True
    df, overwrite = analyzer.db.inserted[0]
    assert overwrite is False
    assert df.iloc[0]['timestamp'].startswith('2024-10-03T12:40')


def test_manual_sms_duplicate_is_reported_not_overwritten(analyzer):
    analyzer.db = _DB(existing={'AB12CD34EF'})
    result = analyzer.parse_and_insert_sms(SMS)
    assert result['success'] is False
    assert 'already recorded' in result['summary']
    assert analyzer.db.inserted == []


def test_manual_sms_that_is_not_a_transaction(analyzer):
    result = analyzer.parse_and_insert_sms('Failed. The till number entered is incorrect.')
    assert result['success'] is False


@pytest.mark.parametrize('kwargs,fragment', [
    ({'category': 'spaceships', 'limit_amount': 100}, 'Unknown category'),
    ({'category': 'food', 'limit_amount': 0}, 'greater than 0'),
    ({'category': 'food', 'limit_amount': 100, 'period': 'daily'}, 'weekly'),
    ({'category': 'food', 'limit_amount': 100, 'alert_threshold_pct': 150}, 'between 1 and 100'),
])
def test_set_budget_validation(analyzer, kwargs, fragment):
    result = analyzer.set_budget(**kwargs)
    assert result['success'] is False and fragment in result['error']
    assert analyzer.db.budgets == []


def test_set_budget_normalizes_category_and_period(analyzer):
    assert analyzer.set_budget('Groceries', 5000, ' Weekly ')['success'] is True
    assert analyzer.db.budgets == [('food', 5000, 'weekly', 80)]


def test_cache_expires(analyzer, monkeypatch):
    analyzer._cache_set('k', 1)
    assert analyzer._cache_get('k') == 1
    monkeypatch.setattr(analyzer_module.time, 'time', lambda: 10 ** 12)
    assert analyzer._cache_get('k') is None


def test_anomaly_fallback_lists_largest_first():
    text = _anomaly_fallback_text([
        {'amount': 100, 'recipient': 'A', 'timestamp': '2026-01-01T00:00:00'},
        {'amount': 900, 'recipient': 'B', 'timestamp': '2026-01-02T00:00:00'},
    ])
    assert text.index('B') < text.index('- KES 100')


def test_aggregate_query_results_groups_by_category():
    agg = _aggregate_query_results([
        {'merchant_category': 'food', 'amount': 10.0},
        {'merchant_category': 'food', 'amount': 5.0},
        {'merchant_category': 'other', 'amount': 1.0},
    ])
    assert agg['row_count'] == 3
    assert agg['by_merchant_category'][0] == {'key': 'food', 'total': 15.0}
    assert _aggregate_query_results([]) == {'row_count': 0}
