import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import re
import io
import base64
from datetime import datetime
from dotenv import load_dotenv
from src.analyzer import MpesaAnalyzer
from src import chart_generator
from typing import Optional
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")

WHATSAPP_PIN = os.getenv('WHATSAPP_PIN')
WHATSAPP_API_PORT = int(os.getenv('WHATSAPP_API_PORT', 8000))
WHATSAPP_MAIN_NUMBER = os.getenv('WHATSAPP_MAIN_NUMBER')

if not WHATSAPP_PIN:
    raise ValueError("WHATSAPP_PIN must be set in .env")

DANGEROUS_KEYWORDS = ['DELETE', 'DROP', 'TRUNCATE', 'UPDATE', 'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC']

FORECAST_KEYWORDS = [
    'forecast', 'spending prediction', 'predict my spending', 'spending forecast',
    'projected spending', 'predict spending', 'future spending',
]

ANOMALY_KEYWORDS = [
    'anomaly', 'anomalies', 'unusual spending', 'unusual transaction', 'weird transaction',
    'strange transaction', 'suspicious transaction', 'flagged transaction', 'odd spending',
    'out of pattern', 'is anything unusual',
]

BUDGET_STATUS_KEYWORDS = [
    'my budgets', 'budget status', 'how are my budgets', 'budget check',
    'check my budget', 'am i over budget', 'am i within budget', 'budget progress',
]
SET_BUDGET_PATTERN = re.compile(
    r'(?:'
        r'(?:set\s+)?budget(?:\s+limit)?\s+(?:for\s+)?(?P<category>[a-zA-Z ]+?)\s+'
        r'(?:to\s+|of\s+|at\s+)?(?:kes\s*)?(?P<amount>[\d,]+(?:\.\d+)?)'
        r'|'
        r'set\s+(?P<category2>[a-zA-Z ]+?)\s+budget\s*'
        r'(?:to\s+|of\s+|at\s+)?(?:kes\s*)?(?P<amount2>[\d,]+(?:\.\d+)?)'
    r')\s*(?P<period>weekly|monthly)?',
    re.IGNORECASE,
)
_HAS_DIGIT = re.compile(r'\d')

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

def is_safe_question(question: str) -> bool:
    question_upper = question.upper()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in question_upper:
            return False
    if '--' in question or '/*' in question:
        return False
    return True

def is_valid_mpesa_sms(text: str) -> bool:
    text_upper = text.upper()
    return any(x in text_upper for x in ['KSH', 'KESH', 'MPESA', 'CONFIRMED'])

def clean_response(text: str) -> str:
    jargon = ['postgresql', 'postgres', 'schema', 'database', 'query', 'sql', 'rpc']
    for word in jargon:
        text = re.sub(word, '', text, flags=re.IGNORECASE)
    return re.sub(r' +', ' ', text).strip()

def _encode_figure() -> str:
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    plt.close()
    return img_b64

def _empty_chart(title: str) -> str:
    fig, ax = plt.subplots(figsize=(11, 7), facecolor='white', edgecolor='#e0e0e0')
    ax.text(0.5, 0.5, '📊 No data available\n\nAdd transactions to generate charts',
            ha='center', va='center', fontsize=14, color='#666666', weight='bold', family='monospace')
    ax.set_title(title, fontsize=16, fontweight='bold', pad=20, color='#333333')
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
        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')
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

def parse_days_from_question(question_lower: str, default: int = 30) -> int:
    if 'all time' in question_lower or 'year' in question_lower or re.search(r'\b365\b', question_lower):
        return 365
    if re.search(r'\b180\b', question_lower) or '6 months' in question_lower:
        return 180
    if re.search(r'\b90\b', question_lower) or '3 months' in question_lower:
        return 90
    if re.search(r'\b60\b', question_lower):
        return 60
    if re.search(r'\bweek\b', question_lower) or '7 days' in question_lower:
        return 7
    if '14 days' in question_lower or 'two weeks' in question_lower:
        return 14
    match = re.search(r'(\d{1,3})\s*day', question_lower)
    if match:
        days = int(match.group(1))
        if 1 <= days <= 365:
            return days
    return default

