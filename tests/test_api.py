import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from tests.conftest import require_test_database

pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def client(monkeypatch_module=None):
    require_test_database()
    os.environ.setdefault('WHATSAPP_PIN', '1234')
    os.environ.setdefault('GROQ_API_KEY', 'test-key')
    from fastapi.testclient import TestClient
    from whatsapp.whatsapp_api import app
    return TestClient(app)


def test_health(client):
    assert client.get('/health').json()['status'] == 'healthy'


def test_parse_sms_empty_body_returns_http_400(client):
    resp = client.post('/parse-sms', json={'sms_content': '   '})
    assert resp.status_code == 400


def test_parse_sms_non_mpesa_text_is_rejected_gracefully(client):
    resp = client.post('/parse-sms', json={'sms_content': 'hello there'})
    assert resp.status_code == 200
    assert resp.json()['success'] is False


def test_cors_does_not_allow_arbitrary_origins(client):
    resp = client.get('/health', headers={'Origin': 'https://evil.example'})
    assert resp.headers.get('access-control-allow-origin') != '*'
    assert resp.headers.get('access-control-allow-origin') != 'https://evil.example'


def test_plain_strips_emoji_for_matplotlib():
    require_test_database()
    os.environ.setdefault('WHATSAPP_PIN', '1234')
    os.environ.setdefault('GROQ_API_KEY', 'test-key')
    from whatsapp.whatsapp_api import _plain

    assert _plain('🔮 7-Day Spending Forecast') == '7-Day Spending Forecast'
    assert _plain('🕵️ Unusual Transactions (last 90d)') == 'Unusual Transactions (last 90d)'
    assert _plain('Plain title') == 'Plain title'
