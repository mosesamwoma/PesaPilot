"""One conversational brain shared by the WhatsApp API and the dashboard chat, so both always route and answer alike."""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src import chart_generator
from src.analyzer import LLM_UNAVAILABLE_MESSAGE, MpesaAnalyzer
from src.chat_common import (
    budget_status_text, clean_response, daily_summary_text, detect_intent, forecast_header, help_text,
    is_safe_question, is_valid_question_length, parse_days_from_question, parse_forecast_horizon, parse_set_budget,
    period_summary_text, range_summary_text,
)

logger = logging.getLogger(__name__)


@dataclass
class Reply:
    text: str
    fig: Any = None
    sql: str = ''
    results: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    intent: str = 'ask'


def _health_text(health: Dict, narrative: str = '') -> str:
    if not health.get('sufficient_data'):
        return health.get('message', 'Not enough history yet to score your financial health.')
    lines = [f"**Financial Health: {health['score']}/100 (grade {health['grade']})**", health['headline'], '']
    for comp in sorted(health['components'], key=lambda c: c['score']):
        lines.append(f"- {comp['name']}: {comp['score']:.0f}/100 · {comp['value']}")
    if narrative:
        lines += ['', narrative]
    elif health['tips']:
        lines += ['', '**Do this next:**'] + [f"{i}. {t}" for i, t in enumerate(health['tips'], 1)]
    return '\n'.join(lines)


def _recurring_text(items: List[Dict]) -> str:
    if not items:
        return ("I haven't found recurring payments yet. A payment counts once you've paid the same recipient "
                "several times at a regular rhythm.")
    subs = [i for i in items if i['kind'] == 'subscription']
    lines = [f"**Recurring payments and habits** ({len(items)} active)", '']
    for item in items[:8]:
        tag = 'subscription-like' if item['kind'] == 'subscription' else 'habit'
        nxt = f", next around {item['next_expected']}" if item['kind'] == 'subscription' else ''
        lines.append(f"- {item['recipient']}: ~KES {item['monthly_estimate']:,.0f}/month · {item['cadence']} · "
                     f"{item['payments']} payments ({tag}{nxt})")
    total = sum(i['monthly_estimate'] for i in items)
    lines += ['', f"Together about KES {total:,.0f} a month" + (f", of which {len(subs)} look like subscriptions." if subs else '.')]
    return '\n'.join(lines)


def _runway_text(run: Dict) -> str:
    if run['days_of_cover'] is None or run['balance'] is None:
        return "I can't work out your cash runway yet; I need your balance and a few days of spending history."
    verdict = {'critical': 'Critical: less than a day of cover.', 'low': 'Low: top up soon.',
               'ok': 'Okay for now.', 'strong': 'Comfortable.'}.get(run['status'], '')
    return (f"**Cash runway**\n\nBalance: KES {run['balance']:,.0f}\n"
            f"Recent spending: KES {run['avg_daily_spend']:,.0f}/day · income KES {run['avg_daily_income']:,.0f}/day\n"
            f"Your balance covers about {run['days_of_cover']:.1f} days at that pace. {verdict}")


def _anomaly_reply(az: MpesaAnalyzer, question_lower: str, dark: bool) -> Reply:
    days = parse_days_from_question(question_lower, default=90)
    result = az.get_smart_anomalies(days=days, force_refresh=False)
    flagged = result.get('anomalies', [])
    window = 'all time' if days is None else f'last {days} days'
    if not flagged:
        return Reply(clean_response(f"**No Unusual Transactions ({window})**\n\n{result.get('insight', '')}"), intent='anomalies')
    header = f"**{len(flagged)} Unusual Transaction(s) Found ({window})**\n\n"
    insight = result.get('insight', '')
    text = clean_response(header + insight)
    first_reason = (flagged[0].get('reasons') or [''])[0]
    if first_reason and first_reason not in insight:
        why = ['', '**Why they were flagged:**']
        for a in flagged[:5]:
            reason = (a.get('reasons') or ['Unusual against your normal pattern'])[0]
            why.append(f"- {str(a.get('timestamp', ''))[:10]}: {reason}")
        text += '\n' + '\n'.join(why)
    fig = chart_generator.render_anomalies(flagged, f"Unusual transactions ({window})", dark)
    return Reply(text, fig=fig, intent='anomalies')


