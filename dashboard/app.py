# dashboard/app.py
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

# ============================================================
# PLOTLY_DARK – removed xaxis/yaxis to avoid conflicts
# ============================================================
PLOTLY_DARK: dict[str, Any] = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font_color='#8892a4',
    margin=dict(l=0, r=0, t=40, b=0),
)

# ============================================================
# ASK-AI ROUTING — duplicated from whatsapp/whatsapp_api.py so the
# dashboard chat understands the same commands as the WhatsApp bot
# (budget plans, investment advice, forecasts, chart requests, daily/
# summary shortcuts, help). Charts are re-implemented in Plotly here
# instead of matplotlib so they match the dashboard's dark theme.
# Kept intentionally independent of whatsapp_api.py — if you change
# behavior in one, mirror it here by hand.
# ============================================================

DANGEROUS_KEYWORDS = ['DELETE', 'DROP', 'TRUNCATE', 'UPDATE', 'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC']

FORECAST_KEYWORDS = [
    'forecast', 'spending prediction', 'predict my spending', 'spending forecast',
    'projected spending', 'predict spending', 'future spending',
]

BUDGET_KEYWORDS = ['budget plan', 'budget', 'how should i budget', 'monthly plan', 'allocate my money', 'allocate income']
INVEST_KEYWORDS = ['invest', 'investment', 'where to invest', 'grow my money', 'grow savings', 'mmf', 'money market fund',
                    'treasury bill', 't-bill', 'sacco', 'put my money']

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

CHART_KEYWORDS = {
    'bar': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
    'bar chart': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
    'pie': ('🥧 Spending Distribution', 'merchant_category', 'total_amount'),
    'pie chart': ('🥧 Spending Distribution', 'merchant_category', 'total_amount'),
    'trend': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'spending trend': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'line': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'line chart': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'over days': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'over time': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'spending over': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'daily trend': ('📈 Daily Spending Trend', 'date', 'total_spent'),
    'heatmap': ('🔥 Weekly Spending Heatmap', None, None),
    'heat map': ('🔥 Weekly Spending Heatmap', None, None),
    'weekly': ('🔥 Weekly Spending Heatmap', None, None),
    'merchants': ('🏆 Top 10 Merchants', 'recipient', 'amount'),
    'top merchants': ('🏆 Top 10 Merchants', 'recipient', 'amount'),
    'top recipients': ('🏆 Top 10 Merchants', 'recipient', 'amount'),
    'recipients': ('🏆 Top 10 Merchants', 'recipient', 'amount'),
    'top spending': ('🏆 Top 10 Merchants', 'recipient', 'amount'),
    'histogram': ('📊 Transaction Distribution', 'amount', None),
    'distribution': ('📊 Transaction Distribution', 'amount', None),
    'amount distribution': ('📊 Transaction Distribution', 'amount', None),
    'chart': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
    'graph': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
    'visualize': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
    'show chart': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
    'show graph': ('💰 Spending by Category', 'merchant_category', 'total_amount'),
}

HELP_TEXT = """🤖 **PesaPilot v2.1 - Your AI Financial Assistant**

📊 **CHARTS** (Visual Analytics):
  • "Bar chart" → Spending by category
  • "Pie chart" → Distribution breakdown
  • "Trend" / "Over days" → Daily spending pattern
  • "Heatmap" → Weekly activity grid
  • "Merchants" → Top 10 recipients
  • "Histogram" → Amount distribution
  • "Visualize" / "Graph"

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
    """Read an explicit time window out of natural language. Falls back to `default`."""
    if 'all time' in question_lower or 'year' in question_lower or '365' in question_lower:
        return 365
    if '180' in question_lower or '6 months' in question_lower:
        return 180
    if '90' in question_lower or '3 months' in question_lower:
        return 90
    if '60' in question_lower:
        return 60
    if 'week' in question_lower or '7 days' in question_lower:
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
    """Read an explicit forecast horizon out of natural language. Defaults to 7 days.
    Only 7 and 30 are supported horizons; anything else falls back to `default`."""
    if 'month' in question_lower or re.search(r'\b30\b', question_lower):
        return 30
    if 'week' in question_lower or re.search(r'\b7\b', question_lower):
        return 7
    return default


def extract_category_filter(question_lower: str) -> Optional[str]:
    """If the question names a known spending category, return its canonical name."""
    for category, synonyms in CATEGORY_SYNONYMS.items():
        for synonym in synonyms:
            if synonym in question_lower:
                return category
    return None


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
    # NOTE: mirrors whatsapp_api.py exactly — get_summary() doesn't take a
    # `days` filter, so `days` is only used in the displayed averages below,
    # not in the underlying query. Kept as-is for parity with the bot.
    summary = analyzer.db.get_summary()

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
- Spending Trend: {'📈 Increasing' if spent > received else '📉 Decreasing'}"""

    return "📭 No transactions in this period. Start tracking now!"


