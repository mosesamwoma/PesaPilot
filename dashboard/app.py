import sys
import os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
import html
import re
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import logging
from typing import Optional, Any
from src.analyzer import LLM_UNAVAILABLE_MESSAGE, MpesaAnalyzer
from src.chat_common import (
    ANOMALY_KEYWORDS, BUDGET_KEYWORDS, BUDGET_STATUS_KEYWORDS, CHART_TRIGGER_WORDS, FORECAST_KEYWORDS,
    INVEST_KEYWORDS, budget_status_text, clean_response, daily_summary_text, forecast_header, help_text,
    is_safe_question, is_set_budget_command, is_valid_question_length, matches_any_keyword,
    parse_days_from_question, parse_forecast_horizon, parse_set_budget, range_summary_text,
)
from src.parse_sms import MpesaParser

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


PERIOD_OPTIONS: dict[str, Optional[int]] = {
    "Last 7 days": 7,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 180 days": 180,
    "Last 365 days": 365,
    "All time": None,
}
PERIOD_LABEL_BY_DAYS = {v: k for k, v in PERIOD_OPTIONS.items()}


_SUMMARY_COMMAND_RE = re.compile(r'\bsummary\b')
_DAILY_COMMAND_RE = re.compile(
    r"^\s*(?:(?:my|the|give me|show me)\s+)*(?:daily|today(?:'s)?)(?:\s+(?:summary|overview|report|spending))?\s*\??\s*$"
)


def generate_daily_summary_text(analyzer: "MpesaAnalyzer") -> str:
    try:
        return daily_summary_text(analyzer.db.get_today_summary(), manual_sms_hint=False)
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return "Could not generate summary. Please try again."


def generate_summary_text(analyzer: "MpesaAnalyzer", days: Optional[int]) -> str:
    try:
        return range_summary_text(analyzer.db.get_range_summary(days=days), days)
    except Exception as e:
        logger.error(f"Summary error: {e}")
        return "Could not generate summary. Please try again."


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


def fmt_money(amount: Any) -> str:
    return f"KES {float(amount):,.2f}" if pd.notna(amount) and amount else ''


def chat_html(text: str) -> str:
    escaped = html.escape(text or '')
    bold = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    return bold.replace(chr(10), '<br>')


