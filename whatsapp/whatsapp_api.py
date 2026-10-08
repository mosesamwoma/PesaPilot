import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import re
import base64
import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from src import chart_generator
from src.analyzer import MpesaAnalyzer
from src.chat_common import (
    ANOMALY_KEYWORDS, BUDGET_KEYWORDS, BUDGET_STATUS_KEYWORDS, CHART_TRIGGER_WORDS, FORECAST_KEYWORDS,
    INVEST_KEYWORDS, budget_status_text, clean_response, daily_summary_text, forecast_header, help_text,
    is_safe_question, is_set_budget_command, is_valid_question_length, matches_any_keyword,
    parse_days_from_question, parse_forecast_horizon, parse_set_budget, range_summary_text,
)
from src.timeutil import now_nairobi

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")

WHATSAPP_API_PORT = int(os.getenv('WHATSAPP_API_PORT', 8000))
API_BIND = os.getenv('API_BIND_HOST', '127.0.0.1')

analyzer: Optional[MpesaAnalyzer] = None


def get_analyzer() -> MpesaAnalyzer:
    global analyzer
    if analyzer is None:
        analyzer = MpesaAnalyzer()
    return analyzer


class QuestionRequest(BaseModel):
    question: str


class AnalysisResponse(BaseModel):
    question: str
    analysis: str
    error: Optional[str] = None
    chart: Optional[str] = None


class ParseSMSRequest(BaseModel):
    sms_content: str


class ParseSMSResponse(BaseModel):
    success: bool
    summary: str
    error: Optional[str] = None


class SetBudgetRequest(BaseModel):
    category: str
    limit_amount: float
    period: str = 'monthly'
    alert_threshold_pct: int = 80


class BudgetAlertsResponse(BaseModel):
    alerts: list
    count: int


def is_valid_mpesa_sms(text: str) -> bool:
    text_upper = text.upper()
    return any(x in text_upper for x in ['KSH', 'KESH', 'MPESA', 'M-PESA', 'CONFIRMED'])


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+",
    flags=re.UNICODE,
)


def _plain(text: str) -> str:
    return re.sub(r'\s{2,}', ' ', _EMOJI_RE.sub('', text or '')).strip()


def _encode_figure() -> str:
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    plt.close()
    return img_b64

def _empty_chart(title: str) -> str:
    fig, ax = plt.subplots(figsize=(11, 7), facecolor='white', edgecolor='#e0e0e0')
    ax.text(0.5, 0.5, 'No data available\n\nAdd transactions to generate charts',
            ha='center', va='center', fontsize=14, color='#666666', weight='bold', family='monospace')
    ax.set_title(_plain(title), fontsize=16, fontweight='bold', pad=20, color='#333333')
    ax.axis('off')
    ax.spines['top'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    return _encode_figure()

def generate_bar_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str = "💰 Spending by Category") -> Optional[str]:
    try:
        if df is None or df.empty or category_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        chart_data = df.groupby(category_col)[value_col].sum().sort_values(ascending=True).tail(15)
        if chart_data.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(13, 8), facecolor='white', edgecolor='#e0e0e0')
        colors = sns.color_palette("husl", len(chart_data))
        bars = ax.barh(chart_data.index, chart_data.values, color=colors, edgecolor='#333333', linewidth=1.2)

        ax.set_xlabel('Amount (KES)', fontsize=12, fontweight='bold', color='#333333')
        ax.set_title(_plain(title), fontsize=15, fontweight='bold', pad=20, color='#333333')
        ax.grid(axis='x', alpha=0.3, linestyle='--', color='#cccccc')

        for bar, value in zip(bars, chart_data.values, strict=True):
            ax.text(value, bar.get_y() + bar.get_height()/2, f' KES {value:,.0f}',
                   va='center', ha='left', fontsize=10, fontweight='bold', color='#333333')

        ax.set_ylim(-0.5, len(chart_data)-0.5)
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Bar chart error: {e}")
        return None

