import os

import pytest

pytestmark = pytest.mark.skipif(
    'test' not in os.getenv('POSTGRES_DB', '').lower(),
    reason="Needs a disposable PostgreSQL database whose name contains 'test' (POSTGRES_DB=pesapilot_test).",
)


@pytest.fixture(scope='module')
def db(real_transactions):
    from src.database import PostgresDB
    instance = PostgresDB()
    instance.insert_transactions(real_transactions)
    yield instance
    instance.close()


def test_all_parsed_rows_are_stored(db, real_transactions):
    row = db._fetch_one("SELECT COUNT(*) AS n FROM transactions WHERE transaction_id = ANY(%s)",
                        (list(real_transactions['transaction_id']),))
    assert row['n'] == len(real_transactions)


def test_all_time_summary_matches_parsed_data(db, real_transactions):
    summary = db.get_range_summary(days=None)
    credits = real_transactions[real_transactions['type'] == 'credit']['amount'].sum()
    assert summary['total_received'] == pytest.approx(credits)
    assert summary['total_spent'] == pytest.approx(real_transactions['amount'].sum() - credits)
    assert summary['span_days'] > 365


def test_category_totals_add_up_to_total_spent(db):
    total = db.get_range_summary(days=None)['total_spent']
    by_category = sum(c['total_amount'] for c in db.get_spending_by_category(days=None))
    assert by_category == pytest.approx(total)


def test_top_merchants_limit(db):
    assert len(db.get_top_merchants(days=None, limit=3)) == 3
    assert len(db.get_top_merchants(days=None, limit=None)) > 3


def test_execute_query_is_read_only_and_guarded(db):
    assert db.execute_query("SELECT COUNT(*) AS n FROM transactions")[0]['n'] > 0
    assert db.execute_query("SELECT pg_sleep(1)") == []
    assert db.execute_query("DELETE FROM transactions") == []
    assert db.execute_query("SELECT COUNT(*) AS n FROM transactions WHERE recipient ILIKE '%delete; --%'")[0]['n'] == 0
    assert db.execute_query("SELECT 1 AS one; DROP TABLE transactions") == []
    assert db.execute_query("WITH x AS (SELECT amount FROM transactions) SELECT SUM(amount) AS s FROM x")[0]['s'] > 0


def test_sql_analytics_functions_run(db):
    for call in ("daily_trend_running(7)", "category_month_trend(3)", "top_merchants_ranked(30, 3)",
                 "detect_category_anomalies(2.5, 90)", "recipient_gaps(90)", "budget_pace()"):
        assert isinstance(db._fetch_all(f"SELECT * FROM {call}"), list)


def test_timestamps_are_stored_in_nairobi_time(db):
    row = db._fetch_one("SELECT MIN(timestamp) AS first_seen FROM transactions")
    assert row['first_seen'].startswith('2024-10-03T12:40')


def test_saved_anomalies_join_back_to_transactions(db):
    from src.analyzer import MpesaAnalyzer
    analyzer = MpesaAnalyzer.__new__(MpesaAnalyzer)
    analyzer.db = db
    analyzer._cache = {}

    class _Groq:
        def generate_anomaly_insights(self, anomalies):
            return 'ok'

    analyzer.groq = _Groq()
    result = analyzer.get_smart_anomalies(days=None, force_refresh=True)
    assert result['count'] == len(result['anomalies']) > 0
    assert all(b['std_amount'] == b['std_amount'] for b in result['baselines'])
    assert db._fetch_one("SELECT COUNT(*) AS n FROM spending_baselines WHERE std_amount = 'NaN'")['n'] == 0
    first = result['anomalies'][0]
    assert first['transaction_id'] and first['amount'] > 0 and first['recipient']


def test_paybill_payments_with_phone_accounts_are_not_personal(db):
    row = db._fetch_one(
        "SELECT COUNT(*) AS n FROM transactions "
        "WHERE merchant_category = 'personal' AND type <> 'credit' AND body ILIKE %s",
        ('%for account%',),
    )
    assert row['n'] == 0
