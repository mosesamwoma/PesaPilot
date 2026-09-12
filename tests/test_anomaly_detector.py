import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from src import anomaly_detector


def _tx(id_, amount, category='food', tx_type='payment', days_ago=0):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        'id': id_,
        'amount': amount,
        'type': tx_type,
        'merchant_category': category,
        'recipient': 'Test Merchant',
        'timestamp': ts,
    }


def test_compute_baselines_empty():
    assert anomaly_detector.compute_baselines([]) == []


def test_compute_baselines_groups_by_category():
    txs = [_tx(str(i), 100 + i, category='food') for i in range(5)]
    txs += [_tx(str(100 + i), 500 + i, category='transport') for i in range(5)]
    baselines = anomaly_detector.compute_baselines(txs)
    categories = {b['merchant_category'] for b in baselines}
    assert categories == {'food', 'transport'}
    for b in baselines:
        assert b['sample_size'] == 5


def test_compute_baselines_missing_merchant_category_defaults_to_other():
    txs = [
        {'id': '1', 'amount': 100, 'type': 'payment'},
        {'id': '2', 'amount': 120, 'type': 'payment'},
    ]
    baselines = anomaly_detector.compute_baselines(txs)
    assert len(baselines) == 1
    assert baselines[0]['merchant_category'] == 'other'


def test_compute_baselines_ignores_credits():
    txs = [_tx('1', 1000, tx_type='credit')]
    assert anomaly_detector.compute_baselines(txs) == []


def test_compute_baselines_missing_amount_column():
    assert anomaly_detector.compute_baselines([{'type': 'payment'}]) == []


def test_detect_anomalies_empty():
    assert anomaly_detector.detect_anomalies([]) == []


def test_detect_anomalies_missing_required_columns():
    assert anomaly_detector.detect_anomalies([{'amount': 100}]) == []


def test_detect_anomalies_ignores_credits():
    txs = [_tx('1', 1000, tx_type='credit') for _ in range(3)]
    assert anomaly_detector.detect_anomalies(txs) == []


def test_detect_anomalies_uses_mad_fallback_for_small_groups():
    base_amounts = [100, 102, 98, 105, 97]
    txs = [_tx(str(i), amt, category='food') for i, amt in enumerate(base_amounts)]
    txs.append(_tx('outlier', 100000, category='food'))
    flagged = anomaly_detector.detect_anomalies(txs)
    assert any(f['transaction_id'] == 'outlier' for f in flagged)
    assert all(f['model'] == anomaly_detector.FALLBACK_MODEL_NAME for f in flagged)


def test_detect_anomalies_uses_isolation_forest_for_large_groups():
    txs = [_tx(str(i), 100 + (i % 3), category='food') for i in range(20)]
    txs.append(_tx('big_outlier', 500000, category='food'))
    flagged = anomaly_detector.detect_anomalies(txs)
    assert any(f['transaction_id'] == 'big_outlier' for f in flagged)
    assert all(f['model'] == anomaly_detector.MODEL_NAME for f in flagged)


def test_detect_anomalies_sorted_by_score_descending():
    base_amounts = [100, 102, 98, 105, 97]
    txs = [_tx(str(i), amt, category='food') for i, amt in enumerate(base_amounts)]
    txs.append(_tx('mild', 400, category='food'))
    txs.append(_tx('extreme', 4000, category='food'))
    flagged = anomaly_detector.detect_anomalies(txs)
    scores = [f['score'] for f in flagged]
    assert scores == sorted(scores, reverse=True)


def test_detect_anomalies_missing_merchant_category_defaults_to_other():
    txs = [
        {'id': str(i), 'amount': 100, 'type': 'payment', 'timestamp': datetime.now().isoformat()}
        for i in range(5)
    ]
    txs.append({
        'id': 'outlier', 'amount': 100000, 'type': 'payment',
        'timestamp': datetime.now().isoformat(),
    })
    flagged = anomaly_detector.detect_anomalies(txs)
    assert all(f['merchant_category'] == 'other' for f in flagged)


def test_detect_anomalies_drops_rows_with_bad_timestamp():
    txs = [_tx(str(i), 100, category='food') for i in range(3)]
    txs.append({
        'id': 'bad', 'amount': 100, 'type': 'payment',
        'merchant_category': 'food', 'timestamp': 'not-a-real-date',
    })
    flagged = anomaly_detector.detect_anomalies(txs)
    assert all(f['transaction_id'] != 'bad' for f in flagged)