def generate_forecast_chart(forecast_data: dict, title: str = "🔮 Spending Forecast") -> Optional[str]:
    try:
        hist_pts = forecast_data.get('historical', [])[-60:]
        fcst_pts = forecast_data.get('forecast', [])

        if not hist_pts and not fcst_pts:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(13, 7), facecolor='white', edgecolor='#e0e0e0')

        if hist_pts:
            df_h = pd.DataFrame(hist_pts)
            ax.plot(df_h['date'], df_h['amount'], color='#2196F3', linewidth=2.5,
                    marker='o', markersize=3, label='Historical Spending')

        if fcst_pts:
            df_f = pd.DataFrame(fcst_pts)
            ax.plot(df_f['date'], df_f['predicted'], color='#FF6B6B', linewidth=2.5,
                    linestyle='--', marker='o', markersize=5, label='Forecast Spending')
            ax.fill_between(df_f['date'], df_f['lower'], df_f['upper'],
                             color='#FF6B6B', alpha=0.18, label='Confidence Interval')

        ax.set_xlabel('Date', fontsize=12, fontweight='bold', color='#333333')
        ax.set_ylabel('Amount (KES)', fontsize=12, fontweight='bold', color='#333333')
        ax.set_title(_plain(title), fontsize=15, fontweight='bold', pad=20, color='#333333')
        ax.grid(True, alpha=0.3, linestyle='--', color='#cccccc')
        ax.legend(loc='upper left', fontsize=10, framealpha=0.9)
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Forecast chart error: {e}")
        return None


def generate_daily_summary() -> str:
    try:
        return daily_summary_text(get_analyzer().db.get_today_summary())
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return "⚠️ Could not generate summary. Please try again."


_SUMMARY_COMMAND_RE = re.compile(r'\bsummary\b')
_DAILY_COMMAND_RE = re.compile(
    r"^\s*(?:(?:my|the|give me|show me)\s+)*(?:daily|today(?:'s)?)(?:\s+(?:summary|overview|report|spending))?\s*\??\s*$"
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_analyzer()
    yield


app = FastAPI(title="PesaPilot API", version="1.2", lifespan=lifespan)

_cors_origins = [o.strip() for o in os.getenv('CORS_ORIGINS', '').split(',') if o.strip()]

if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


@app.get("/daily-summary")
async def daily_summary():
    return {"summary": generate_daily_summary()}


@app.get("/budget-check", response_model=BudgetAlertsResponse)
async def budget_check():
    try:
        alerts = get_analyzer().check_budget_alerts()
        return BudgetAlertsResponse(alerts=alerts, count=len(alerts))
    except Exception as e:
        logger.error(f"budget_check endpoint error: {e}")
        return BudgetAlertsResponse(alerts=[], count=0)


@app.get("/budgets")
async def list_budgets():
    return {"budgets": get_analyzer().get_budgets_overview()}


@app.post("/budgets")
async def create_budget(request: SetBudgetRequest):
    result = get_analyzer().set_budget(
        category=request.category,
        limit_amount=request.limit_amount,
        period=request.period,
        alert_threshold_pct=request.alert_threshold_pct,
    )
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Could not save budget'))
    return result


@app.get("/anomalies")
async def list_anomalies(days: int = Query(90, ge=1, le=1000)):
    return get_analyzer().get_smart_anomalies(days=days, force_refresh=False)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "PesaPilot API",
        "version": "1.2",
        "port": WHATSAPP_API_PORT,
        "timestamp": now_nairobi().isoformat(),
    }


