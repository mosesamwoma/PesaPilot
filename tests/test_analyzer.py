# tests/test_analyzer.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.analyzer import MpesaAnalyzer
from src.groq_client import GroqClient

@pytest.fixture(scope='module')
def analyzer():
    return MpesaAnalyzer()

@pytest.fixture(scope='module')
def groq():
    return GroqClient()

# ── Groq LLM tests ──────────────────────────────────────────────────────────

def test_groq_connection(groq):
    """Groq client initializes"""
    assert groq.client is not None

def test_groq_chat(groq):
    response = groq.chat("Say hello in one word")
    assert isinstance(response, str)
    assert len(response) > 0

def test_groq_generate_sql(groq):
    from src.database import SupabaseDB
    schema = SupabaseDB().get_schema()
    sql = groq.generate_sql("How much did I spend on food?", schema)
    assert isinstance(sql, str)
    assert sql.upper().startswith("SELECT"), f"Expected SELECT, got: {sql[:50]}"

def test_groq_analyze_results(groq):
    results = [{'merchant_category': 'food', 'total': 3500}]
    analysis = groq.analyze_results("food spending", "SELECT ...", results)
    assert isinstance(analysis, str)
    assert len(analysis) > 10

def test_groq_generate_insights(groq):
    summary = {
        'total_transactions': 100,
        'total_spent': 25000,
        'total_received': 30000,
        'avg_spend': 250,
    }
    insights = groq.generate_insights(summary)
    assert isinstance(insights, str)
    assert len(insights) > 20

# ── Analyzer pipeline tests ─────────────────────────────────────────────────

def test_analyzer_initializes(analyzer):
    assert analyzer.db is not None
    assert analyzer.groq is not None

def test_get_dashboard_data(analyzer):
    data = analyzer.get_dashboard_data(days=30)
    assert isinstance(data, dict)
    expected_keys = ['summary', 'spending_by_category', 'daily_trend', 'anomalies', 'top_merchants']
    for key in expected_keys:
        assert key in data, f"Missing key: {key}"

def test_ask_question_returns_structure(analyzer):
    result = analyzer.ask_question("What is my total spending?")
    assert isinstance(result, dict)
    assert 'question' in result
    assert 'analysis' in result
    assert 'sql' in result
    assert 'results' in result

def test_ask_question_analysis_not_empty(analyzer):
    result = analyzer.ask_question("How much did I spend this month?")
    assert isinstance(result['analysis'], str)
    assert len(result['analysis']) > 0

def test_ask_question_handles_bad_input(analyzer):
    result = analyzer.ask_question("xyzzy nonsense question ???")
    assert result['error'] is None or isinstance(result['error'], str)