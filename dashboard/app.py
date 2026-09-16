import sys
import os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
import re
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import logging
from typing import Optional, Any
from src.analyzer import MpesaAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="PesaPilot",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background: #0f1117; }
    [data-testid="stSidebar"] { background: #1a1d2e; }
    .metric-card {
        background: #1e2130;
        border-radius: 12px;
        padding: 20px;
        border: 1px solid #2d3250;
        text-align: center;
    }
    .metric-value { font-size: 2rem; font-weight: 700; color: #00d4aa; }
    .metric-label { font-size: 0.85rem; color: #8892a4; margin-top: 4px; }
    .chat-msg-user {
        background: #2d3250;
        border-radius: 12px 12px 2px 12px;
        padding: 12px 16px;
        margin: 8px 0;
        color: #e8eaf0;
        text-align: right;
    }
    .chat-msg-bot {
        background: #1e2130;
        border-radius: 12px 12px 12px 2px;
        padding: 12px 16px;
        margin: 8px 0;
        color: #e8eaf0;
        border-left: 3px solid #00d4aa;
    }
    .sql-box {
        background: #12141f;
        border-radius: 8px;
        padding: 10px 14px;
        font-family: monospace;
        font-size: 0.8rem;
        color: #7ec8e3;
        border: 1px solid #2d3250;
    }
    .anomaly-badge {
        background: #ff4b6e22;
        border: 1px solid #ff4b6e;
        border-radius: 8px;
        padding: 8px 12px;
        color: #ff4b6e;
        font-size: 0.85rem;
    }
    h1, h2, h3 { color: #e8eaf0 !important; }
    .stPlotlyChart { border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

PLOTLY_DARK: dict[str, Any] = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font_color='#8892a4',
    margin=dict(l=0, r=0, t=40, b=0),
)


DANGEROUS_KEYWORDS = ['DELETE', 'DROP', 'TRUNCATE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE', 'ATTACH', 'REPLACE', 'MERGE', 'CALL']

FORECAST_KEYWORDS = [
    'forecast', 'spending prediction', 'predict my spending', 'spending forecast',
    'projected spending', 'predict spending', 'future spending',
]

BUDGET_KEYWORDS = ['budget plan', 'budget', 'how should i budget', 'monthly plan', 'allocate my money', 'allocate income']
INVEST_KEYWORDS = ['invest', 'investment', 'where to invest', 'grow my money', 'grow savings', 'mmf', 'money market fund',
                    'treasury bill', 't-bill', 'sacco', 'put my money']

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

CHART_TRIGGER_WORDS = [
    'bar chart', 'pie chart', 'donut chart', 'doughnut chart', 'line chart', 'area chart',
    'scatter chart', 'scatter plot', 'box plot', 'boxplot', 'boxen plot', 'violin plot',
    'stacked bar', 'stacked chart',
    'bar', 'pie', 'donut', 'doughnut', 'trend', 'line', 'area', 'heatmap', 'heat map',
    'histogram', 'distribution', 'spread', 'variability', 'consistency', 'outlier', 'outliers',
    'violin', 'stacked', 'chart', 'graph', 'plot', 'draw', 'diagram', 'visualize', 'visualise',
    'over days', 'over time', 'spending over', 'daily trend', 'weekly',
    'merchants', 'top merchants', 'top recipients', 'recipients', 'top spending',
    'breakdown of', 'spending by', 'spending per', 'where did i spend', 'where did my money go',
    'how did i spend', 'proportion', 'percentage of my spending', 'compare my spending',
    'show me my spending', 'show my spending', 'transaction costs', 'transaction fees',
]

HELP_TEXT = """🤖 **PesaPilot v1.2 - Your AI Financial Assistant**

📊 **CHARTS** (Describe what you want, in your own words):
  • "Pie chart of my spending by category last month"
  • "Donut chart of my spending by category"
  • "Bar chart of my top 5 recipients in August"
  • "Show my transport spending as a line chart this year"
  • "How much has M-Pesa charged me in fees this month?"
  • "Heatmap of my spending by day of the week"
  • "Stacked bar of my spending by category and day"
  • "Distribution of my transaction amounts last 90 days"
  • "Spread of my food spending" or "Violin plot of my spending by category"
  • Any chart type (bar/pie/donut/line/area/scatter/histogram/heatmap/
    box/violin/stacked bar) + any date range (a specific month, "last
    week", "Q1", exact dates, "all time")

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

🔮 **FORECASTING**:
  • "Forecast" / "Forecast 7 days" → Next 7-day spending prediction
  • "Forecast 30 days" → Next 30-day spending prediction
  • "Spending prediction" → Same as "forecast"
  • Returns predicted amount, trend, risk level + AI summary

🕵️ **ANOMALY DETECTION**:
  • "Anomalies" / "Unusual spending" → ML-flagged unusual transactions
  • Learns YOUR normal pattern per category, not a generic threshold
  • Also browsable on the 🕵️ Anomalies page in the sidebar

🎯 **BUDGET GOALS**:
  • "Set budget food 5000" → Monthly food budget of KES 5,000
  • "Set budget transport 3000 weekly" → Weekly transport budget
  • "My budgets" / "Budget status" → Current spend vs each limit
  • Manage budgets anytime on the 🎯 Budgets page in the sidebar

✨ Just ask naturally! Charts & analysis are smart."""


def is_safe_question(question: str) -> bool:
    question_upper = question.upper()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in question_upper:
            return False
    if '--' in question or '/*' in question:
        return False
    return True


def clean_response(text: str) -> str:
    jargon = ['postgresql', 'postgres', 'schema', 'database', 'query', 'sql', 'rpc']
    for word in jargon:
        text = re.sub(word, '', text, flags=re.IGNORECASE)
    return re.sub(r' +', ' ', text).strip()


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


def parse_forecast_horizon(question_lower: str, default: int = 7) -> int:
    if 'month' in question_lower or re.search(r'\b30\b', question_lower):
        return 30
    if 'week' in question_lower or re.search(r'\b7\b', question_lower):
        return 7
    return default


def generate_daily_summary_text(analyzer: "MpesaAnalyzer") -> str:
    try:
        summary = analyzer.db.get_today_summary()

        if not summary or summary.get('total_transactions', 0) == 0:
            return "📭 No transactions recorded today.\n\nStart tracking by adding M-Pesa transactions."

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


def generate_summary_text(analyzer: "MpesaAnalyzer", days: int) -> str:
    summary = analyzer.db.get_range_summary(days=days)

    if summary and summary.get('total_transactions', 0) > 0:
        spent = summary.get('total_spent', 0)
        received = summary.get('total_received', 0)
        balance = summary.get('balance', 0)
        transactions = summary.get('total_transactions', 0)

        return f"""📊 **{days}-Day Financial Summary**

💰 Transactions: {transactions}
💸 Total Spent: KES {spent:,.0f}
💵 Total Received: KES {received:,.0f}
📈 Net: KES {received - spent:,.0f}
⚖️ Balance: KES {balance:,.0f}

**Analytics:**
- Daily Average: KES {spent / max(days, 1):,.0f}
- Per Transaction: KES {spent / max(transactions, 1):,.0f}
- Net Position: {'⚠️ Deficit (spent more than received)' if spent > received else '✅ Surplus (received more than spent)'}"""

    return "📭 No transactions in this period. Start tracking now!"


def chat_bar_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str) -> Optional[go.Figure]:
    if df is None or df.empty or category_col not in df.columns or value_col not in df.columns:
        return None
    chart_data = df.groupby(category_col)[value_col].sum().sort_values(ascending=True).tail(15)
    if chart_data.empty:
        return None
    fig = px.bar(
        x=chart_data.values, y=chart_data.index, orientation='h',
        color=chart_data.values, color_continuous_scale='teal',
        text=[f"KES {v:,.0f}" for v in chart_data.values],
        labels={'x': 'Amount (KES)', 'y': ''},
    )
    fig.update_traces(textposition='outside')
    fig.update_layout(
        **PLOTLY_DARK, title=title, coloraxis_showscale=False,
        xaxis=dict(gridcolor='#2d3250'), yaxis=dict(gridcolor='#2d3250'),
    )
    return fig


def chat_forecast_chart(forecast_data: dict, title: str) -> Optional[go.Figure]:
    hist_points: list = forecast_data.get('historical', [])[-60:]
    forecast_points: list = forecast_data.get('forecast', [])
    if not hist_points and not forecast_points:
        return None

    fig = go.Figure()

    if hist_points:
        df_hist = pd.DataFrame(hist_points)
        fig.add_trace(go.Scatter(
            x=df_hist['date'], y=df_hist['amount'], name='Historical',
            mode='lines+markers', line=dict(color='#00d4aa', width=2), marker=dict(size=4),
        ))

    if forecast_points:
        df_fcst = pd.DataFrame(forecast_points).reset_index(drop=True)
        fig.add_trace(go.Scatter(
            x=df_fcst['date'], y=df_fcst['predicted'], name='Forecast',
            mode='lines+markers', line=dict(color='#ff4b6e', width=2, dash='dash'), marker=dict(size=5),
        ))
        dates_fwd = df_fcst['date'].tolist()
        dates_rev = df_fcst['date'].tolist()[::-1]
        upper_fwd = df_fcst['upper'].tolist()
        lower_rev = df_fcst['lower'].tolist()[::-1]
        fig.add_trace(go.Scatter(
            x=dates_fwd + dates_rev, y=upper_fwd + lower_rev, fill='toself',
            fillcolor='rgba(255,75,110,0.15)', line=dict(color='rgba(255,255,255,0)'),
            name='Confidence Interval', hoverinfo='skip',
        ))

    fig.update_layout(
        **PLOTLY_DARK, title=title,
        xaxis=dict(gridcolor='#2d3250'), yaxis=dict(gridcolor='#2d3250'),
    )
    return fig


@st.cache_resource
def get_analyzer() -> MpesaAnalyzer:
    return MpesaAnalyzer()


def fmt_ksh(amount: Optional[float]) -> str:
    if amount is None:
        return "KES 0"
    return f"KES {float(amount):,.0f}"


def route_ask_ai_question(analyzer: "MpesaAnalyzer", question: str) -> dict:

    if not question or len(question) < 2 or len(question) > 500:
        return {'content': "⚠️ Question too short or too long (2-500 chars).", 'sql': None, 'results': None, 'fig': None}

    if not is_safe_question(question):
        logger.warning("🚨 BLOCKED: Destructive operation")
        return {'content': "⚠️ Invalid question.", 'sql': None, 'results': None, 'fig': None}

    question_lower = question.lower().strip()


    if (question_lower.startswith('set budget') or question_lower.startswith('budget limit')
            or (question_lower.startswith('set ') and 'budget' in question_lower
                and _HAS_DIGIT.search(question_lower))):
        logger.info("🎯 SET BUDGET")
        match = SET_BUDGET_PATTERN.search(question)
        if match:
            category = (match.group('category') or match.group('category2')).strip().lower()
            amount = float((match.group('amount') or match.group('amount2')).replace(',', ''))
            period = (match.group('period') or 'monthly').lower()
            result = analyzer.set_budget(category, amount, period=period)
            if result.get('success'):
                content = (
                    f"🎯 Budget set: {category.title()} — KES {amount:,.0f} per {period}.\n"
                    f"Check the 🎯 Budgets page anytime to see progress."
                )
            else:
                content = f"❌ Couldn't set that budget: {result.get('error', 'unknown error')}"
        else:
            content = "❌ Couldn't read that. Try: \"set budget food 5000\" or \"set budget transport 3000 weekly\""
        return {'content': clean_response(content), 'sql': None, 'results': None, 'fig': None}

    if any(k in question_lower for k in BUDGET_STATUS_KEYWORDS):
        logger.info("🎯 BUDGET STATUS")
        status_rows = analyzer.get_budgets_overview()
        if not status_rows:
            content = "📭 No budgets set yet. Try: \"set budget food 5000\" to create one, or use the 🎯 Budgets page."
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
            content = "\n".join(lines)
        return {'content': clean_response(content), 'sql': None, 'results': None, 'fig': None}

    if any(k in question_lower for k in BUDGET_KEYWORDS):
        logger.info("📋 BUDGET PLAN")
        context = analyzer.build_context_string(days=30)
        analysis = analyzer.groq.budget_plan(context=context)
        return {'content': clean_response(analysis), 'sql': None, 'results': None, 'fig': None}

    if any(k in question_lower for k in INVEST_KEYWORDS):
        logger.info("📈 INVESTMENT ADVICE")
        context = analyzer.build_context_string(days=30)
        analysis = analyzer.groq.investment_advice(context=context)
        return {'content': clean_response(analysis), 'sql': None, 'results': None, 'fig': None}

    if any(k in question_lower for k in FORECAST_KEYWORDS):
        logger.info("🔮 FORECAST")
        horizon = parse_forecast_horizon(question_lower, default=7)
        forecast_data = analyzer.get_forecast(horizon_days=horizon)

        if not forecast_data.get('sufficient_data'):
            msg = forecast_data.get('message', 'Not enough transaction history yet for a forecast.')
            return {'content': f"📉 {clean_response(msg)}", 'sql': None, 'results': None, 'fig': None}

        fig = chat_forecast_chart(forecast_data, title=f"🔮 {horizon}-Day Spending Forecast")

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
        content = clean_response(header + (f"\n💡 {ai_summary}" if ai_summary else ""))
        return {'content': content, 'sql': None, 'results': None, 'fig': fig}

    if any(k in question_lower for k in ANOMALY_KEYWORDS):
        logger.info("🕵️ ML ANOMALY DETECTION")
        anomaly_days = parse_days_from_question(question_lower, default=90)
        result = analyzer.get_smart_anomalies(days=anomaly_days, force_refresh=False)
        flagged = result.get('anomalies', [])

        fig = None
        if flagged:
            df = pd.DataFrame(flagged)
            fig = chat_bar_chart(
                df, 'recipient', 'amount',
                title=f"🕵️ Unusual Transactions (last {anomaly_days}d)"
            )
            header = f"🕵️ **{len(flagged)} Unusual Transaction(s) Found (last {anomaly_days} days)**\n\n"
        else:
            header = f"✅ **No Unusual Transactions (last {anomaly_days} days)**\n\n"

        content = clean_response(header + result.get('insight', ''))
        return {'content': content, 'sql': None, 'results': None, 'fig': fig}

    if any(w in question_lower for w in CHART_TRIGGER_WORDS):
        logger.info("📊 DYNAMIC CHART")
        chart_result = analyzer.generate_dynamic_chart(question, dark=True)
        fig = chart_result['fig']
        if fig is None:
            content = f"❌ {chart_result['error'] or 'No data available yet for that chart.'}"
            return {'content': content, 'sql': None, 'results': None, 'fig': None}
        spec = chart_result['spec']
        content = f"📊 **{spec.get('title')}**\n\n{chart_result['summary']}\n✅ Chart generated"
        return {'content': content, 'sql': None, 'results': None, 'fig': fig}

    if question_lower == 'help':
        return {'content': HELP_TEXT, 'sql': None, 'results': None, 'fig': None}

    if 'daily' in question_lower or 'today' in question_lower:
        return {'content': generate_daily_summary_text(analyzer), 'sql': None, 'results': None, 'fig': None}

    if 'summary' in question_lower:
        days = parse_days_from_question(question_lower, default=30)
        return {'content': generate_summary_text(analyzer, days), 'sql': None, 'results': None, 'fig': None}

    result = analyzer.ask_question(question)
    if result.get('error'):
        content = f"⚠️ {clean_response(result.get('error', 'Error'))}"
    else:
        content = clean_response(result.get('analysis', 'No response'))

    return {
        'content': content,
        'sql': result.get('sql', ''),
        'results': result.get('results', []),
        'fig': None,
    }
def main() -> None:
    analyzer: MpesaAnalyzer = get_analyzer()

    with st.sidebar:
        st.markdown("## 💸 PesaPilot")
        st.markdown("*Your M-Pesa Financial Advisor*")
        st.divider()

        page: str = st.radio("Navigate", ["📊 Dashboard", "🔮 Forecast", "🎯 Budgets", "💬 Ask AI", "📋 Transactions", "🕵️ Anomalies"])
        st.divider()

        days: int = st.slider("Analysis period (days)", 7, 180, 30)

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Loading your financial data..."):
        data: dict[str, Any] = analyzer.get_dashboard_data(days=days)

    summary: dict[str, Any] = data.get('summary', {})
    category_data: list[dict[str, Any]] = data.get('spending_by_category', [])
    daily_trend: list[dict[str, Any]] = data.get('daily_trend', [])
    top_merchants: list[dict[str, Any]] = data.get('top_merchants', [])
    recent_txs: list[dict[str, Any]] = data.get('recent_transactions', [])
    insights: str = data.get('insights', '')

    if page == "📊 Dashboard":
        st.title("📊 Financial Dashboard")
        st.caption(f"Last {days} days · M-Pesa transaction analysis")

        c1, c2, c3, c4 = st.columns(4)
        metrics: list[tuple[Any, str, Any]] = [
            (c1, "Total Transactions", summary.get('total_transactions', 0)),
            (c2, "Total Spent",        fmt_ksh(summary.get('total_spent', 0))),
            (c3, "Total Received",     fmt_ksh(summary.get('total_received', 0))),
            (c4, "Avg Transaction",    fmt_ksh(summary.get('avg_spend', 0))),
        ]
        for col, label, value in metrics:
            with col:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">{value}</div>
                    <div class="metric-label">{label}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("")

        col_left, col_right = st.columns([1.2, 0.8])

        with col_left:
            st.subheader("Daily Spending Trend")
            if daily_trend:
                df_trend: pd.DataFrame = pd.DataFrame(daily_trend)
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_trend['date'], y=df_trend['total_spent'],
                    name='Spent', fill='tozeroy',
                    line=dict(color='#ff4b6e', width=2),
                    fillcolor='rgba(255,75,110,0.1)'
                ))
                fig.add_trace(go.Scatter(
                    x=df_trend['date'], y=df_trend['total_received'],
                    name='Received', fill='tozeroy',
                    line=dict(color='#00d4aa', width=2),
                    fillcolor='rgba(0,212,170,0.1)'
                ))
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#8892a4',
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis=dict(gridcolor='#2d3250'),
                    yaxis=dict(gridcolor='#2d3250'),
                    legend=dict(bgcolor='rgba(0,0,0,0)'),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No trend data available.")

        with col_right:
            st.subheader("Spending by Category")
            if category_data:
                df_cat: pd.DataFrame = pd.DataFrame(category_data)
                fig = px.pie(
                    df_cat.head(8),
                    values='total_amount',
                    names='merchant_category',
                    hole=0.55,
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    font_color='#8892a4',
                    legend=dict(bgcolor='rgba(0,0,0,0)'),
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No category data available.")

        col_l2, col_r2 = st.columns(2)

        with col_l2:
            st.subheader("Top Merchants")
            if top_merchants:
                df_merch: pd.DataFrame = pd.DataFrame(top_merchants)
                fig = px.bar(
                    df_merch,
                    x='total_amount',
                    y='recipient',
                    orientation='h',
                    color='total_amount',
                    color_continuous_scale='teal',
                    labels={'total_amount': 'Amount (KES)', 'recipient': ''},
                )
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#8892a4',
                    margin=dict(l=0, r=0, t=10, b=0),
                    coloraxis_showscale=False,
                    xaxis=dict(gridcolor='#2d3250'),
                    yaxis=dict(autorange='reversed', gridcolor='#2d3250'),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No merchant data available.")

        with col_r2:
            st.subheader("💡 AI Insights")
            if insights:
                st.markdown(f"""
                <div style="background:#1e2130;border-radius:12px;padding:16px;border:1px solid #2d3250;color:#c8cdd8;line-height:1.7;">
                {insights.replace(chr(10), '<br>')}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Load transactions to generate insights.")

        st.markdown("---")
        col_h1, col_h2 = st.columns(2)

        with col_h1:
            st.subheader("🔥 Spending Heatmap")
            st.caption(f"KES per category per day of week (last {days} days)")
            raw_for_heat: list[dict[str, Any]] = analyzer.db.get_transactions(days=days, limit=5000)
            if raw_for_heat:
                df_heat: pd.DataFrame = pd.DataFrame(raw_for_heat)
                df_heat = df_heat[df_heat['type'] != 'credit'].copy()
                if not df_heat.empty and 'timestamp' in df_heat.columns:
                    df_heat['timestamp'] = pd.to_datetime(df_heat['timestamp'], format='ISO8601', errors='coerce')
                    df_heat = df_heat.dropna(subset=['timestamp'])
                    df_heat['merchant_category'] = df_heat['merchant_category'].fillna('other')
                    df_heat['amount'] = pd.to_numeric(df_heat['amount'], errors='coerce').fillna(0)
                    df_heat['day'] = df_heat['timestamp'].dt.day_name()

                    pivot = df_heat.pivot_table(
                        values='amount',
                        index='merchant_category',
                        columns='day',
                        aggfunc='sum',
                        fill_value=0,
                    )
                    day_order: list[str] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    available: list[str] = [d for d in day_order if d in pivot.columns]

                    if available and not pivot.empty:
                        pivot = pivot[available]
                        fig = px.imshow(
                            pivot,
                            labels=dict(x="Day of Week", y="Category", color="KES"),
                            color_continuous_scale='YlOrRd',
                            aspect='auto',
                            text_auto='.0f',
                        )
                        fig.update_layout(
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            font_color='#8892a4',
                            margin=dict(l=0, r=0, t=10, b=0),
                            coloraxis_colorbar=dict(title="KES"),
                            xaxis=dict(gridcolor='#2d3250'),
                            yaxis=dict(gridcolor='#2d3250'),
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Not enough data for a heatmap yet.")
                else:
                    st.info("No spending data found.")
            else:
                st.info("Load transactions to see the spending heatmap.")

        with col_h2:
            st.subheader("📊 Amount Distribution")
            st.caption(f"Frequency of transaction sizes (last {days} days)")
            if recent_txs:
                df_hist: pd.DataFrame = pd.DataFrame(recent_txs)
                df_hist = df_hist[df_hist['type'] != 'credit'].copy()
                if not df_hist.empty and 'amount' in df_hist.columns:
                    fig = px.histogram(
                        df_hist,
                        x='amount',
                        nbins=20,
                        labels={'amount': 'Amount (KES)', 'count': 'Transactions'},
                        color_discrete_sequence=['#2E86AB'],
                    )
                    mean_val: float = df_hist['amount'].mean()
                    fig.add_vline(x=mean_val, line_dash='dash', line_color='#ff4b6e',
                                  annotation_text=f"Avg KES {mean_val:,.0f}",
                                  annotation_position="top right")
                    fig.update_layout(
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        font_color='#8892a4',
                        margin=dict(l=0, r=0, t=10, b=0),
                        xaxis=dict(gridcolor='#2d3250'),
                        yaxis=dict(gridcolor='#2d3250'),
                        bargap=0.05,
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No debit transactions to chart.")
            else:
                st.info("No transaction data available.")

    elif page == "🔮 Forecast":
        st.title("🔮 Spending Forecast")
        st.caption("AI-projected spending based on your real transaction history")

        horizon_label = st.radio("Forecast horizon", ["7 days", "30 days"], horizontal=True)
        horizon_days = 7 if horizon_label == "7 days" else 30

        with st.spinner("Training forecast model..."):
            forecast_data: dict[str, Any] = analyzer.get_forecast(horizon_days=horizon_days)

        if not forecast_data.get('sufficient_data'):
            st.info(forecast_data.get('message', 'Not enough transaction history yet for a forecast.'))
        else:
            fc1, fc2, fc3, fc4 = st.columns(4)
            trend_emoji = {'Increasing': '📈', 'Decreasing': '📉', 'Stable': '➡️'}.get(
                forecast_data.get('trend', 'Stable'), '➡️'
            )
            risk_emoji = {'Low': '🟢', 'Moderate': '🟡', 'High': '🔴'}.get(
                forecast_data.get('risk_level', 'Low'), '🟢'
            )
            forecast_metrics: list[tuple[Any, str, Any]] = [
                (fc1, "Predicted Spend",  fmt_ksh(forecast_data.get('total_predicted', 0))),
                (fc2, "Avg per Day",      fmt_ksh(forecast_data.get('avg_predicted_daily', 0))),
                (fc3, "Trend",            f"{trend_emoji} {forecast_data.get('trend', 'Stable')}"),
                (fc4, "Risk Level",       f"{risk_emoji} {forecast_data.get('risk_level', 'Low')}"),
            ]
            for col, label, value in forecast_metrics:
                with col:
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-value">{value}</div>
                        <div class="metric-label">{label}</div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("")
            st.subheader("Historical Spending + Forecast")

            fig = chat_forecast_chart(forecast_data, title="")
            if fig:
                fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig, use_container_width=True)

            insight: str = forecast_data.get('insight', '')
            if insight:
                st.subheader("💡 AI Insight")
                st.markdown(f"""
                <div style="background:#1e2130;border-radius:12px;padding:16px;border:1px solid #2d3250;color:#c8cdd8;line-height:1.7;">
                {insight.replace(chr(10), '<br>')}
                </div>
                """, unsafe_allow_html=True)

            st.caption(f"Based on {forecast_data.get('history_days', 0)} days of spending history")

    elif page == "🎯 Budgets":
        st.title("🎯 Budget Goals")
        st.caption("Set spending limits per category and track progress live")

        budgets: list[dict[str, Any]] = analyzer.get_budgets_overview()

        st.subheader("Current Budgets")
        if budgets:
            for row in budgets:
                limit_amt = float(row.get('limit_amount') or 0)
                spent_amt = float(row.get('spent_this_period') or 0)
                pct = (spent_amt / limit_amt * 100) if limit_amt else 0
                threshold = float(row.get('alert_threshold_pct') or 80)
                icon = "🔴" if pct >= 100 else "🟡" if pct >= threshold else "🟢"

                bc1, bc2 = st.columns([3, 1])
                with bc1:
                    st.markdown(
                        f"**{icon} {str(row.get('category', '')).title()}** "
                        f"({row.get('period', 'monthly')}) — "
                        f"KES {spent_amt:,.0f} / {limit_amt:,.0f} ({pct:.0f}%)"
                    )
                    st.progress(min(pct / 100, 1.0))
                with bc2:
                    st.caption(f"Alert at {threshold:.0f}%")
                st.markdown("")
        else:
            st.info("No budgets set yet. Create one below.")

        st.divider()

        st.subheader("Set / Update a Budget")
        st.caption("Setting a budget for a category + period you've already used updates its limit.")
        with st.form("set_budget_form", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                category_input: str = st.selectbox(
                    "Category", list(CATEGORY_SYNONYMS.keys()),
                    format_func=lambda c: c.title(),
                )
            with fc2:
                limit_input: float = st.number_input("Monthly/weekly limit (KES)", min_value=0.0, step=500.0)
            with fc3:
                period_input: str = st.selectbox("Period", ["monthly", "weekly"])
            threshold_input: int = st.slider("Alert threshold (%)", min_value=50, max_value=100, value=80, step=5)

            submitted = st.form_submit_button("💾 Save Budget", use_container_width=True)
            if submitted:
                if limit_input <= 0:
                    st.error("Enter a limit greater than 0.")
                else:
                    result = analyzer.set_budget(
                        category_input, limit_input, period=period_input,
                        alert_threshold_pct=threshold_input,
                    )
                    if result.get('success'):
                        st.success(f"Budget saved: {category_input.title()} — KES {limit_input:,.0f} per {period_input}.")
                        st.rerun()
                    else:
                        st.error(f"Could not save budget: {result.get('error', 'unknown error')}")

        st.divider()
        st.subheader("Check for New Alerts")
        st.caption(
            "The WhatsApp bot checks this automatically every 2 hours and pings you when a budget "
            "crosses its threshold. Use this button to check right now instead of waiting."
        )
        if st.button("🔔 Check Now", use_container_width=True):
            with st.spinner("Checking budgets..."):
                new_alerts: list[dict[str, Any]] = analyzer.check_budget_alerts()
            if new_alerts:
                for alert in new_alerts:
                    icon = "🚨" if alert.get('alert_level') == 'over' else "⚠️"
                    st.warning(f"{icon} {alert.get('message', '')}")
            else:
                st.success("✅ Nothing new to report — no budgets have newly crossed their threshold.")

    elif page == "💬 Ask AI":
        st.title("💬 Ask PesaPilot")
        st.caption("Ask anything about your M-Pesa transactions — same commands as the WhatsApp bot")

        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []

        suggestions: list[str] = [
            "What did I spend most on this month?",
            "Give me a budget plan",
            "What should I invest in?",
            "Forecast my spending",
            "Any unusual spending?",
            "My budgets",
            "Bar chart",
            "help",
        ]
        st.markdown("**Quick questions:**")
        cols = st.columns(3)
        for i, q in enumerate(suggestions):
            with cols[i % 3]:
                if st.button(q, key=f"sugg_{i}", use_container_width=True):
                    st.session_state.pending_question = q

        st.divider()

        for i, msg in enumerate(st.session_state.chat_history):
            if msg['role'] == 'user':
                st.markdown(f'<div class="chat-msg-user">🧑 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-msg-bot">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
                if msg.get('fig') is not None:
                    fig_obj = msg['fig']
                    if hasattr(fig_obj, 'savefig'):
                        st.pyplot(fig_obj, use_container_width=True)
                    else:
                        st.plotly_chart(fig_obj, use_container_width=True, key=f"chat_fig_{i}")
                if msg.get('sql'):
                    with st.expander("View SQL", expanded=False):
                        st.markdown(f'<div class="sql-box">{msg["sql"]}</div>', unsafe_allow_html=True)
                if msg.get('results'):
                    with st.expander(f"View results ({len(msg['results'])} rows)", expanded=False):
                        st.dataframe(pd.DataFrame(msg['results']).head(20), use_container_width=True)

        pending = st.session_state.pop('pending_question', None)
        question: Optional[str] = st.chat_input("Ask about your spending...") or pending

        if question:
            st.session_state.chat_history.append({'role': 'user', 'content': question})
            with st.spinner("Thinking..."):
                routed = route_ask_ai_question(analyzer, question)
            bot_msg: dict[str, Any] = {
                'role': 'bot',
                'content': routed['content'],
                'sql': routed.get('sql'),
                'results': routed.get('results'),
                'fig': routed.get('fig'),
            }
            st.session_state.chat_history.append(bot_msg)
            st.rerun()

    elif page == "📋 Transactions":
        st.title("📋 Recent Transactions")
        if recent_txs:
            df: pd.DataFrame = pd.DataFrame(recent_txs)
            cols_show: list[str] = [c for c in ['timestamp', 'type', 'amount', 'recipient', 'merchant_category', 'balance'] if c in df.columns]
            df_show: pd.DataFrame = df[cols_show].copy()
            if 'amount' in df_show.columns:
                df_show['amount'] = df_show['amount'].apply(lambda x: f"KES {x:,.2f}" if x else '')
            if 'balance' in df_show.columns:
                df_show['balance'] = df_show['balance'].apply(lambda x: f"KES {x:,.2f}" if x else '')

            fc1, fc2 = st.columns(2)
            with fc1:
                tx_types: list[str] = ['All'] + sorted(df['type'].dropna().unique().tolist())
                selected_type: str = st.selectbox("Transaction type", tx_types)
            with fc2:
                cats: list[str] = ['All'] + sorted(df['merchant_category'].dropna().unique().tolist())
                selected_cat: str = st.selectbox("Category", cats)

            mask: pd.Series = pd.Series([True] * len(df))
            if selected_type != 'All':
                mask &= df['type'] == selected_type
            if selected_cat != 'All':
                mask &= df['merchant_category'] == selected_cat

            st.dataframe(df_show[mask], use_container_width=True, height=500)
            st.caption(f"Showing {mask.sum()} transactions")
        else:
            st.info("No transactions found. Load your M-Pesa XML backup to get started.")

    elif page == "🕵️ Anomalies":
        st.title("🕵️ Unusual Transactions")
        st.caption(
            "ML-flagged transactions that stand out from YOUR OWN normal pattern in that "
            "category — not compared to other people. Some flagged items are perfectly "
            "legitimate one-offs (a big one-time purchase, a rare emergency)."
        )

        anom_days: int = st.slider("Lookback period (days)", 14, 180, 90, key="anomaly_days_slider")
        force_refresh: bool = st.button("🔄 Re-run detection now", use_container_width=False)

        with st.spinner("Scanning your spending pattern..."):
            smart_result: dict[str, Any] = analyzer.get_smart_anomalies(days=anom_days, force_refresh=force_refresh)

        flagged_txs: list[dict[str, Any]] = smart_result.get('anomalies', [])
        insight_text: str = smart_result.get('insight', '')

        if insight_text:
            st.markdown(f"""
            <div style="background:#1e2130;border-radius:12px;padding:16px;border:1px solid #2d3250;color:#c8cdd8;line-height:1.7;">
            💡 {insight_text.replace(chr(10), '<br>')}
            </div>
            """, unsafe_allow_html=True)
            st.markdown("")

        if flagged_txs:
            st.subheader(f"{len(flagged_txs)} Flagged Transaction(s)")
            for a in flagged_txs[:20]:
                score = float(a.get('score', 0))
                model_used = a.get('model', '')
                model_label = "learned pattern" if 'isolation' in model_used else "statistical check"
                st.markdown(f"""
                <div class="anomaly-badge">
                    🕵️ <strong>{a.get('recipient', 'Unknown')}</strong> — KES {float(a.get('amount', 0)):,.2f}
                    &nbsp;·&nbsp; {str(a.get('merchant_category', 'other')).title()}
                    &nbsp;·&nbsp; {str(a.get('timestamp', ''))[:16]}
                    &nbsp;·&nbsp; unusualness score: {score:.1f} ({model_label})
                </div>
                """, unsafe_allow_html=True)
                st.markdown("")
        else:
            st.success(f"✅ No unusual transactions detected in the last {anom_days} days.")


if __name__ == "__main__":
    main()