@app.post("/ask", response_model=AnalysisResponse)
async def ask_question(request: QuestionRequest):
    try:
        question = request.question.strip()

        if not is_valid_question_length(question):
            raise HTTPException(status_code=400, detail="Question too short (2-500 chars)")

        if not is_safe_question(question):
            logger.warning("BLOCKED: destructive operation")
            raise HTTPException(status_code=403, detail="Invalid question")

        az = get_analyzer()
        question_lower = question.lower().strip()

        def reply(text: str, chart: Optional[str] = None, error: Optional[str] = None) -> AnalysisResponse:
            return AnalysisResponse(question=request.question, analysis=text, chart=chart, error=error)

        if is_set_budget_command(question_lower):
            parsed, problem = parse_set_budget(question)
            if parsed is None:
                return reply(clean_response(f"❌ {problem}"))
            result = az.set_budget(parsed['category'], parsed['amount'], period=parsed['period'])
            if result.get('success'):
                unit = 'week' if parsed['period'] == 'weekly' else 'month'
                analysis = (
                    f"🎯 Budget set: {parsed['category'].title()} — KES {parsed['amount']:,.0f} per {unit}.\n"
                    f"I'll ping you here if you get close to or go over it."
                )
            else:
                analysis = f"❌ Couldn't set that budget: {result.get('error', 'unknown error')}"
            return reply(clean_response(analysis))

        if matches_any_keyword(question_lower, BUDGET_STATUS_KEYWORDS):
            return reply(clean_response(budget_status_text(az.get_budgets_overview())))

        if matches_any_keyword(question_lower, BUDGET_KEYWORDS):
            context = az.build_context_string(days=30)
            return reply(clean_response(az.groq.budget_plan(context=context)))

        if matches_any_keyword(question_lower, INVEST_KEYWORDS):
            context = az.build_context_string(days=30)
            return reply(clean_response(az.groq.investment_advice(context=context)))

        if matches_any_keyword(question_lower, FORECAST_KEYWORDS):
            horizon = parse_forecast_horizon(question_lower, default=7)
            forecast_data = az.get_forecast(horizon_days=horizon)

            if not forecast_data.get('sufficient_data'):
                message = forecast_data.get('message', 'Not enough transaction history yet for a forecast.')
                return reply(clean_response(f"📉 {message}"))

            chart_img = generate_forecast_chart(forecast_data, title=f"🔮 {horizon}-Day Spending Forecast")
            ai_summary = forecast_data.get('insight', '')
            header = forecast_header(forecast_data, horizon)
            analysis = clean_response(header + (f"\n💡 {ai_summary}" if ai_summary else ""))
            return reply(analysis, chart=chart_img)

        if matches_any_keyword(question_lower, ANOMALY_KEYWORDS):
            anomaly_days = parse_days_from_question(question_lower, default=90)
            result = az.get_smart_anomalies(days=anomaly_days, force_refresh=False)
            flagged = result.get('anomalies', [])
            window = "all time" if anomaly_days is None else f"last {anomaly_days} days"

            chart_img = None
            if flagged:
                df = pd.DataFrame(flagged)
                chart_img = generate_bar_chart(
                    df.head(15), 'recipient', 'amount',
                    title=f"🕵️ Unusual Transactions ({window})"
                )
                header = f"🕵️ **{len(flagged)} Unusual Transaction(s) Found ({window})**\n\n"
            else:
                header = f"✅ **No Unusual Transactions ({window})**\n\n"

            return reply(clean_response(header + result.get('insight', '')), chart=chart_img)

        if question_lower == 'help':
            return reply(help_text())

        if _DAILY_COMMAND_RE.match(question_lower):
            return reply(generate_daily_summary())

        if matches_any_keyword(question_lower, CHART_TRIGGER_WORDS):
            chart_result = az.generate_dynamic_chart(question, dark=False)
            fig = chart_result['fig']
            if fig is None:
                analysis = f"❌ {chart_result['error'] or 'No data available yet for that chart.'}"
                return reply(analysis)
            spec = chart_result['spec']
            chart_img = chart_generator.figure_to_base64(fig)
            analysis = f"📊 **{spec.get('title')}**\n\n{chart_result['summary']}\n✅ Chart generated"
            return reply(analysis, chart=chart_img)

        if _SUMMARY_COMMAND_RE.search(question_lower) and len(question_lower.split()) <= 6:
            days = parse_days_from_question(question_lower, default=30)
            summary = az.db.get_range_summary(days=days)
            return reply(range_summary_text(summary, days))

        result = az.ask_question(question)

        if result.get('error'):
            analysis = f"⚠️ {clean_response(result.get('error', 'Error'))}"
        else:
            analysis = clean_response(result.get('analysis', 'No response'))

        return reply(analysis, error=result.get('error'))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)[:100]}") from e


@app.post("/parse-sms", response_model=ParseSMSResponse)
async def parse_sms(request: ParseSMSRequest):
    try:
        sms_content = request.sms_content.strip()

        if not sms_content:
            raise HTTPException(status_code=400, detail="SMS content required")

        if not is_valid_mpesa_sms(sms_content):
            return ParseSMSResponse(success=False, summary="❌ Not an M-Pesa SMS")

        result = get_analyzer().parse_and_insert_sms(sms_content)

        if result.get('success'):
            return ParseSMSResponse(
                success=True,
                summary=result.get('summary', '✅ SMS parsed successfully'),
            )
        if result.get('summary'):
            return ParseSMSResponse(success=False, summary=result['summary'], error=result.get('error'))
        return ParseSMSResponse(
            success=False,
            summary=f"❌ {result.get('error', 'Could not parse SMS')}",
            error=result.get('error'),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SMS parse error: {str(e)}")
        return ParseSMSResponse(success=False, summary=f"❌ Error: {str(e)[:100]}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_BIND, port=WHATSAPP_API_PORT, log_level="warning")