def route_ask_ai_question(analyzer: "MpesaAnalyzer", question: str) -> dict:

    def reply(content: str, fig=None, sql=None, results=None) -> dict:
        return {'content': content, 'sql': sql, 'results': results, 'fig': fig}

    if not is_valid_question_length(question):
        return reply("Question too short or too long (2-500 chars).")

    if not is_safe_question(question):
        logger.warning("BLOCKED: destructive operation")
        return reply("Invalid question.")

    question_lower = question.lower().strip()

    if is_set_budget_command(question_lower):
        parsed, problem = parse_set_budget(question)
        if parsed is None:
            return reply(clean_response(f"{problem}"))
        result = analyzer.set_budget(parsed['category'], parsed['amount'], period=parsed['period'])
        if result.get('success'):
            content = (
                f"Budget set: {parsed['category'].title()} — KES {parsed['amount']:,.0f} per {parsed['period'][:-2]}.\n"
                f"Check the Budgets page anytime to see progress."
            )
        else:
            content = f"Couldn't set that budget: {result.get('error', 'unknown error')}"
        return reply(clean_response(content))

    if matches_any_keyword(question_lower, BUDGET_STATUS_KEYWORDS):
        return reply(clean_response(budget_status_text(analyzer.get_budgets_overview(), dashboard=True)))

    if matches_any_keyword(question_lower, BUDGET_KEYWORDS):
        context = analyzer.build_context_string(days=30)
        return reply(clean_response(analyzer.groq.budget_plan(context=context) or LLM_UNAVAILABLE_MESSAGE))

    if matches_any_keyword(question_lower, INVEST_KEYWORDS):
        context = analyzer.build_context_string(days=30)
        return reply(clean_response(analyzer.groq.investment_advice(context=context) or LLM_UNAVAILABLE_MESSAGE))

    if matches_any_keyword(question_lower, FORECAST_KEYWORDS):
        horizon = parse_forecast_horizon(question_lower, default=7)
        forecast_data = analyzer.get_forecast(horizon_days=horizon)

        if not forecast_data.get('sufficient_data'):
            msg = forecast_data.get('message', 'Not enough transaction history yet for a forecast.')
            return reply(f"{clean_response(msg)}")

        fig = chat_forecast_chart(forecast_data, title=f"{horizon}-Day Spending Forecast")
        ai_summary = forecast_data.get('insight', '')
        header = forecast_header(forecast_data, horizon)
        return reply(clean_response(header + (f"\n{ai_summary}" if ai_summary else "")), fig=fig)

    if matches_any_keyword(question_lower, ANOMALY_KEYWORDS):
        anomaly_days = parse_days_from_question(question_lower, default=90)
        result = analyzer.get_smart_anomalies(days=anomaly_days, force_refresh=False)
        flagged = result.get('anomalies', [])
        window = "all time" if anomaly_days is None else f"last {anomaly_days} days"

        fig = None
        if flagged:
            df = pd.DataFrame(flagged)
            fig = chat_bar_chart(
                df.head(15), 'recipient', 'amount',
                title=f"Unusual Transactions ({window})"
            )
            header = f"**{len(flagged)} Unusual Transaction(s) Found ({window})**\n\n"
        else:
            header = f"**No Unusual Transactions ({window})**\n\n"

        return reply(clean_response(header + result.get('insight', '')), fig=fig)

    if question_lower == 'help':
        return reply(help_text(dashboard=True))

    if _DAILY_COMMAND_RE.match(question_lower):
        return reply(generate_daily_summary_text(analyzer))

    if matches_any_keyword(question_lower, CHART_TRIGGER_WORDS):
        chart_result = analyzer.generate_dynamic_chart(question, dark=True)
        fig = chart_result['fig']
        if fig is None:
            return reply(f"{chart_result['error'] or 'No data available yet for that chart.'}")
        spec = chart_result['spec']
        content = f"**{spec.get('title')}**\n\n{chart_result['summary']}\nChart generated"
        return reply(content, fig=fig)

    if _SUMMARY_COMMAND_RE.search(question_lower) and len(question_lower.split()) <= 6:
        days = parse_days_from_question(question_lower, default=30)
        return reply(generate_summary_text(analyzer, days))

    result = analyzer.ask_question(question)
    if result.get('error'):
        content = f"{clean_response(result.get('error', 'Error'))}"
    else:
        content = clean_response(result.get('analysis', 'No response'))

    return reply(content, sql=result.get('sql', ''), results=result.get('results', []))