# ── Plotly chart builders for the Ask-AI chat (dark-themed equivalents of
#    the matplotlib charts in whatsapp_api.py) ──────────────────────────────

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


def chat_pie_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str) -> Optional[go.Figure]:
    if df is None or df.empty or category_col not in df.columns or value_col not in df.columns:
        return None
    chart_data = df.groupby(category_col)[value_col].sum().sort_values(ascending=False)
    if chart_data.empty:
        return None
    if len(chart_data) > 8:
        other_sum = chart_data.iloc[8:].sum()
        chart_data = chart_data.iloc[:8].copy()
        if other_sum > 0:
            chart_data['Other'] = other_sum
    fig = px.pie(
        values=chart_data.values, names=chart_data.index, hole=0.55,
        color_discrete_sequence=px.colors.qualitative.Bold,
    )
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', font_color='#8892a4', title=title,
        legend=dict(bgcolor='rgba(0,0,0,0)'), margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


def chat_line_chart(df: pd.DataFrame, date_col: str, value_col: str, title: str) -> Optional[go.Figure]:
    if df is None or df.empty or date_col not in df.columns or value_col not in df.columns:
        return None
    df_sorted = df.sort_values(by=date_col)
    if df_sorted.empty:
        return None
    avg_val = df_sorted[value_col].mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_sorted[date_col], y=df_sorted[value_col], name='Spent',
        mode='lines+markers', fill='tozeroy',
        line=dict(color='#ff4b6e', width=2), fillcolor='rgba(255,75,110,0.1)',
    ))
    fig.add_hline(y=avg_val, line_dash='dash', line_color='#00d4aa',
                  annotation_text=f"Avg: KES {avg_val:,.0f}", annotation_position="top left")
    fig.update_layout(
        **PLOTLY_DARK, title=title,
        xaxis=dict(gridcolor='#2d3250'), yaxis=dict(gridcolor='#2d3250'),
    )
    return fig


def chat_heatmap_chart(df: pd.DataFrame, date_col: str, category_col: str, value_col: str, title: str) -> Optional[go.Figure]:
    if df is None or df.empty or date_col not in df.columns or category_col not in df.columns or value_col not in df.columns:
        return None
    df = df.copy()
    if 'type' in df.columns:
        df = df[df['type'].isin(['debit', 'payment', 'withdrawal'])]
    if df.empty:
        return None
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col])
    if df.empty:
        return None
    df[category_col] = df[category_col].fillna('other')
    df[value_col] = pd.to_numeric(df[value_col], errors='coerce').fillna(0)
    df['day'] = df[date_col].dt.day_name()

    pivot = df.pivot_table(values=value_col, index=category_col, columns='day', aggfunc='sum', fill_value=0)
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    available = [d for d in day_order if d in pivot.columns]
    if not available or pivot.empty or pivot.values.max() == 0:
        return None
    pivot = pivot[available]

    fig = px.imshow(
        pivot, labels=dict(x="Day of Week", y="Category", color="KES"),
        color_continuous_scale='YlOrRd', aspect='auto', text_auto='.0f',
    )
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font_color='#8892a4', title=title, margin=dict(l=0, r=0, t=40, b=0),
        coloraxis_colorbar=dict(title="KES"),
        xaxis=dict(gridcolor='#2d3250'), yaxis=dict(gridcolor='#2d3250'),
    )
    return fig