CATEGORY_SYNONYMS = {
    'food': ['food', 'groceries', 'grocery', 'eating', 'restaurant', 'eats', 'lunch', 'dinner', 'kibanda', 'mama mboga'],
    'transport': ['transport', 'fare', 'matatu', 'uber', 'bolt', 'taxi', 'fuel', 'petrol', 'boda'],
    'utilities': ['utilities', 'utility', 'kplc', 'electricity', 'power', 'water bill', 'wifi', 'internet'],
    'banking': ['banking', 'bank charges', 'bank charge', 'withdrawal', 'withdraw', 'deposit', 'transaction charges'],
    'shopping': ['shopping', 'shop', 'clothes', 'clothing', 'retail'],
    'health': ['health', 'medical', 'hospital', 'clinic', 'pharmacy', 'medicine', 'nhif', 'sha'],
    'education': ['education', 'school fees', 'fees', 'tuition', 'school'],
    'entertainment': ['entertainment', 'movies', 'netflix', 'showmax', 'fun', 'leisure'],
    'savings': ['savings', 'saving', 'sacco', 'mmf', 'chama'],
    'business': ['business', 'stock', 'supplies', 'wholesale'],
    'other': ['other', 'miscellaneous', 'misc'],
}

def extract_category_filter(question_lower: str) -> Optional[str]:
    for category, synonyms in CATEGORY_SYNONYMS.items():
        for synonym in synonyms:
            if synonym in question_lower:
                return category
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
        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')
        ax.grid(True, alpha=0.3, linestyle='--', color='#cccccc')
        ax.legend(loc='upper left', fontsize=10, framealpha=0.9)
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Forecast chart error: {e}")
        return None

def parse_forecast_horizon(question_lower: str, default: int = 7) -> int:
    if 'month' in question_lower or re.search(r'\b30\b', question_lower):
        return 30
    if 'week' in question_lower or re.search(r'\b7\b', question_lower):
        return 7
    return default

def generate_daily_summary() -> str:
    try:
        summary = analyzer.db.get_today_summary()

        if not summary or summary.get('total_transactions', 0) == 0:
            return "📭 No transactions recorded today.\n\nStart tracking by sending M-Pesa SMS or manual entry: PIN-SMS_CONTENT"

        spent = summary.get('total_spent', 0)
        received = summary.get('total_received', 0)
        balance = summary.get('balance', 0)
        transactions = summary.get('total_transactions', 0)

        return f"""📊 **Today's Financial Summary**

💰 Total Transactions: {transactions}
💸 Total Spent: KES {spent:,.0f}
💵 Total Received: KES {received:,.0f}
📈 Net Flow: KES {received - spent:,.0f}
⚖️ Current Balance: KES {balance:,.0f}

**Insights:**
- Average per transaction: KES {spent/max(transactions, 1):,.0f}
- Spending velocity: {'High' if spent > 5000 else 'Moderate' if spent > 1000 else 'Low'}
"""
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return "⚠️ Could not generate summary. Please try again."

