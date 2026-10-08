import time

import pytest

from src import groq_client
from src.groq_client import _ResponseCache


def test_groq_client_requires_api_key(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(ValueError):
        groq_client.GroqClient()


def test_response_cache_roundtrip_and_expiry():
    cache = _ResponseCache()
    cache.set('system', 'question', 'answer', ttl=60)
    assert cache.get('system', 'question') == 'answer'
    assert cache.get('system', 'other question') is None
    cache.set('system', 'short', 'gone soon', ttl=0)
    time.sleep(0.01)
    assert cache.get('system', 'short') is None


def test_chat_returns_empty_string_on_api_error(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    client = groq_client.GroqClient()

    def _boom(**kwargs):
        raise RuntimeError("boom")

    client.client = type('C', (), {
        'chat': type('Chat', (), {
            'completions': type('Completions', (), {'create': staticmethod(_boom)})()
        })()
    })()

    assert client._chat('system prompt', 'user prompt') == ""
