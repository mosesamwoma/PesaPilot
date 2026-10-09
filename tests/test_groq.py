from types import SimpleNamespace

import pytest

from src import groq_client
from src.groq_client import GroqClient


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else ''
        if isinstance(reply, Exception):
            raise reply
        choice = SimpleNamespace(message=SimpleNamespace(content=reply), finish_reason='stop')
        return SimpleNamespace(choices=[choice])


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')

    def build(*replies):
        groq_client._cache.clear()
        client = GroqClient()
        completions = FakeCompletions(replies)
        client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        return client, completions

    yield build
    groq_client._cache.clear()


def test_missing_api_key_is_rejected(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(ValueError):
        GroqClient()


def test_generate_sql_strips_markdown_fences(make_client):
    client, _ = make_client("```sql\nSELECT SUM(amount) AS total FROM transactions WHERE type != 'credit'\n```")
    sql = client.generate_sql('how much did I spend?', 'transactions(amount, type)')
    assert sql == "SELECT SUM(amount) AS total FROM transactions WHERE type != 'credit'"


@pytest.mark.parametrize('bad_sql', [
    'DROP TABLE transactions',
    'DELETE FROM transactions',
    'SELECT 1; DROP TABLE transactions',
    'SELECT pg_sleep(30)',
    '',
])
def test_generate_sql_rejects_unsafe_output(make_client, bad_sql):
    client, _ = make_client(bad_sql)
    assert client.generate_sql('anything', 'transactions(amount)') == ''


def test_identical_prompts_are_served_from_cache(make_client):
    client, completions = make_client('first answer', 'second answer')
    assert client.chat('hello') == 'first answer'
    assert client.chat('hello') == 'first answer'
    assert len(completions.calls) == 1
    client.invalidate_cache()
    assert client.chat('hello') == 'second answer'
    assert len(completions.calls) == 2


def test_api_errors_return_empty_text_and_are_not_cached(make_client):
    client, completions = make_client(RuntimeError('boom'), 'recovered')
    assert client.chat('hello') == ''
    assert client.chat('hello') == 'recovered'
    assert len(completions.calls) == 2


def test_reasoning_effort_is_only_sent_to_gpt_oss_models(make_client):
    client, completions = make_client('a', 'b')
    client._chat('system', 'user', model='openai/gpt-oss-20b')
    client._chat('system', 'user', model='llama-3.1-8b-instant')
    assert 'reasoning_effort' in completions.calls[0]
    assert 'reasoning_effort' not in completions.calls[1]


def test_sql_uses_the_smart_model_and_chat_uses_the_fast_model(make_client):
    client, completions = make_client('SELECT 1', 'hi there')
    client.generate_sql('q', 'schema')
    client.chat('hello')
    assert completions.calls[0]['model'] == client.model_smart
    assert completions.calls[1]['model'] == client.model_fast


def test_budget_alert_has_a_fallback_when_the_llm_is_unavailable(make_client):
    client, _ = make_client('')
    alert = {'category': 'food', 'amount_spent': 4200, 'limit_amount': 5000, 'pct_used': 84,
             'alert_level': 'warning', 'period': 'monthly'}
    message = client.budget_alert_message(alert)
    assert 'Food' in message and '4,200' in message and '84%' in message