app = FastAPI(title="PesaPilot API", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

analyzer = MpesaAnalyzer()

@app.get("/daily-summary")
async def daily_summary():
    return {"summary": generate_daily_summary()}

@app.get("/budget-check", response_model=BudgetAlertsResponse)
async def budget_check():
    try:
        alerts = analyzer.check_budget_alerts()
        return BudgetAlertsResponse(alerts=alerts, count=len(alerts))
    except Exception as e:
        logger.error(f"budget_check endpoint error: {e}")
        return BudgetAlertsResponse(alerts=[], count=0)

@app.get("/budgets")
async def list_budgets():
    return {"budgets": analyzer.get_budgets_overview()}

@app.post("/budgets")
async def create_budget(request: SetBudgetRequest):
    result = analyzer.set_budget(
        category=request.category,
        limit_amount=request.limit_amount,
        period=request.period,
        alert_threshold_pct=request.alert_threshold_pct,
    )
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Could not save budget'))
    return result

@app.get("/anomalies")
async def list_anomalies(days: int = 90):
    return analyzer.get_smart_anomalies(days=days, force_refresh=False)

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "PesaPilot API",
        "version": "2.1",
        "port": WHATSAPP_API_PORT,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/ask", response_model=AnalysisResponse)
async def ask_question(request: QuestionRequest):
    try:
        question = request.question.strip()

        if not question or len(question) < 2 or len(question) > 500:
            raise HTTPException(status_code=400, detail="Question too short (2-500 chars)")

        if not is_safe_question(question):
            logger.warning("🚨 BLOCKED: Destructive operation")
            raise HTTPException(status_code=403, detail="Invalid question")

        logger.info(f"📨 Q: {question[:50]}")

        question_lower = question.lower().strip()

        BUDGET_KEYWORDS = ['budget plan', 'budget', 'how should i budget', 'monthly plan', 'allocate my money', 'allocate income']
        INVEST_KEYWORDS = ['invest', 'investment', 'where to invest', 'grow my money', 'grow savings', 'mmf', 'money market fund',
                            'treasury bill', 't-bill', 'sacco', 'put my money']

        if (question_lower.startswith('set budget') or question_lower.startswith('budget limit')
                or (question_lower.startswith('set ') and 'budget' in question_lower
                    and _HAS_DIGIT.search(question_lower))):
            match = SET_BUDGET_PATTERN.search(question)
            if match:
                category = (match.group('category') or match.group('category2')).strip().lower()
                amount = float((match.group('amount') or match.group('amount2')).replace(',', ''))
                period = (match.group('period') or 'monthly').lower()
                logger.info(f"🎯 SET BUDGET: {category} KES {amount} ({period})")
                result = analyzer.set_budget(category, amount, period=period)
                if result.get('success'):
                    analysis = (
                        f"🎯 Budget set: {category.title()} — KES {amount:,.0f} per {period}.\n"
                        f"I'll ping you here if you get close to or go over it."
                    )
                else:
                    analysis = f"❌ Couldn't set that budget: {result.get('error', 'unknown error')}"
                return AnalysisResponse(question=request.question, analysis=clean_response(analysis))
            else:
                analysis = "❌ Couldn't read that. Try: \"set budget food 5000\" or \"set budget transport 3000 weekly\""
                return AnalysisResponse(question=request.question, analysis=clean_response(analysis))

        if any(k in question_lower for k in BUDGET_STATUS_KEYWORDS):
            logger.info("🎯 BUDGET STATUS")
            status_rows = analyzer.get_budgets_overview()
            if not status_rows:
                analysis = "📭 No budgets set yet. Try: \"set budget food 5000\" to create one."
            else:
                lines = ["🎯 **Your Budgets**\n"]
                for row in status_rows:
                    limit = float(row.get('limit_amount') or 0)
                    spent = float(row.get('spent_this_period') or 0)
                    pct = (spent / limit * 100) if limit else 0
                    icon = "🔴" if pct >= 100 else "🟡" if pct >= float(row.get('alert_threshold_pct') or 80) else "🟢"
                    lines.append(
                        f"{icon} {str(row.get('category', '')).title()} ({row.get('period', 'monthly')}): "
                        f"KES {spent:,.0f} / {limit:,.0f} ({pct:.0f}%)"
                    )
                analysis = "\n".join(lines)
            return AnalysisResponse(question=request.question, analysis=clean_response(analysis))

        if any(k in question_lower for k in BUDGET_KEYWORDS):
            logger.info("📋 BUDGET PLAN")
            context = analyzer.build_context_string(days=30)
            analysis = analyzer.groq.budget_plan(context=context)
            return AnalysisResponse(question=request.question, analysis=clean_response(analysis))

        if any(k in question_lower for k in INVEST_KEYWORDS):
            logger.info("📈 INVESTMENT ADVICE")
            context = analyzer.build_context_string(days=30)
            analysis = analyzer.groq.investment_advice(context=context)
            return AnalysisResponse(question=request.question, analysis=clean_response(analysis))

        if any(k in question_lower for k in FORECAST_KEYWORDS):
            logger.info("🔮 FORECAST")
            horizon = parse_forecast_horizon(question_lower, default=7)
            forecast_data = analyzer.get_forecast(horizon_days=horizon)

            if not forecast_data.get('sufficient_data'):
                analysis = f"📉 {forecast_data.get('message', 'Not enough transaction history yet for a forecast.')}"
                return AnalysisResponse(question=request.question, analysis=clean_response(analysis))

            chart_img = generate_forecast_chart(forecast_data, title=f"🔮 {horizon}-Day Spending Forecast")

            trend_icon = {'Increasing': '📈', 'Decreasing': '📉', 'Stable': '➡️'}.get(forecast_data.get('trend', 'Stable'), '➡️')
            risk_icon = {'Low': '🟢', 'Moderate': '🟡', 'High': '🔴'}.get(forecast_data.get('risk_level', 'Low'), '🟢')

            header = (
                f"🔮 **{horizon}-Day Spending Forecast**\n\n"
                f"💰 Predicted Spend: KES {forecast_data.get('total_predicted', 0):,.0f}\n"
                f"📅 Avg per Day: KES {forecast_data.get('avg_predicted_daily', 0):,.0f}\n"
                f"{trend_icon} Trend: {forecast_data.get('trend', 'Stable')}\n"
                f"{risk_icon} Risk Level: {forecast_data.get('risk_level', 'Low')}\n"
            )
            ai_summary = forecast_data.get('insight', '')
            analysis = clean_response(header + (f"\n💡 {ai_summary}" if ai_summary else ""))

            return AnalysisResponse(question=request.question, analysis=analysis, chart=chart_img)

        if any(k in question_lower for k in ANOMALY_KEYWORDS):
            logger.info("🕵️ ML ANOMALY DETECTION")
            anomaly_days = parse_days_from_question(question_lower, default=90)
            result = analyzer.get_smart_anomalies(days=anomaly_days, force_refresh=False)
            flagged = result.get('anomalies', [])

            chart_img = None
            if flagged:
                df = pd.DataFrame(flagged)
                chart_img = generate_bar_chart(
                    df, 'recipient', 'amount',
                    title=f"🕵️ Unusual Transactions (last {anomaly_days}d)"
                )
                header = f"🕵️ **{len(flagged)} Unusual Transaction(s) Found (last {anomaly_days} days)**\n\n"
            else:
                header = f"✅ **No Unusual Transactions (last {anomaly_days} days)**\n\n"

            analysis = clean_response(header + result.get('insight', ''))
            return AnalysisResponse(question=request.question, analysis=analysis, chart=chart_img)

        CHART_TRIGGER_WORDS = [
            'bar chart', 'pie chart', 'line chart', 'area chart', 'scatter chart', 'scatter plot',
            'bar', 'pie', 'trend', 'line', 'area', 'heatmap', 'heat map', 'histogram', 'distribution',
            'chart', 'graph', 'plot', 'draw', 'diagram', 'visualize', 'visualise',
            'over days', 'over time', 'spending over', 'daily trend', 'weekly',
            'merchants', 'top merchants', 'top recipients', 'recipients', 'top spending',
            'breakdown of', 'spending by', 'spending per', 'where did i spend', 'where did my money go',
            'how did i spend', 'proportion', 'percentage of my spending', 'compare my spending',
            'show me my spending', 'show my spending', 'transaction costs', 'transaction fees',
        ]
        if any(w in question_lower for w in CHART_TRIGGER_WORDS):
            logger.info("📊 DYNAMIC CHART")
            chart_result = analyzer.generate_dynamic_chart(question, dark=False)
            fig = chart_result['fig']
            if fig is None:
                analysis = f"❌ {chart_result['error'] or 'No data available yet for that chart.'}"
                return AnalysisResponse(question=question, analysis=analysis, chart=None)
            spec = chart_result['spec']
            chart_img = chart_generator.figure_to_base64(fig)
            analysis = f"📊 **{spec.get('title')}**\n\n{chart_result['summary']}\n✅ Chart generated"
            return AnalysisResponse(question=question, analysis=analysis, chart=chart_img)

        if question_lower == 'help':
            help_text = """🤖 **PesaPilot v2.1 - Your AI Financial Assistant**

📊 **CHARTS** (Describe what you want, in your own words):
  • "Pie chart of my spending by category last month"
  • "Bar chart of my top 5 recipients in August"
  • "Show my transport spending as a line chart this year"
  • "How much has M-Pesa charged me in fees this month?"
  • "Heatmap of my spending by day of the week"
  • "Distribution of my transaction amounts last 90 days"
  • Any chart type (bar/pie/line/area/scatter/histogram/heatmap) + any date
    range (a specific month, "last week", "Q1", exact dates, "all time")

💬 **QUESTIONS** (Ask naturally):
  • "What did I spend on food?"
  • "Top 5 expenses?"
  • "How much to Safaricom?"

💡 **ADVICE**:
  • "Give me a budget plan" → Personalized KES budget split
  • "What should I invest in?" → Sacco / MMF / T-Bill guidance

📋 **REPORTS**:
  • "Summary" → Last 30 days
  • "Daily summary" / "Today" → Today's overview
  • "90 days" / "All time" → Extended periods

📱 **MANUAL SMS**:
  • PIN-PASTE_SMS_HERE (e.g., 1234-UFMD8OKA...)

🔮 **FORECASTING**:
  • "Forecast" / "Forecast 7 days" → Next 7-day spending prediction
  • "Forecast 30 days" → Next 30-day spending prediction
  • "Spending prediction" → Same as "forecast"
  • Returns predicted amount, trend, risk level + AI summary

🕵️ **ANOMALY DETECTION**:
  • "Anomalies" / "Unusual spending" → ML-flagged unusual transactions
  • Learns YOUR normal pattern per category, not a generic threshold

🎯 **BUDGET GOALS**:
  • "Set budget food 5000" → Monthly food budget of KES 5,000
  • "Set budget transport 3000 weekly" → Weekly transport budget
  • "My budgets" / "Budget status" → Current spend vs each limit
  • I'll proactively ping you here if you get close to or go over

✨ Just ask naturally! Charts & analysis are smart."""
            return AnalysisResponse(question=request.question, analysis=help_text)

        if 'daily' in question_lower or 'today' in question_lower:
            analysis = generate_daily_summary()
            return AnalysisResponse(question=request.question, analysis=analysis)

        if 'summary' in question_lower:
            days = parse_days_from_question(question_lower, default=30)

            logger.info(f"📊 Summary: {days}d")
            summary = analyzer.db.get_range_summary(days=days)

            if summary and summary.get('total_transactions', 0) > 0:
                spent = summary.get('total_spent', 0)
                received = summary.get('total_received', 0)
                balance = summary.get('balance', 0)
                transactions = summary.get('total_transactions', 0)

                analysis = f"""📊 **{days}-Day Financial Summary**

💰 Transactions: {transactions}
💸 Total Spent: KES {spent:,.0f}
💵 Total Received: KES {received:,.0f}
📈 Net: KES {received - spent:,.0f}
⚖️ Balance: KES {balance:,.0f}

**Analytics:**
- Daily Average: KES {spent / max(days, 1):,.0f}
- Per Transaction: KES {spent / max(transactions, 1):,.0f}
- Net Position: {'⚠️ Deficit (spent more than received)' if spent > received else '✅ Surplus (received more than spent)'}"""
            else:
                analysis = "📭 No transactions in this period. Start tracking now!"

            return AnalysisResponse(question=request.question, analysis=analysis)

        logger.info("🔄 AI analysis")
        result = analyzer.ask_question(question)

        if result.get('error'):
            analysis = f"⚠️ {clean_response(result.get('error', 'Error'))}"
        else:
            analysis = clean_response(result.get('analysis', 'No response'))

        return AnalysisResponse(question=request.question, analysis=analysis, error=result.get('error'))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Server error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)[:100]}") from e

@app.post("/parse-sms", response_model=ParseSMSResponse)
async def parse_sms(request: ParseSMSRequest):
    try:
        sms_content = request.sms_content.strip()

        if not sms_content:
            raise HTTPException(status_code=400, detail="SMS content required")

        if not is_valid_mpesa_sms(sms_content):
            return ParseSMSResponse(success=False, summary="❌ Not an M-Pesa SMS")

        logger.info(f"📨 SMS: {sms_content[:50]}")

        result = analyzer.parse_and_insert_sms(sms_content)

        if result.get('success'):
            return ParseSMSResponse(
                success=True,
                summary=f"✅ {result.get('summary', 'SMS parsed successfully')}"
            )
        else:
            return ParseSMSResponse(
                success=False,
                summary=f"❌ {result.get('error', 'Could not parse SMS')}"
            )

    except Exception as e:
        logger.error(f"SMS parse error: {str(e)}")
        return ParseSMSResponse(success=False, summary=f"❌ Error: {str(e)[:100]}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=WHATSAPP_API_PORT, log_level="warning")