def main() -> None:
    analyzer: MpesaAnalyzer = get_analyzer()

    with st.sidebar:
        st.markdown("## 💸 PesaPilot")
        st.markdown("*Your M-Pesa Financial Advisor*")
        st.divider()

        page: str = st.radio("Navigate", ["Dashboard", "Forecast", "Budgets", "Ask AI", "Transactions", "Anomalies"])
        st.divider()

        period_label_choice: str = st.selectbox("Analysis period", list(PERIOD_OPTIONS), index=1)
        days: Optional[int] = PERIOD_OPTIONS[period_label_choice]

        if st.button("Refresh Data", width='stretch'):
            analyzer.clear_cache()
            st.rerun()

    with st.spinner("Loading your financial data..."):
        data: dict[str, Any] = analyzer.get_dashboard_data(days=days)

    summary: dict[str, Any] = data.get('summary', {})
    category_data: list[dict[str, Any]] = data.get('spending_by_category', [])
    daily_trend: list[dict[str, Any]] = data.get('daily_trend', [])
    top_merchants: list[dict[str, Any]] = data.get('top_merchants', [])
    recent_txs: list[dict[str, Any]] = data.get('recent_transactions', [])
    insights: str = data.get('insights', '')

    if page == "Dashboard":
        st.title("Financial Dashboard")
        st.caption(f"{PERIOD_LABEL_BY_DAYS.get(days, 'Selected period')} · M-Pesa transaction analysis")

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
                st.plotly_chart(fig, width='stretch')
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
                st.plotly_chart(fig, width='stretch')
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
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("No merchant data available.")

        with col_r2:
            st.subheader("AI Insights")
            if insights:
                st.markdown(f"""
                <div style="background:#1e2130;border-radius:12px;padding:16px;border:1px solid #2d3250;color:#c8cdd8;line-height:1.7;">
                {html.escape(insights).replace(chr(10), '<br>')}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Load transactions to generate insights.")

        st.markdown("---")
        col_h1, col_h2 = st.columns(2)

        with col_h1:
            st.subheader("Spending Heatmap")
            st.caption(f"KES per category per day of week ({PERIOD_LABEL_BY_DAYS.get(days, 'selected period').lower()})")
            raw_for_heat: list[dict[str, Any]] = analyzer.db.get_transactions(days=days, limit=20000)
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
                        st.plotly_chart(fig, width='stretch')
                    else:
                        st.info("Not enough data for a heatmap yet.")
                else:
                    st.info("No spending data found.")
            else:
                st.info("Load transactions to see the spending heatmap.")

        with col_h2:
            st.subheader("Amount Distribution")
            st.caption(f"Frequency of transaction sizes ({PERIOD_LABEL_BY_DAYS.get(days, 'selected period').lower()})")
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
                    st.plotly_chart(fig, width='stretch')
                else:
                    st.info("No debit transactions to chart.")
            else:
                st.info("No transaction data available.")

    elif page == "Forecast":
        st.title("Spending Forecast")
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
                forecast_data.get('trend', 'Stable'), ''
            )
            risk_emoji = {'Low': '🟢', 'Moderate': '🟡', 'High': '🔴'}.get(
                forecast_data.get('risk_level', 'Low'), ''
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
                st.plotly_chart(fig, width='stretch')

            insight: str = forecast_data.get('insight', '')
            if insight:
                st.subheader("AI Insight")
                st.markdown(f"""
                <div style="background:#1e2130;border-radius:12px;padding:16px;border:1px solid #2d3250;color:#c8cdd8;line-height:1.7;">
                {html.escape(insight).replace(chr(10), '<br>')}
                </div>
                """, unsafe_allow_html=True)

            st.caption(f"Based on {forecast_data.get('history_days', 0)} days of spending history")

    elif page == "Budgets":
        st.title("Budget Goals")
        st.caption("Set spending limits per category and track progress live")

        flash = st.session_state.pop('budget_flash', None)
        if flash:
            st.success(flash)

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
                    "Category", list(MpesaParser.CATEGORIES),
                    format_func=lambda c: c.title(),
                )
            with fc2:
                limit_input: float = st.number_input("Monthly/weekly limit (KES)", min_value=0.0, step=500.0)
            with fc3:
                period_input: str = st.selectbox("Period", ["monthly", "weekly"])
            threshold_input: int = st.slider("Alert threshold (%)", min_value=50, max_value=100, value=80, step=5)

            submitted = st.form_submit_button("Save Budget", width='stretch')
            if submitted:
                if limit_input <= 0:
                    st.error("Enter a limit greater than 0.")
                else:
                    result = analyzer.set_budget(
                        category_input, limit_input, period=period_input,
                        alert_threshold_pct=threshold_input,
                    )
                    if result.get('success'):
                        st.session_state.budget_flash = (
                            f"Budget saved: {category_input.title()} — KES {limit_input:,.0f} per {period_input}."
                        )
                        st.rerun()
                    else:
                        st.error(f"Could not save budget: {result.get('error', 'unknown error')}")

        st.divider()
        st.subheader("Check for New Alerts")
        st.caption(
            "The WhatsApp bot checks this automatically every 2 hours and pings you when a budget "
            "crosses its threshold. Use this button to check right now instead of waiting."
        )
        if st.button("Check Now", width='stretch'):
            with st.spinner("Checking budgets..."):
                new_alerts: list[dict[str, Any]] = analyzer.check_budget_alerts()
            if new_alerts:
                for alert in new_alerts:
                    icon = "🚨" if alert.get('alert_level') == 'over' else "⚠️"
                    st.warning(f"{icon} {alert.get('message', '')}")
            else:
                st.success("Nothing new to report — no budgets have newly crossed their threshold.")

    elif page == "Ask AI":
        st.title("Ask PesaPilot")
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
                if st.button(q, key=f"sugg_{i}", width='stretch'):
                    st.session_state.pending_question = q

        st.divider()

        for i, msg in enumerate(st.session_state.chat_history):
            if msg['role'] == 'user':
                st.markdown(f'<div class="chat-msg-user">{html.escape(msg["content"])}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-msg-bot">{chat_html(msg["content"])}</div>', unsafe_allow_html=True)
                if msg.get('fig') is not None:
                    fig_obj = msg['fig']
                    if hasattr(fig_obj, 'savefig'):
                        st.pyplot(fig_obj, width='stretch')
                    else:
                        st.plotly_chart(fig_obj, width='stretch', key=f"chat_fig_{i}")
                if msg.get('sql'):
                    with st.expander("View SQL", expanded=False):
                        st.markdown(f'<div class="sql-box">{html.escape(msg["sql"])}</div>', unsafe_allow_html=True)
                if msg.get('results'):
                    with st.expander(f"View results ({len(msg['results'])} rows)", expanded=False):
                        st.dataframe(pd.DataFrame(msg['results']).head(20), width='stretch')

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

    elif page == "Transactions":
        st.title("Recent Transactions")
        if recent_txs:
            df: pd.DataFrame = pd.DataFrame(recent_txs)
            cols_show: list[str] = [c for c in ['timestamp', 'type', 'amount', 'recipient', 'merchant_category', 'balance'] if c in df.columns]
            df_show: pd.DataFrame = df[cols_show].copy()
            if 'amount' in df_show.columns:
                df_show['amount'] = df_show['amount'].apply(fmt_money)
            if 'balance' in df_show.columns:
                df_show['balance'] = df_show['balance'].apply(fmt_money)

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

            st.dataframe(df_show[mask], width='stretch', height=500)
            st.caption(f"Showing {mask.sum()} transactions")
        else:
            st.info("No transactions found. Load your M-Pesa XML backup to get started.")

    elif page == "Anomalies":
        st.title("Unusual Transactions")
        st.caption(
            "ML-flagged transactions that stand out from YOUR OWN normal pattern in that "
            "category — not compared to other people. Some flagged items are perfectly "
            "legitimate one-offs (a big one-time purchase, a rare emergency)."
        )

        anom_days: int = st.slider("Lookback period (days)", 14, 730, 90, key="anomaly_days_slider")
        force_refresh: bool = st.button("Re-run detection now", width='content')

        with st.spinner("Scanning your spending pattern..."):
            smart_result: dict[str, Any] = analyzer.get_smart_anomalies(days=anom_days, force_refresh=force_refresh)

        flagged_txs: list[dict[str, Any]] = smart_result.get('anomalies', [])
        insight_text: str = smart_result.get('insight', '')

        if insight_text:
            st.markdown(f"""
            <div style="background:#1e2130;border-radius:12px;padding:16px;border:1px solid #2d3250;color:#c8cdd8;line-height:1.7;">
            {html.escape(insight_text).replace(chr(10), '<br>')}
            </div>
            """, unsafe_allow_html=True)
            st.markdown("")

        if flagged_txs:
            st.subheader(f"{len(flagged_txs)} Flagged Transaction(s)")
            for a in flagged_txs[:20]:
                score = float(a.get('score') or 0)
                model_used = a.get('model', '')
                model_label = "learned pattern" if 'isolation' in model_used else "statistical check"
                st.markdown(f"""
                <div class="anomaly-badge">
                    <strong>{html.escape(str(a.get('recipient', 'Unknown')))}</strong> — KES {float(a.get('amount', 0)):,.2f}
                    &nbsp;·&nbsp; {str(a.get('merchant_category', 'other')).title()}
                    &nbsp;·&nbsp; {str(a.get('timestamp', ''))[:16]}
                    &nbsp;·&nbsp; unusualness score: {score:.1f} ({model_label})
                </div>
                """, unsafe_allow_html=True)
                st.markdown("")
        else:
            st.success(f"No unusual transactions detected in the last {anom_days} days.")


if __name__ == "__main__":
    main()