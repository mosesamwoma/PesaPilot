import pytest
from fastapi.testclient import TestClient

from whatsapp import whatsapp_api


class _FakeDB:
    def __init__(self):
        self.range_calls = []

    def get_today_summary(self):
        return {
            'total_transactions': 2, 'total_spent': 300, 'total_received': 100, 'balance': 50,
            'debit_count': 1, 'total_transaction_cost': 5,
        }

    def get_range_summary(self, days=30):
        self.range_calls.append(days)
        return {
            'total_transactions': 4, 'total_spent': 900, 'total_received': 1000, 'balance': 75,
            'debit_count': 3, 'total_transaction_cost': 12, 'span_days': 20,
        }


class _FakeGroq:
    def budget_plan(self, context=''):
        return 'PLAN'

    def investment_advice(self, context=''):
        return 'ADVICE'


class _FakeAnalyzer:
    def __init__(self):
        self.db = _FakeDB()
        self.groq = _FakeGroq()
        self.budgets = []
        self.asked = []
        self.sms = []

    def set_budget(self, category, limit_amount, period='monthly', alert_threshold_pct=80):
        self.budgets.append((category, limit_amount, period))
        return {'success': True, 'budget': {}}

    def get_budgets_overview(self):
        return [{'category': 'food', 'period': 'monthly', 'limit_amount': 1000,
                 'spent_this_period': 400, 'alert_threshold_pct': 80}]

    def build_context_string(self, days=30):
        return ''

    def ask_question(self, question):
        self.asked.append(question)
        return {'analysis': 'ANSWER', 'error': None, 'sql': 'SELECT 1', 'results': []}

    def parse_and_insert_sms(self, sms):
        self.sms.append(sms)
        if 'DUP' in sms:
            return {'success': False, 'error': 'duplicate', 'summary': 'already recorded'}
        return {'success': True, 'summary': 'saved'}

    def check_budget_alerts(self):
        return [{'category': 'food', 'alert_level': 'over', 'message': 'careful'}]

    def get_smart_anomalies(self, days=None, force_refresh=False):
        return {'anomalies': [], 'baselines': [], 'count': 0, 'insight': 'fine'}


@pytest.fixture
def fake(monkeypatch):
    instance = _FakeAnalyzer()
    monkeypatch.setattr(whatsapp_api, 'analyzer', instance)
    return instance


@pytest.fixture
def client(fake):
    return TestClient(whatsapp_api.app)


def ask(client, text):
    resp = client.post('/ask', json={'question': text})
    assert resp.status_code == 200, resp.text
    return resp.json()['analysis']


def test_health(client):
    body = client.get('/health').json()
    assert body['status'] == 'healthy'


def test_parse_sms_empty_body_returns_http_400(client):
    assert client.post('/parse-sms', json={'sms_content': '   '}).status_code == 400


def test_parse_sms_non_mpesa_text_is_rejected_gracefully(client):
    resp = client.post('/parse-sms', json={'sms_content': 'hello there'})
    assert resp.status_code == 200 and resp.json()['success'] is False


def test_parse_sms_success_and_duplicate(client, fake):
    ok = client.post('/parse-sms', json={'sms_content': 'AB12CD34EF Confirmed. Ksh10.00 paid to X'}).json()
    assert ok == {'success': True, 'summary': 'saved', 'error': None}
    dup = client.post('/parse-sms', json={'sms_content': 'DUP Confirmed. Ksh10.00 paid to X'}).json()
    assert dup['success'] is False and dup['summary'] == 'already recorded'


def test_cors_does_not_allow_arbitrary_origins(client):
    resp = client.get('/health', headers={'Origin': 'https://evil.example'})
    assert resp.headers.get('access-control-allow-origin') not in ('*', 'https://evil.example')


def test_destructive_question_is_blocked(client):
    assert client.post('/ask', json={'question': 'drop table transactions'}).status_code == 403


def test_normal_english_with_sql_words_is_not_blocked(client, fake):
    assert ask(client, 'How much did I spend on call credit?') == 'ANSWER'
    assert fake.asked == ['How much did I spend on call credit?']


def test_question_length_validation(client):
    assert client.post('/ask', json={'question': 'x'}).status_code == 400


def test_set_budget_normalizes_category(client, fake):
    text = ask(client, 'set budget groceries 5,000 weekly')
    assert fake.budgets == [('food', 5000.0, 'weekly')]
    assert 'Budget set' in text


def test_set_budget_rejects_unknown_category(client, fake):
    assert "don't know the category" in ask(client, 'set budget spaceships 100')
    assert fake.budgets == []


def test_budget_status(client):
    assert 'Food' in ask(client, 'my budgets')


def test_help(client):
    assert 'PesaPilot' in ask(client, 'help')


def test_daily_summary_route_is_strict(client, fake):
    assert "Today's Financial Summary" in ask(client, 'daily summary')
    assert "Today's Financial Summary" in ask(client, 'today')
    assert ask(client, 'how much did i spend today on food') == 'ANSWER'


def test_summary_route_and_all_time(client, fake):
    assert '30-Day Financial Summary' in ask(client, 'summary')
    assert 'All-Time Financial Summary' in ask(client, 'summary all time')
    assert fake.db.range_calls == [30, None]


def test_long_summary_question_goes_to_ai(client, fake):
    assert ask(client, 'give me a summary of my spending on transport and food in march') == 'ANSWER'


def test_budget_plan_and_investment_routes(client):
    assert ask(client, 'give me a budget plan') == 'PLAN'
    assert ask(client, 'where should i invest') == 'ADVICE'


def test_sacco_payment_question_is_a_data_question(client, fake):
    assert ask(client, 'how much did i pay to my sacco') == 'ANSWER'


def test_budget_check_and_anomaly_endpoints(client):
    assert client.get('/budget-check').json()['count'] == 1
    assert client.get('/anomalies?days=30').json()['count'] == 0
    assert client.get('/anomalies?days=0').status_code == 422


def test_plain_strips_emoji_for_matplotlib():
    assert whatsapp_api._plain('🔮 7-Day Spending Forecast') == '7-Day Spending Forecast'
    assert whatsapp_api._plain('🕵️ Unusual Transactions (last 90d)') == 'Unusual Transactions (last 90d)'
    assert whatsapp_api._plain('Plain title') == 'Plain title'
