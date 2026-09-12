import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

import pandas as pd

from src import chart_generator


class _FakeGroqClient:
    def __init__(self, response):
        self._response = response

    def generate_chart_spec(self, description, system_prompt):
        return self._response


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def get_transactions_range(self, date_from=None, date_to=None, limit=20000):
        return self._rows


def _row(amount, category='food', recipient='Java House', tx_type='payment', days_ago=0, cost=0):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    return {
        'amount': amount,
        'merchant_category': category,
        'recipient': recipient,
        'type': tx_type,
        'timestamp': ts,
        'transaction_cost': cost,
    }


def test_parse_chart_request_uses_llm_json():
    groq = _FakeGroqClient('{"chart_type": "pie", "metric": "amount", "group_by": "recipient", "top_n": 5}')
    spec = chart_generator.parse_chart_request(groq, "pie chart of my top recipients")
    assert spec['chart_type'] == 'pie'
    assert spec['group_by'] == 'recipient'
    assert spec['top_n'] == 5


def test_parse_chart_request_falls_back_to_heuristic_on_bad_json():
    groq = _FakeGroqClient('not json at all')
    spec = chart_generator.parse_chart_request(groq, "donut chart of my spending by category")
    assert spec['chart_type'] == 'donut'


def test_parse_chart_request_clamps_top_n():
    groq = _FakeGroqClient('{"chart_type": "bar", "top_n": 999}')
    spec = chart_generator.parse_chart_request(groq, "bar chart")
    assert spec['top_n'] == 30


def test_parse_chart_request_rejects_bad_dates():
    groq = _FakeGroqClient('{"chart_type": "bar", "date_from": "not-a-date"}')
    spec = chart_generator.parse_chart_request(groq, "bar chart")
    assert spec['date_from'] is None


def test_parse_chart_request_defaults_invalid_chart_type_to_bar():
    groq = _FakeGroqClient('{"chart_type": "nonsense"}')
    spec = chart_generator.parse_chart_request(groq, "something")
    assert spec['chart_type'] == 'bar'


def test_parse_chart_request_lowercases_category_filter():
    groq = _FakeGroqClient('{"chart_type": "bar", "category_filter": "FOOD"}')
    spec = chart_generator.parse_chart_request(groq, "bar chart of food")
    assert spec['category_filter'] == 'food'


def test_heuristic_spec_detects_histogram_clears_group_by():
    spec = chart_generator._heuristic_spec("show me a histogram of my transaction amounts")
    assert spec['chart_type'] == 'histogram'
    assert spec['group_by'] is None


def test_heuristic_spec_detects_fees():
    spec = chart_generator._heuristic_spec("how much has m-pesa charged me in fees this month")
    assert spec['metric'] == 'transaction_cost'


def test_heuristic_spec_detects_top_n():
    spec = chart_generator._heuristic_spec("top 5 recipients this week")
    assert spec['top_n'] == 5


def test_heuristic_spec_detects_income():
    spec = chart_generator._heuristic_spec("show me a chart of money received this month")
    assert spec['transaction_type'] == 'income'


def test_fetch_chart_data_fills_missing_columns():
    rows = [
        {'amount': 100, 'type': 'payment', 'timestamp': datetime.now().isoformat()},
    ]
    db = _FakeDB(rows)
    df = chart_generator.fetch_chart_data(db, dict(chart_generator.DEFAULT_SPEC))
    assert df.loc[0, 'merchant_category'] == 'other'
    assert df.loc[0, 'recipient'] == 'Unknown'


def test_fetch_chart_data_filters_spending_only():
    rows = [_row(100, tx_type='payment'), _row(500, tx_type='credit')]
    db = _FakeDB(rows)
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['transaction_type'] = 'spending'
    df = chart_generator.fetch_chart_data(db, spec)
    assert len(df) == 1
    assert df.iloc[0]['amount'] == 100


def test_fetch_chart_data_filters_income_only():
    rows = [_row(100, tx_type='payment'), _row(500, tx_type='credit')]
    db = _FakeDB(rows)
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['transaction_type'] = 'income'
    df = chart_generator.fetch_chart_data(db, spec)
    assert len(df) == 1
    assert df.iloc[0]['amount'] == 500


def test_fetch_chart_data_empty_rows_returns_empty_df():
    db = _FakeDB([])
    df = chart_generator.fetch_chart_data(db, dict(chart_generator.DEFAULT_SPEC))
    assert df.empty


def test_fetch_chart_data_applies_category_filter():
    rows = [_row(100, category='food'), _row(200, category='transport')]
    db = _FakeDB(rows)
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['category_filter'] = 'food'
    df = chart_generator.fetch_chart_data(db, spec)
    assert len(df) == 1
    assert df.iloc[0]['merchant_category'] == 'food'


def test_build_figure_returns_none_for_empty_df():
    fig, message = chart_generator.build_figure(pd.DataFrame(), dict(chart_generator.DEFAULT_SPEC))
    assert fig is None
    assert 'No transactions' in message


def test_build_figure_bar_chart_from_synthetic_data():
    rows = [_row(100, category='food'), _row(200, category='transport'), _row(50, category='food')]
    db = _FakeDB(rows)
    spec = dict(chart_generator.DEFAULT_SPEC)
    df = chart_generator.fetch_chart_data(db, spec)
    fig, summary = chart_generator.build_figure(df, spec)
    assert fig is not None
    assert isinstance(summary, str)
    chart_generator.plt.close(fig)


def test_build_figure_line_chart_from_synthetic_data():
    rows = [_row(100, days_ago=2), _row(200, days_ago=1), _row(50, days_ago=0)]
    db = _FakeDB(rows)
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['chart_type'] = 'line'
    spec['group_by'] = None
    df = chart_generator.fetch_chart_data(db, spec)
    fig, summary = chart_generator.build_figure(df, spec)
    assert fig is not None
    chart_generator.plt.close(fig)


def test_build_figure_pie_chart_from_synthetic_data():
    rows = [_row(100, category='food'), _row(200, category='transport')]
    db = _FakeDB(rows)
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['chart_type'] = 'pie'
    df = chart_generator.fetch_chart_data(db, spec)
    fig, summary = chart_generator.build_figure(df, spec)
    assert fig is not None
    chart_generator.plt.close(fig)


def test_default_title_includes_category_filter():
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['category_filter'] = 'food'
    title = chart_generator._default_title(spec)
    assert 'Food' in title


def test_default_title_includes_date_range():
    spec = dict(chart_generator.DEFAULT_SPEC)
    spec['date_from'] = '2026-01-01'
    spec['date_to'] = '2026-01-31'
    title = chart_generator._default_title(spec)
    assert '2026-01-01' in title and '2026-01-31' in title


def test_figure_to_base64_returns_none_for_none_figure():
    assert chart_generator.figure_to_base64(None) is None