def chat_top_merchants_chart(df: pd.DataFrame, recipient_col: str, value_col: str, title: str) -> Optional[go.Figure]:
    if df is None or df.empty or recipient_col not in df.columns or value_col not in df.columns:
        return None
    if 'type' in df.columns:
        df = df[df['type'].isin(['debit', 'payment', 'withdrawal'])]
    if df.empty:
        return None
    chart_data = df.groupby(recipient_col)[value_col].sum().sort_values(ascending=True).tail(10)
    if chart_data.empty:
        return None
    fig = px.bar(
        x=chart_data.values, y=chart_data.index, orientation='h',
        color=chart_data.values, color_continuous_scale='RdYlGn_r',
        text=[f"KES {v:,.0f}" for v in chart_data.values],
        labels={'x': 'Total Amount (KES)', 'y': ''},
    )
    fig.update_traces(textposition='outside')
    fig.update_layout(
        **PLOTLY_DARK, title=title, coloraxis_showscale=False,
        xaxis=dict(gridcolor='#2d3250'), yaxis=dict(gridcolor='#2d3250'),
    )
    return fig


def chat_histogram_chart(df: pd.DataFrame, value_col: str, title: str) -> Optional[go.Figure]:
    if df is None or df.empty or value_col not in df.columns:
        return None
    if 'type' in df.columns:
        df = df[df['type'].isin(['debit', 'payment', 'withdrawal'])]
    amounts = pd.to_numeric(df[value_col], errors='coerce').dropna()
    amounts = amounts[amounts > 0]
    if amounts.empty or len(amounts) < 2:
        return None
    mean_val = amounts.mean()
    fig = px.histogram(x=amounts, nbins=25, labels={'x': 'Amount (KES)'}, color_discrete_sequence=['#2196F3'])
    fig.add_vline(x=mean_val, line_dash='dash', line_color='#ff4b6e',
                  annotation_text=f"Avg KES {mean_val:,.0f}", annotation_position="top right")
    fig.update_layout(
        **PLOTLY_DARK, title=title,
        xaxis=dict(gridcolor='#2d3250'), yaxis=dict(gridcolor='#2d3250'), bargap=0.05,
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
    """Return a cached instance of the analyzer."""
    return MpesaAnalyzer()


def fmt_ksh(amount: Optional[float]) -> str:
    """Format a number as Kenyan Shillings."""
    if amount is None:
        return "KES 0"
    return f"KES {float(amount):,.0f}"


def route_ask_ai_question(analyzer: "MpesaAnalyzer", question: str) -> dict:
    """Mirrors the routing logic in whatsapp/whatsapp_api.py's /ask endpoint,
    so the dashboard chat understands the same commands as the WhatsApp bot.
    Returns a dict with keys: content (str), sql (str|None), results (list|None),
    fig (plotly Figure|None)."""

    if not question or len(question) < 2 or len(question) > 500:
        return {'content': "⚠️ Question too short or too long (2-500 chars).", 'sql': None, 'results': None, 'fig': None}

    if not is_safe_question(question):
        logger.warning("🚨 BLOCKED: Destructive operation")
        return {'content': "⚠️ Invalid question.", 'sql': None, 'results': None, 'fig': None}

    question_lower = question.lower().strip()

    # NOTE: check order below is intentionally identical to whatsapp_api.py's
    # /ask endpoint: budget → invest → forecast → chart → help → daily/today
    # → summary → fallback. Do not reorder — question_lower substring checks
    # overlap (e.g. 'daily trend' contains both a chart keyword and 'daily'),
    # so whichever branch runs first wins, and the bot and dashboard must
    # agree on which one that is.

    # ── BUDGET PLAN ───────────────────────────────────────────────────────
    if any(k in question_lower for k in BUDGET_KEYWORDS):
        logger.info("📋 BUDGET PLAN")
        context = analyzer.build_context_string(days=30)
        analysis = analyzer.groq.budget_plan(context=context)
        return {'content': clean_response(analysis), 'sql': None, 'results': None, 'fig': None}

    # ── INVESTMENT ADVICE ─────────────────────────────────────────────────
    if any(k in question_lower for k in INVEST_KEYWORDS):
        logger.info("📈 INVESTMENT ADVICE")
        context = analyzer.build_context_string(days=30)
        analysis = analyzer.groq.investment_advice(context=context)
        return {'content': clean_response(analysis), 'sql': None, 'results': None, 'fig': None}

    # ── FORECAST ──────────────────────────────────────────────────────────
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

    # ── CHARTS ────────────────────────────────────────────────────────────
    chart_type = None
    for key in CHART_KEYWORDS.keys():
        if key in question_lower:
            chart_type = key
            break

    if chart_type:
        logger.info(f"📊 {chart_type.upper()}")
        chart_days = parse_days_from_question(question_lower, default=30)
        category_filter = extract_category_filter(question_lower)
        data = analyzer.get_dashboard_data(days=chart_days)
        fig = None
        content = ""

        if chart_type in ['bar', 'chart', 'graph', 'bar chart']:
            if category_filter:
                raw_data = analyzer.db.get_transactions(days=chart_days, limit=1000)
                df_raw = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                df_cat = (df_raw[df_raw['merchant_category'] == category_filter]
                          if not df_raw.empty and 'merchant_category' in df_raw.columns
                          else pd.DataFrame())
                fig = chat_bar_chart(df_cat, 'recipient', 'amount',
                                      title=f"💰 {category_filter.title()} Spending by Recipient (last {chart_days}d)")
                if not df_cat.empty and 'amount' in df_cat.columns:
                    total_cat = df_cat['amount'].sum()
                    by_recipient = df_cat.groupby('recipient')['amount'].sum().sort_values(ascending=False)
                    top_line = f"\n🔝 Top recipient: {by_recipient.index[0]} (KES {by_recipient.iloc[0]:,.0f})" if not by_recipient.empty else ""
                    content = f"💰 **{category_filter.title()} Spending (last {chart_days} days)**\n\nTotal: KES {total_cat:,.0f}{top_line}\n✅ Chart generated showing recipients within this category"
            else:
                df = pd.DataFrame(data.get('spending_by_category', []))
                fig = chat_bar_chart(df, 'merchant_category', 'total_amount',
                                      title=f"💰 Spending by Category (last {chart_days}d)")
                if not df.empty and 'total_amount' in df.columns:
                    top_cat = df.nlargest(1, 'total_amount')
                    if not top_cat.empty:
                        top_name = top_cat.iloc[0]['merchant_category']
                        top_amount = top_cat.iloc[0]['total_amount']
                        content = f"📊 **Spending Breakdown by Category (last {chart_days} days)**\n\n🔝 Top: {top_name} (KES {top_amount:,.0f})\n✅ Chart generated showing all categories ranked by spending"

        elif chart_type in ['pie', 'pie chart']:
            if category_filter:
                raw_data = analyzer.db.get_transactions(days=chart_days, limit=1000)
                df_raw = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                df_cat = (df_raw[df_raw['merchant_category'] == category_filter]
                          if not df_raw.empty and 'merchant_category' in df_raw.columns
                          else pd.DataFrame())
                fig = chat_pie_chart(df_cat, 'recipient', 'amount',
                                      title=f"🥧 {category_filter.title()} Spending Distribution (last {chart_days}d)")
                if not df_cat.empty and 'amount' in df_cat.columns:
                    total_cat = df_cat['amount'].sum()
                    content = f"🥧 **{category_filter.title()} Spending Distribution (last {chart_days} days)**\n\n💰 Total: KES {total_cat:,.0f}\n✅ Percentages shown per recipient within this category"
            else:
                df = pd.DataFrame(data.get('spending_by_category', []))
                fig = chat_pie_chart(df, 'merchant_category', 'total_amount',
                                      title=f"🥧 Spending Distribution (last {chart_days}d)")
                if not df.empty and 'total_amount' in df.columns:
                    total = df['total_amount'].sum()
                    content = f"🥧 **Spending Distribution Overview (last {chart_days} days)**\n\n💰 Total: KES {total:,.0f}\n✅ Percentages shown for each category"

        elif chart_type in ['trend', 'line', 'line chart', 'over days', 'over time', 'spending over', 'daily trend', 'spending trend']:
            df = pd.DataFrame(data.get('daily_trend', []))
            fig = chat_line_chart(df, 'date', 'total_spent', title=f"📈 Daily Spending Trend (last {chart_days}d)")
            if not df.empty and 'total_spent' in df.columns:
                max_day = df.loc[df['total_spent'].idxmax()]
                content = f"📈 **{chart_days}-Day Spending Trend**\n\n📍 Peak Day: {max_day['date']} (KES {max_day['total_spent']:,.0f})\n✅ Shows daily spending pattern with average line"

        elif chart_type in ['heatmap', 'heat map', 'weekly']:
            heat_days = parse_days_from_question(question_lower, default=90)
            raw_data = analyzer.db.get_transactions(days=heat_days, limit=2000)
            df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
            if not df.empty:
                fig = chat_heatmap_chart(df, 'timestamp', 'merchant_category', 'amount',
                                          title=f"🔥 Weekly Spending Heatmap (last {heat_days}d)")
                content = f"🔥 **Weekly Spending Heatmap (last {heat_days} days)**\n\n📅 Shows spending patterns across days and categories\n✅ Darker colors = higher spending"

        elif chart_type in ['merchants', 'top merchants', 'top recipients', 'recipients', 'top spending']:
            merch_days = parse_days_from_question(question_lower, default=30)
            raw_data = analyzer.db.get_transactions(days=merch_days, limit=1000)
            df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
            if not df.empty and 'amount' in df.columns and 'recipient' in df.columns:
                fig = chat_top_merchants_chart(df, 'recipient', 'amount', title=f"🏆 Top 10 Merchants (last {merch_days}d)")
                top_recipient = df.nlargest(1, 'amount')
                if not top_recipient.empty:
                    content = f"🏆 **Top 10 Recipients (last {merch_days} days)**\n\n💸 #1: {top_recipient.iloc[0]['recipient']} (KES {top_recipient.iloc[0]['amount']:,.0f})\n✅ Your most frequent spending targets"

        elif chart_type in ['histogram', 'distribution', 'amount distribution']:
            hist_days = parse_days_from_question(question_lower, default=30)
            raw_data = analyzer.db.get_transactions(days=hist_days, limit=1000)
            df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
            if not df.empty and 'amount' in df.columns:
                fig = chat_histogram_chart(df, 'amount', title=f"📊 Transaction Distribution (last {hist_days}d)")
                amounts = df[df['amount'] > 0]['amount']
                if not amounts.empty:
                    content = f"📊 **Transaction Amount Analysis (last {hist_days} days)**\n\n📈 Average: KES {amounts.mean():,.0f}\n📌 Most Common: KES {amounts.median():,.0f}\n✅ Distribution shows spending pattern"

        if not fig:
            content = "❌ No data available yet. Add some transactions first."

        return {'content': content, 'sql': None, 'results': None, 'fig': fig}

    # ── HELP ──────────────────────────────────────────────────────────────
    if question_lower == 'help':
        return {'content': HELP_TEXT, 'sql': None, 'results': None, 'fig': None}

    # ── DAILY / TODAY ─────────────────────────────────────────────────────
    if 'daily' in question_lower or 'today' in question_lower:
        return {'content': generate_daily_summary_text(analyzer), 'sql': None, 'results': None, 'fig': None}

    # ── SUMMARY ───────────────────────────────────────────────────────────
    if 'summary' in question_lower:
        days = parse_days_from_question(question_lower, default=30)
        return {'content': generate_summary_text(analyzer, days), 'sql': None, 'results': None, 'fig': None}

    # ── FALLBACK: free-form question → analyzer.ask_question (SQL+AI) ─────
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
    """Main Streamlit application."""
    analyzer: MpesaAnalyzer = get_analyzer()

    # Sidebar
    with st.sidebar:
        st.markdown("## 💸 PesaPilot")
        st.markdown("*Your M-Pesa Financial Advisor*")
        st.divider()

        page: str = st.radio("Navigate", ["📊 Dashboard", "🔮 Forecast", "💬 Ask AI", "📋 Transactions", "⚠️ Anomalies"])
        st.divider()

        days: int = st.slider("Analysis period (days)", 7, 180, 30)

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Load dashboard data
    with st.spinner("Loading your financial data..."):
        data: dict[str, Any] = analyzer.get_dashboard_data(days=days)

    summary: dict[str, Any] = data.get('summary', {})
    category_data: list[dict[str, Any]] = data.get('spending_by_category', [])
    daily_trend: list[dict[str, Any]] = data.get('daily_trend', [])
    anomalies: list[dict[str, Any]] = data.get('anomalies', [])
    top_merchants: list[dict[str, Any]] = data.get('top_merchants', [])
    recent_txs: list[dict[str, Any]] = data.get('recent_transactions', [])
    insights: str = data.get('insights', '')

    # ── DASHBOARD ──────────────────────────────────────────────────────────
    if page == "📊 Dashboard":
        st.title("📊 Financial Dashboard")
        st.caption(f"Last {days} days · M-Pesa transaction analysis")

        # ── Row 1: metrics ──
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

        # ── Row 2: trend + category pie ──
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

        # ── Row 3: top merchants + AI insights ──
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

        # ── Row 4: heatmap + histogram ──
        st.markdown("---")
        col_h1, col_h2 = st.columns(2)

        with col_h1:
            st.subheader("🔥 Spending Heatmap")
            st.caption("KES per category per day of week (last 90 days)")
            raw_for_heat: list[dict[str, Any]] = analyzer.db.get_transactions(days=90, limit=2000)
            if raw_for_heat:
                df_heat: pd.DataFrame = pd.DataFrame(raw_for_heat)
                df_heat = df_heat[df_heat['type'] != 'credit'].copy()
                if not df_heat.empty and 'timestamp' in df_heat.columns:
                    df_heat['timestamp'] = pd.to_datetime(df_heat['timestamp'], errors='coerce')
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
            st.caption("Frequency of transaction sizes (last 30 days)")
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

    # ── FORECAST ────────────────────────────────────────────────────────────
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

    # ── ASK AI ─────────────────────────────────────────────────────────────
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
                    st.plotly_chart(msg['fig'], use_container_width=True, key=f"chat_fig_{i}")
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

    # ── TRANSACTIONS ────────────────────────────────────────────────────────
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

    # ── ANOMALIES ───────────────────────────────────────────────────────────
    elif page == "⚠️ Anomalies":
        st.title("⚠️ Unusual Transactions")
        st.caption("Transactions significantly above your normal spending pattern")

        if anomalies:
            for a in anomalies[:20]:
                score: float = float(a.get('zscore', 0))
                st.markdown(f"""
                <div class="anomaly-badge">
                    ⚠️ <strong>{a.get('recipient', 'Unknown')}</strong> — KES {float(a.get('amount', 0)):,.2f}
                    &nbsp;·&nbsp; {str(a.get('timestamp', ''))[:16]}
                    &nbsp;·&nbsp; z-score: {score:.1f}x above normal
                </div>
                """, unsafe_allow_html=True)
                st.markdown("")
        else:
            st.success("✅ No unusual transactions detected in your history.")


if __name__ == "__main__":
    main()