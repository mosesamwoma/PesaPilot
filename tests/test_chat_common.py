import pytest

from src import chat_common as cc


@pytest.mark.parametrize('text,expected', [
    ('summary', 30),
    ('summary last 90 days', 90),
    ('summary 14 days', 14),
    ('spending last 3 months', 90),
    ('this year', 365),
    ('this week', 7),
    ('two weeks', 14),
    ('past 45', 45),
    ('summary all time', None),
    ('what did i spend ever', None),
])
def test_parse_days_from_question(text, expected):
    assert cc.parse_days_from_question(text, default=30) == expected


def test_parse_days_is_capped():
    assert cc.parse_days_from_question('last 99999 days') == cc.MAX_PERIOD_DAYS


@pytest.mark.parametrize('text,expected', [
    ('forecast', 7),
    ('forecast next month', 30),
    ('forecast 30 days', 30),
    ('forecast this week', 7),
])
def test_parse_forecast_horizon(text, expected):
    assert cc.parse_forecast_horizon(text) == expected


def test_parse_set_budget_variants():
    assert cc.parse_set_budget('set budget food 5000')[0] == {'category': 'food', 'amount': 5000.0, 'period': 'monthly'}
    assert cc.parse_set_budget('set budget groceries 5,000 weekly')[0] == {'category': 'food', 'amount': 5000.0, 'period': 'weekly'}
    assert cc.parse_set_budget('set budget for transport to 3000')[0]['category'] == 'transport'
    assert cc.parse_set_budget('set food budget 2500')[0]['amount'] == 2500.0
    assert cc.parse_set_budget('budget limit airtime 200')[0]['category'] == 'utilities'


def test_parse_set_budget_rejects_unknown_category_and_zero():
    parsed, problem = cc.parse_set_budget('set budget spaceships 100')
    assert parsed is None and 'spaceships' in problem
    parsed, problem = cc.parse_set_budget('set budget food 0')
    assert parsed is None and 'greater than 0' in problem


def test_is_set_budget_command():
    assert cc.is_set_budget_command('set budget food 5000')
    assert cc.is_set_budget_command('set food budget 5000')
    assert not cc.is_set_budget_command('how is my budget')
    assert not cc.is_set_budget_command('set a reminder')


def test_normalize_category():
    assert cc.normalize_category('Food') == 'food'
    assert cc.normalize_category('matatu') == 'transport'
    assert cc.normalize_category('send money') == 'personal'
    assert cc.normalize_category('nonsense') is None
    assert cc.normalize_category('') is None


def test_safe_question_allows_normal_english_that_contains_sql_words():
    assert cc.is_safe_question('How much did I spend on call credit?')
    assert cc.is_safe_question('Did I update my rent payment or create a savings plan?')
    assert cc.is_safe_question('Replace my budget plan with a cheaper one')


@pytest.mark.parametrize('text', [
    'drop table transactions',
    'DELETE FROM transactions',
    'insert into budgets values (1)',
    'update transactions set amount = 0',
    'truncate table transactions',
])
def test_safe_question_blocks_destructive_sql(text):
    assert not cc.is_safe_question(text)


def test_keyword_matching_uses_word_boundaries():
    assert cc.matches_any_keyword('show a pie of food', cc.CHART_TRIGGER_WORDS)
    assert not cc.matches_any_keyword('how much did i spend at the bar', cc.CHART_TRIGGER_WORDS)
    assert not cc.matches_any_keyword('what is my outline', cc.CHART_TRIGGER_WORDS)
    assert cc.matches_any_keyword('how much to my sacco', cc.INVEST_KEYWORDS) is False
    assert cc.matches_any_keyword('where should i invest', cc.INVEST_KEYWORDS)


def test_question_length_bounds():
    assert not cc.is_valid_question_length('a')
    assert cc.is_valid_question_length('ok')
    assert not cc.is_valid_question_length('x' * 501)


def test_clean_response_strips_jargon():
    assert 'sql' not in cc.clean_response('Here is the sql result').lower()


def test_daily_summary_text_empty_and_populated():
    assert 'No transactions' in cc.daily_summary_text({})
    text = cc.daily_summary_text({
        'total_transactions': 3, 'total_spent': 1200, 'total_received': 500, 'balance': 80,
        'debit_count': 2, 'total_transaction_cost': 10,
    })
    assert 'KES 1,200' in text and 'Average per payment: KES 600' in text


def test_range_summary_text_all_time_uses_span_days():
    text = cc.range_summary_text({
        'total_transactions': 10, 'total_spent': 1000, 'total_received': 400, 'balance': 5,
        'debit_count': 5, 'total_transaction_cost': 0, 'span_days': 10,
    }, None)
    assert 'All-Time' in text and 'Daily Average: KES 100' in text and 'Deficit' in text


def test_budget_status_text_icons():
    rows = [
        {'category': 'food', 'period': 'monthly', 'limit_amount': 1000, 'spent_this_period': 1200, 'alert_threshold_pct': 80},
        {'category': 'transport', 'period': 'weekly', 'limit_amount': 1000, 'spent_this_period': 850, 'alert_threshold_pct': 80},
        {'category': 'health', 'period': 'monthly', 'limit_amount': 1000, 'spent_this_period': 10, 'alert_threshold_pct': 80},
    ]
    text = cc.budget_status_text(rows)
    assert '🔴 Food' in text and '🟡 Transport' in text and '🟢 Health' in text
    assert 'No budgets' in cc.budget_status_text([])
