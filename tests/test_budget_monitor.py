import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from src import budget_monitor


def test_period_start_for_monthly():
    today = date(2026, 6, 15)
    assert budget_monitor.period_start_for('monthly', today) == date(2026, 6, 1)


def test_period_start_for_weekly():
    today = date(2026, 6, 17)
    result = budget_monitor.period_start_for('weekly', today)
    assert result.weekday() == 0
    assert result <= today


def test_period_start_for_defaults_to_monthly_when_none():
    today = date(2026, 6, 15)
    assert budget_monitor.period_start_for(None, today) == date(2026, 6, 1)


def test_period_start_for_case_insensitive():
    today = date(2026, 6, 17)
    assert budget_monitor.period_start_for('WEEKLY', today) == budget_monitor.period_start_for('weekly', today)


def test_evaluate_budgets_empty():
    assert budget_monitor.evaluate_budgets([], set()) == []


def test_evaluate_budgets_handles_none_rows():
    assert budget_monitor.evaluate_budgets(None, set()) == []


def test_evaluate_budgets_skips_non_positive_limit():
    rows = [{'budget_id': '1', 'limit_amount': 0, 'spent_this_period': 100, 'category': 'food'}]
    assert budget_monitor.evaluate_budgets(rows, set()) == []


def test_evaluate_budgets_flags_over_budget():
    rows = [{
        'budget_id': '1', 'limit_amount': 1000, 'spent_this_period': 1200,
        'alert_threshold_pct': 80, 'category': 'food', 'period': 'monthly',
    }]
    due = budget_monitor.evaluate_budgets(rows, set())
    assert len(due) == 1
    assert due[0]['alert_level'] == budget_monitor.ALERT_OVER
    assert due[0]['pct_used'] == 120.0


def test_evaluate_budgets_flags_warning():
    rows = [{
        'budget_id': '1', 'limit_amount': 1000, 'spent_this_period': 850,
        'alert_threshold_pct': 80, 'category': 'food', 'period': 'monthly',
    }]
    due = budget_monitor.evaluate_budgets(rows, set())
    assert len(due) == 1
    assert due[0]['alert_level'] == budget_monitor.ALERT_WARNING


def test_evaluate_budgets_no_alert_below_threshold():
    rows = [{
        'budget_id': '1', 'limit_amount': 1000, 'spent_this_period': 500,
        'alert_threshold_pct': 80, 'category': 'food', 'period': 'monthly',
    }]
    assert budget_monitor.evaluate_budgets(rows, set()) == []


def test_evaluate_budgets_respects_already_alerted():
    rows = [{
        'budget_id': '1', 'limit_amount': 1000, 'spent_this_period': 1200,
        'alert_threshold_pct': 80, 'category': 'food', 'period': 'monthly',
    }]
    period_start = budget_monitor.period_start_for('monthly').isoformat()
    already = {('1', period_start, budget_monitor.ALERT_OVER)}
    assert budget_monitor.evaluate_budgets(rows, already) == []


def test_evaluate_budgets_skips_malformed_row():
    rows = [{'limit_amount': 1000}]
    assert budget_monitor.evaluate_budgets(rows, set()) == []


def test_evaluate_budgets_defaults_threshold_when_missing():
    rows = [{
        'budget_id': '1', 'limit_amount': 1000, 'spent_this_period': 850,
        'category': 'food', 'period': 'monthly',
    }]
    due = budget_monitor.evaluate_budgets(rows, set())
    assert len(due) == 1
    assert due[0]['alert_level'] == budget_monitor.ALERT_WARNING


def test_clamp_score_keeps_values_inside_decimal_6_3():
    from src.database import _clamp_score

    assert _clamp_score(33718.255) == 999.999
    assert _clamp_score(-5000) == -999.999
    assert _clamp_score(1.234) == 1.234
    assert _clamp_score(None) is None
    assert _clamp_score("not a number") is None
