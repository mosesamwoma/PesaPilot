import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.database import PostgresDB
from tests.conftest import require_test_database

pytestmark = pytest.mark.integration


@pytest.fixture(scope='module', autouse=True)
def _check_prereqs():
    require_test_database()


@pytest.fixture(scope='module')
def db():
    instance = PostgresDB()
    yield instance
    instance.close()


def test_connection(db):
    assert db._pool is not None


def test_get_schema(db):
    schema = db.get_schema()
    assert 'transactions' in schema
    assert 'amount' in schema
    assert 'type' in schema


def test_get_summary_returns_dict(db):
    summary = db.get_summary()
    assert isinstance(summary, dict)


def test_get_summary_keys(db):
    summary = db.get_summary()
    if summary:
        expected = ['total_transactions', 'total_spent', 'total_received', 'avg_spend']
        for key in expected:
            assert key in summary, f"Missing key: {key}"


def test_get_transactions_returns_list(db):
    txs = db.get_transactions(days=90)
    assert isinstance(txs, list)


def test_get_transactions_fields(db):
    txs = db.get_transactions(days=365, limit=5)
    if txs:
        tx = txs[0]
        assert 'amount' in tx
        assert 'type' in tx


def test_get_spending_by_category(db):
    result = db.get_spending_by_category(days=90)
    assert isinstance(result, list)


def test_get_daily_trend(db):
    result = db.get_daily_trend(days=30)
    assert isinstance(result, list)


def test_get_top_merchants(db):
    result = db.get_top_merchants(days=90)
    assert isinstance(result, list)


def test_get_anomalies(db):
    result = db.get_anomalies()
    assert isinstance(result, list)


def test_insert_and_retrieve(db):
    import pandas as pd
    from datetime import datetime

    test_tx_id = 'PYTEST_TEST_TX_0000001'
    dummy = pd.DataFrame([{
        'transaction_id': test_tx_id,
        'amount': 999.00,
        'balance': 5000.00,
        'type': 'payment',
        'recipient': 'Test Merchant',
        'merchant_category': 'other',
        'phone': '0700000000',
        'body': 'Test SMS body',
        'timestamp': datetime.now().isoformat(),
        'readable_date': '01/06/2026 12:00:00',
        'raw_date': '1748779200000',
    }])

    try:
        count = db.insert_transactions(dummy)
        assert count == 1

        txs = db.get_transactions(days=1, limit=10)
        ids = [t.get('transaction_id') for t in txs]
        assert test_tx_id in ids
    finally:
        db._execute(
            "DELETE FROM transactions WHERE transaction_id = %s",
            (test_tx_id,),
        )


def test_insert_and_retrieve_cleans_up(db):
    test_tx_id = 'PYTEST_TEST_TX_0000001'
    remaining = db._fetch_all(
        "SELECT transaction_id FROM transactions WHERE transaction_id = %s",
        (test_tx_id,),
    )
    assert remaining == []
