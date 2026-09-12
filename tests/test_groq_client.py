import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

import pytest

from src import groq_client
from src.groq_client import _ResponseCache, is_safe_select_sql


def test_is_safe_select_sql_accepts_plain_select():
    assert is_safe_select_sql("SELECT * FROM transactions") is True


def test_is_safe_select_sql_rejects_empty():
    assert is_safe_select_sql("") is False
    assert is_safe_select_sql(None) is False


def test_is_safe_select_sql_rejects_non_select():
    assert is_safe_select_sql("DELETE FROM transactions") is False


def test_is_safe_select_sql_rejects_multiple_statements():
    assert is_safe_select_sql("SELECT * FROM transactions; DROP TABLE transactions;") is False


def test_is_safe_select_sql_rejects_forbidden_keyword():
    assert is_safe_select_sql("SELECT * FROM transactions WHERE 1=1; DELETE FROM transactions") is False


def test_is_safe_select_sql_rejects_lowercase_forbidden_keyword():
    assert is_safe_select_sql("SELECT * FROM transactions WHERE id IN (select 1) or drop table x") is False


def test_is_safe_select_sql_allows_trailing_semicolon():
    assert is_safe_select_sql("SELECT * FROM transactions;") is True


def test_response_cache_roundtrip():
    cache = _ResponseCache()
    cache.set('sys', 'user', 'the answer', ttl=60)
    assert cache.get('sys', 'user') == 'the answer'


def test_response_cache_expires():
    cache = _ResponseCache()
    cache.set('sys', 'user', 'the answer', ttl=0)
    time.sleep(0.01)
    assert cache.get('sys', 'user') is None


def test_response_cache_miss_returns_none():
    cache = _ResponseCache()
    assert cache.get('sys', 'nope') is None


def test_response_cache_size_prunes_expired():
    cache = _ResponseCache()
    cache.set('sys', 'a', 'x', ttl=60)
    cache.set('sys', 'b', 'y', ttl=0)
    time.sleep(0.01)
    assert cache.size == 1


def test_response_cache_different_users_different_keys():
    cache = _ResponseCache()
    cache.set('sys', 'a', 'x', ttl=60)
    cache.set('sys', 'b', 'y', ttl=60)
    assert cache.size == 2
    assert cache.get('sys', 'a') == 'x'
    assert cache.get('sys', 'b') == 'y'


def test_groq_client_requires_api_key(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(ValueError):
        groq_client.GroqClient()


def test_groq_client_reads_timeout_from_env(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setenv('API_TIMEOUT', '45')
    client = groq_client.GroqClient()
    assert client.timeout == 45


def test_groq_client_defaults_timeout_when_env_missing(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.delenv('API_TIMEOUT', raising=False)
    client = groq_client.GroqClient()
    assert client.timeout == 20


def test_groq_client_legacy_model_env_overrides_fast_model(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setenv('LLM_MODEL', 'legacy-model')
    client = groq_client.GroqClient()
    assert client.model_fast == 'legacy-model'


class _FakeChoice:
    def __init__(self, content='hello', finish_reason='stop'):
        self.message = type('M', (), {'content': content})()
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content='hello', finish_reason='stop'):
        self.choices = [_FakeChoice(content, finish_reason)]


def _install_fake_completions(client, fake_create):
    client.client = type('C', (), {
        'chat': type('Chat', (), {
            'completions': type('Completions', (), {'create': staticmethod(fake_create)})()
        })()
    })()


def test_groq_client_chat_passes_timeout_to_api(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setenv('API_TIMEOUT', '12')
    client = groq_client.GroqClient()

    captured = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeResponse()

    _install_fake_completions(client, _fake_create)

    result = client._chat('system prompt', 'user prompt')
    assert result == 'hello'
    assert captured['timeout'] == 12


def test_groq_client_chat_explicit_timeout_overrides_default(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.setenv('API_TIMEOUT', '12')
    client = groq_client.GroqClient()

    captured = {}

    def _fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeResponse()

    _install_fake_completions(client, _fake_create)

    client._chat('system prompt', 'user prompt', timeout=5)
    assert captured['timeout'] == 5


def test_groq_client_chat_returns_empty_string_on_api_error(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    client = groq_client.GroqClient()

    def _fake_create(**kwargs):
        raise RuntimeError("boom")

    _install_fake_completions(client, _fake_create)

    result = client._chat('system prompt', 'user prompt')
    assert result == ""


def test_groq_client_chat_warns_on_truncated_response(monkeypatch, caplog):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    client = groq_client.GroqClient()

    def _fake_create(**kwargs):
        return _FakeResponse(content='cut off', finish_reason='length')

    _install_fake_completions(client, _fake_create)

    with caplog.at_level('WARNING'):
        result = client._chat('system prompt', 'user prompt')
    assert result == 'cut off'
    assert any('TRUNCATED' in record.message for record in caplog.records)