def answer(az: MpesaAnalyzer, question: str, dark: bool = False, dashboard: bool = False) -> Reply:
    question = (question or '').strip()
    if not is_valid_question_length(question):
        return Reply("Question too short or too long (2-500 chars).", intent='invalid')
    if not is_safe_question(question):
        logger.warning("BLOCKED: destructive operation")
        return Reply("Invalid question.", intent='blocked')

    q = question.lower()
    intent, arg = detect_intent(question)

    if intent == 'set_budget':
        parsed, problem = parse_set_budget(question)
        if parsed is None:
            return Reply(clean_response(f"{problem}"), intent=intent)
        result = az.set_budget(parsed['category'], parsed['amount'], period=parsed['period'])
        if result.get('success'):
            unit = 'week' if parsed['period'] == 'weekly' else 'month'
            tail = ("Check the Budgets page anytime to see progress." if dashboard
                    else "I'll ping you here if you get close to or go over it.")
            text = f"Budget set: {parsed['category'].title()} — KES {parsed['amount']:,.0f} per {unit}.\n{tail}"
        else:
            text = f"Couldn't set that budget: {result.get('error', 'unknown error')}"
        return Reply(clean_response(text), intent=intent)

    if intent == 'budget_status':
        return Reply(clean_response(budget_status_text(az.get_budgets_overview(), dashboard=dashboard)), intent=intent)

    if intent == 'anomalies':
        return _anomaly_reply(az, q, dark)

    if intent == 'help':
        return Reply(help_text(dashboard=dashboard), intent=intent)

    if intent == 'daily':
        try:
            return Reply(daily_summary_text(az.db.get_today_summary(), manual_sms_hint=not dashboard), intent=intent)
        except Exception as e:
            logger.error(f"Daily summary error: {e}")
            return Reply("Could not generate summary. Please try again.", intent=intent)

    if intent == 'period' and arg:
        try:
            return Reply(period_summary_text(az.get_period_report(arg), arg), intent=intent)
        except Exception as e:
            logger.error(f"{arg} summary error: {e}")
            return Reply("Could not generate that summary. Please try again.", intent=intent)

    if intent == 'chart':
        result = az.generate_dynamic_chart(question, dark=dark)
        if result['fig'] is None:
            return Reply(result['error'] or 'No data available yet for that chart.', intent=intent)
        return Reply(chart_generator.compose_chart_text(result), fig=result['fig'], intent=intent)

    if intent == 'health':
        health = az.get_health()
        narrative = ''
        if health.get('sufficient_data'):
            from src import insights as insight_engine
            facts = (f"Score {health['score']}/100 grade {health['grade']}. Components: "
                     + '; '.join(f"{c['name']} {c['score']:.0f}/100 ({c['value']})" for c in health['components'])
                     + f". Tips: {' | '.join(health['tips'])}\n" + insight_engine.facts_text(az.get_frame()))
            narrative = az.groq.health_coach(facts) if az.groq.available else ''
        fig, _ = chart_generator.render_report('health', {'health': health}, dark) if health.get('sufficient_data') else (None, '')
        return Reply(clean_response(_health_text(health, narrative)), fig=fig, intent=intent)

    if intent == 'recurring':
        items = az.get_recurring()
        fig, _ = chart_generator.render_report('recurring', {'recurring': items}, dark) if items else (None, '')
        return Reply(_recurring_text(items), fig=fig, intent=intent)

    if intent == 'runway':
        return Reply(_runway_text(az.get_runway()), intent=intent)

    if intent == 'budget_plan':
        context = az.build_context_string(days=30)
        return Reply(clean_response(az.groq.budget_plan(context=context) or LLM_UNAVAILABLE_MESSAGE), intent=intent)

    if intent == 'invest':
        context = az.build_context_string(days=30)
        return Reply(clean_response(az.groq.investment_advice(context=context) or LLM_UNAVAILABLE_MESSAGE), intent=intent)

    if intent == 'forecast':
        horizon = parse_forecast_horizon(q, default=7)
        data = az.get_forecast(horizon_days=horizon)
        if not data.get('sufficient_data'):
            return Reply(clean_response(data.get('message', 'Not enough transaction history yet for a forecast.')), intent=intent)
        fig, _ = chart_generator.render_report('forecast', {'forecast': data}, dark, title=f"{horizon}-Day Spending Forecast")
        ai_summary = data.get('insight', '')
        return Reply(clean_response(forecast_header(data, horizon) + (f"\n{ai_summary}" if ai_summary else '')), fig=fig, intent=intent)

    if intent == 'summary':
        days = parse_days_from_question(q, default=30)
        try:
            return Reply(range_summary_text(az.db.get_range_summary(days=days), days), intent=intent)
        except Exception as e:
            logger.error(f"Summary error: {e}")
            return Reply("Could not generate summary. Please try again.", intent=intent)

    result = az.ask_question(question)
    return Reply(clean_response(result.get('analysis') or 'No response'), sql=result.get('sql', ''),
                 results=result.get('results', []), error=result.get('error'), intent='ask')
