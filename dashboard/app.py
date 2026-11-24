import sys
import os
import hmac
import threading
import time
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
import datetime as dt
import html
import re
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import logging
from typing import Optional, Any
from dashboard import plotly_charts as pc
from src import assistant, chart_generator, insights as insight_engine
from src.analyzer import MpesaAnalyzer
from src.chart_types import RENDERERS
from src.chat_common import clean_response
from src.parse_sms import MpesaParser
from src.security import install_log_redaction

logging.basicConfig(level=logging.INFO)
install_log_redaction()
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
    .info-card {
        background: #1e2130; border-radius: 12px; padding: 16px; border: 1px solid #2d3250;
        color: #c8cdd8; line-height: 1.7;
    }
    h1, h2, h3 { color: #e8eaf0 !important; }
    .stPlotlyChart { border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

PERIOD_OPTIONS: dict[str, Optional[int]] = {
    "Last 7 days": 7,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 180 days": 180,
    "Last 365 days": 365,
    "All time": None,
}
CUSTOM_PERIOD_LABEL = "Custom (choose days)"
CUSTOM_DAYS_MIN = 1
CUSTOM_DAYS_MAX = 1095
CUSTOM_DAYS_DEFAULT = 10
MAX_CHAT_HISTORY = 30
PAGES = ["Dashboard", "Smart Insights", "Chart Studio", "Forecast", "Budgets", "Ask AI", "Transactions", "Anomalies"]


def refuse_to_run_on_a_server() -> None:
    in_container = os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv')
    over_ssh = bool(os.getenv('SSH_CONNECTION')) and os.getenv('PESAPILOT_ALLOW_DASHBOARD_OVER_SSH') != '1'
    if not (in_container or over_ssh):
        return
    st.title("PesaPilot")
    st.error(
        "The dashboard is for your own computer only. It must never run on a server or inside Docker. "
        "Run it on your laptop and point POSTGRES_HOST at your database through an SSH tunnel "
        "(ssh -L 5432:127.0.0.1:5432 user@your-server)."
    )
    st.stop()


def period_label(days: Optional[int]) -> str:
    if days is None:
        return "All time"
    return f"Last {days} day" if days == 1 else f"Last {days} days"


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
    headed = re.sub(r'^#{1,6}\s+(.+)$', r'<strong>\1</strong>', bold, flags=re.MULTILINE)
    return headed.replace(chr(10), '<br>')


def info_card(text: str) -> None:
    st.markdown(f'<div class="info-card">{html.escape(text or "").replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)


def metric_cards(items: list[tuple[str, Any]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{html.escape(str(value))}</div>
                <div class="metric-label">{html.escape(label)}</div>
            </div>
            """, unsafe_allow_html=True)


def show_plot(fig: Optional[go.Figure], empty_message: str, key: str) -> None:
    if fig is None:
        st.info(empty_message)
    else:
        st.plotly_chart(fig, width='stretch', key=key)


_LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1', '[::1]'}
_HOST_RE = re.compile(r'^\[?([^\]]+?)\]?(?::\d+)?$')


def _request_host() -> str:
    try:
        raw = (st.context.headers.get('Host') or '').strip().lower()
    except Exception:
        return ''
    if raw.count(':') > 1 and not raw.startswith('['):
        return raw
    match = _HOST_RE.match(raw)
    return match.group(1) if match else raw


def _guard_unprotected_access() -> None:
    host = _request_host()
    if host in _LOOPBACK_HOSTS or os.getenv('DASHBOARD_ALLOW_REMOTE_NO_PASSWORD', '').lower() == 'true':
        return
    st.title("PesaPilot")
    st.error(
        "This dashboard has no DASHBOARD_PASSWORD, so it only answers on localhost. "
        "Set DASHBOARD_PASSWORD in .env."
    )
    st.stop()


_LOGIN_MAX_FAILS = 5
_LOGIN_BASE_LOCK_SECONDS = 30
_LOGIN_MAX_LOCK_SECONDS = 900


@st.cache_resource
def _login_guard() -> dict[str, Any]:
    return {'fails': 0, 'locked_until': 0.0, 'lock': threading.Lock()}


def require_dashboard_password() -> None:
    expected = os.getenv('DASHBOARD_PASSWORD', '')
    if not expected:
        _guard_unprotected_access()
        st.sidebar.warning("No DASHBOARD_PASSWORD is set: anyone who can reach this page can read your finances.")
        return

    try:
        session_minutes = max(5, int(os.getenv('DASHBOARD_SESSION_MINUTES', '480')))
    except ValueError:
        session_minutes = 480
    authed_at = st.session_state.get('_dashboard_authed_at')
    if st.session_state.get('_dashboard_authed') and authed_at and time.time() - authed_at < session_minutes * 60:
        return
    st.session_state.pop('_dashboard_authed', None)

    guard = _login_guard()
    st.title("PesaPilot")
    remaining = guard['locked_until'] - time.time()
    if remaining > 0:
        st.error(f"Too many wrong attempts. Try again in {int(remaining) + 1} seconds.")
        st.stop()

    supplied = st.text_input("Password", type="password")
    if supplied:
        with guard['lock']:
            matched = hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))
            if matched:
                guard['fails'] = 0
                guard['locked_until'] = 0.0
            else:
                guard['fails'] += 1
                if guard['fails'] >= _LOGIN_MAX_FAILS:
                    steps = guard['fails'] - _LOGIN_MAX_FAILS
                    guard['locked_until'] = time.time() + min(
                        _LOGIN_BASE_LOCK_SECONDS * (2 ** steps), _LOGIN_MAX_LOCK_SECONDS,
                    )
        if matched:
            st.session_state['_dashboard_authed'] = True
            st.session_state['_dashboard_authed_at'] = time.time()
            st.rerun()
        time.sleep(1)
        st.error("Incorrect password.")
    st.stop()


def run_chart_request(analyzer: MpesaAnalyzer, description: str, dark: bool = True) -> dict[str, Any]:
    result = analyzer.generate_dynamic_chart(description, dark=dark)
    png = chart_generator.figure_to_png_bytes(result['fig'])
    text = chart_generator.compose_chart_text(result) if png else (result['error'] or 'No data for that chart.')
    return {'text': text, 'png': png}


def render_chart_result(result: dict[str, Any], download_name: str, key: str) -> None:
    st.markdown(f'<div class="chat-msg-bot">{chat_html(result["text"])}</div>', unsafe_allow_html=True)
    if result.get('png'):
        st.image(result['png'], width='stretch')
        st.download_button("Download PNG", data=result['png'], file_name=download_name, mime="image/png", key=key)


def page_dashboard(analyzer: MpesaAnalyzer, days: Optional[int]) -> None:
    with st.spinner("Loading your financial data..."):
        data = analyzer.get_dashboard_data(days=days)
        frame = analyzer.get_frame(days=days)

    summary: dict[str, Any] = data.get('summary', {})
    category_data: list[dict[str, Any]] = data.get('spending_by_category', [])
    daily_trend: list[dict[str, Any]] = data.get('daily_trend', [])
    top_merchants: list[dict[str, Any]] = data.get('top_merchants', [])
    insights: str = data.get('insights', '')

    st.title("Financial Dashboard")
    st.caption(f"{period_label(days)} · M-Pesa transaction analysis")

    metric_cards([
        ("Total Transactions", summary.get('total_transactions', 0)),
        ("Total Spent", fmt_ksh(summary.get('total_spent', 0))),
        ("Total Received", fmt_ksh(summary.get('total_received', 0))),
        ("Avg Transaction", fmt_ksh(summary.get('avg_spend', 0))),
    ])
    st.markdown("")

    col_left, col_right = st.columns([1.2, 0.8])
    with col_left:
        st.subheader("Daily Spending Trend")
        if daily_trend:
            df_trend = pd.DataFrame(daily_trend)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_trend['date'], y=df_trend['total_spent'], name='Spent', fill='tozeroy',
                                     line=dict(color='#ff4b6e', width=2), fillcolor='rgba(255,75,110,0.1)'))
            fig.add_trace(go.Scatter(x=df_trend['date'], y=df_trend['total_received'], name='Received', fill='tozeroy',
                                     line=dict(color='#00d4aa', width=2), fillcolor='rgba(0,212,170,0.1)'))
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#8892a4',
                              margin=dict(l=0, r=0, t=10, b=0), xaxis=dict(gridcolor='#2d3250'),
                              yaxis=dict(gridcolor='#2d3250'), legend=dict(bgcolor='rgba(0,0,0,0)'))
            st.plotly_chart(fig, width='stretch', key='dash_trend')
        else:
            st.info("No trend data available.")

    with col_right:
        st.subheader("Spending by Category")
        if category_data:
            df_cat = pd.DataFrame(category_data)
            fig = px.pie(df_cat.head(8), values='total_amount', names='merchant_category', hole=0.55,
                         color_discrete_sequence=px.colors.qualitative.Bold)
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', font_color='#8892a4', legend=dict(bgcolor='rgba(0,0,0,0)'),
                              margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, width='stretch', key='dash_cat')
        else:
            st.info("No category data available.")

    col_l2, col_r2 = st.columns(2)
    with col_l2:
        st.subheader("Top Merchants")
        if top_merchants:
            df_merch = pd.DataFrame(top_merchants)
            fig = px.bar(df_merch, x='total_amount', y='recipient', orientation='h', color='total_amount',
                         color_continuous_scale='teal', labels={'total_amount': 'Amount (KES)', 'recipient': ''})
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#8892a4',
                              margin=dict(l=0, r=0, t=10, b=0), coloraxis_showscale=False,
                              xaxis=dict(gridcolor='#2d3250'), yaxis=dict(autorange='reversed', gridcolor='#2d3250'))
            st.plotly_chart(fig, width='stretch', key='dash_merch')
        else:
            st.info("No merchant data available.")
    with col_r2:
        st.subheader("AI Insights")
        if insights:
            info_card(insights)
        else:
            st.info("Load transactions to generate insights.")

    st.markdown("---")
    st.subheader("More views")
    tabs = st.tabs(["Calendar", "When you spend", "Treemap", "Sunburst", "Money flow", "Cash flow", "Rolling average",
                    "Payment sizes", "Categories together"])
    with tabs[0]:
        st.caption("Each square is a day; brighter means more spending. Hover for the exact amount.")
        show_plot(pc.calendar_heatmap(frame), "Need at least a week of spending to draw a calendar.", 'v_cal')
    with tabs[1]:
        st.caption("Spending by weekday and hour of day.")
        show_plot(pc.hour_weekday_heatmap(frame), "Not enough transactions yet.", 'v_hour')
        show_plot(pc.weekday_bars(frame), "Need at least a week of spending.", 'v_wd')
    with tabs[2]:
        st.caption("Click a category to zoom into its recipients.")
        show_plot(pc.treemap(frame), "No spending found for this period.", 'v_tree')
    with tabs[3]:
        show_plot(pc.sunburst(frame), "No spending found for this period.", 'v_sun')
    with tabs[4]:
        st.caption("Who sent you money, and where it went.")
        show_plot(pc.sankey(frame), "Need both income and spending in this period.", 'v_sankey')
    with tabs[5]:
        show_plot(pc.cashflow(frame), "No transactions found.", 'v_cash')
        show_plot(pc.cumulative(frame), "No transactions found.", 'v_cum')
    with tabs[6]:
        show_plot(pc.rolling(frame), "Need at least 14 days of spending.", 'v_roll')
    with tabs[7]:
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Spread of payment sizes per category (log scale).")
            show_plot(pc.category_distribution(frame, 'violin'), "Need repeat payments in at least one category.", 'v_violin')
        with c2:
            st.caption("What share of your payments fall under a given amount.")
            show_plot(pc.ecdf(frame), "Need at least 10 payments.", 'v_ecdf')
    with tabs[8]:
        st.caption("Categories that tend to be paid on the same days (correlation).")
        show_plot(pc.correlation(frame), "Need 3+ categories and 14+ days of data.", 'v_corr')


def page_insights(analyzer: MpesaAnalyzer) -> None:
    st.title("Smart Insights")
    st.caption("Computed from your whole M-Pesa history: no guesses, every number is traceable to your transactions.")
    frame = analyzer.get_frame()
    if frame.empty:
        st.info("No transactions yet. Load your M-Pesa XML backup to get started.")
        return

    health = analyzer.get_health()
    run = analyzer.get_runway()
    c1, c2 = st.columns([0.8, 1.2])
    with c1:
        st.subheader("Financial health")
        show_plot(pc.health_gauge(health), health.get('message', 'Not enough history to score yet.'), 'i_gauge')
        if health.get('sufficient_data'):
            st.markdown(f"**{health['headline']}**")
    with c2:
        st.subheader("What drives the score")
        show_plot(pc.health_components(health), "Need at least 14 days of history.", 'i_comp')

    if health.get('sufficient_data'):
        with st.expander("How each component is measured"):
            for comp in sorted(health['components'], key=lambda c: c['score']):
                st.markdown(f"**{comp['name']}** ({comp['weight']}% of score): {comp['score']:.0f}/100: {comp['detail']}")
        if health['tips']:
            st.subheader("Do this next")
            for i, tip in enumerate(health['tips'], 1):
                st.markdown(f"{i}. {tip}")

    st.markdown("---")
    cover = run['days_of_cover']
    metric_cards([
        ("Balance", fmt_ksh(run['balance']) if run['balance'] is not None else 'n/a'),
        ("Spending / day (30d)", fmt_ksh(run['avg_daily_spend'])),
        ("Income / day (30d)", fmt_ksh(run['avg_daily_income'])),
        ("Days of cover", f"{cover:.1f}" if cover is not None else 'n/a'),
    ])
    st.markdown("")

    cmp30 = insight_engine.period_comparison(frame, 30)
    if cmp30.get('sufficient_data'):
        change = cmp30['spend_change_pct']
        extra = f" This is higher than {cmp30['spend_percentile']}% of your past 30-day periods." if cmp30['spend_percentile'] is not None else ''
        direction = '' if change is None else f"{change:+.0f}% versus the 30 days before. "
        st.markdown(f"**Last 30 days:** you spent {fmt_ksh(cmp30['spend'])} and received {fmt_ksh(cmp30['income'])}. {direction}{extra}")

    alerts = analyzer.get_smart_alerts()
    if alerts:
        st.subheader("Heads-up")
        for alert in alerts:
            (st.warning if alert['level'] == 'warning' else st.info)(f"**{alert['title']}**: {alert['detail']}")

    st.markdown("---")
    st.subheader("Recurring payments and habits")
    recurring = analyzer.get_recurring()
    if recurring:
        rc1, rc2 = st.columns([1.1, 0.9])
        with rc1:
            show_plot(pc.recurring_bars(recurring), "Nothing recurring detected.", 'i_rec')
        with rc2:
            table = pd.DataFrame(recurring)[['recipient', 'kind', 'cadence', 'payments', 'median_amount', 'monthly_estimate', 'next_expected']]
            table.columns = ['Recipient', 'Type', 'Rhythm', 'Payments', 'Typical KES', 'KES / month', 'Next expected']
            st.dataframe(table, width='stretch', height=380, hide_index=True)
    else:
        st.info("No recurring payments detected yet.")

    st.markdown("---")
    st.subheader("Your spending patterns")
    pat = insight_engine.spending_patterns(frame)
    if pat.get('sufficient_data'):
        st.markdown(
            f"- You spend most around **{pat['peak_hour_by_amount']}:00** and on **{pat['peak_weekday']}s**; "
            f"your quietest day is **{pat['quietest_weekday']}**.\n"
            f"- Weekends are **{pat['weekend_share_pct']:.0f}%** of your spending (an even spread would be {pat['weekend_expected_pct']:.0f}%).\n"
            f"- **{pat['micro_count_pct']:.0f}%** of your payments are under KES {insight_engine.MICRO_SPEND_KES}, adding up to about "
            f"**{fmt_ksh(pat['micro_monthly'])}** a month.\n"
            f"- M-Pesa fees cost you **{fmt_ksh(pat['fees_total'])}** in total ({pat['fees_pct_of_spend']:.2f}% of spending)."
            + (f"\n- Within 2 days of a big payment in, you spend **{pat['payday_spend_ratio']:.1f}x** your normal pace." if pat.get('payday_spend_ratio') else '')
        )

    st.markdown("---")
    st.subheader("AI money coach")
    if st.button("Explain my score and what to do", key="coach_btn"):
        if not health.get('sufficient_data'):
            st.info(health.get('message', 'Not enough history.'))
        elif not analyzer.groq.available:
            st.info("Set GROQ_API_KEY to enable the AI coach. The computed tips above are always available.")
        else:
            facts = (f"Score {health['score']}/100 grade {health['grade']}. Components: "
                     + '; '.join(f"{c['name']} {c['score']:.0f}/100 ({c['value']})" for c in health['components'])
                     + f". Tips: {' | '.join(health['tips'])}\n" + insight_engine.facts_text(frame))
            with st.spinner("Thinking..."):
                narrative = analyzer.groq.health_coach(facts)
            info_card(clean_response(narrative) if narrative else "The AI coach is unavailable right now.")


def page_chart_studio(analyzer: MpesaAnalyzer) -> None:
    st.title("Chart Studio")
    st.caption(f"{len(RENDERERS)} chart types. Describe what you want, or build it yourself.")
    dark = st.toggle("Dark charts", value=True, key="studio_dark")
    tab_nl, tab_build = st.tabs(["Describe it", "Build it"])

    with tab_nl:
        example = st.selectbox("Need ideas?", ["(type your own below)"] + chart_generator.CHART_EXAMPLES, key="studio_example")
        default_text = "" if example.startswith("(") else example
        description = st.text_input("What should I draw?", value=default_text, max_chars=300,
                                    placeholder="e.g. violin plot of food spending last month", key=f"studio_text_{default_text}")
        if st.button("Draw it", key="studio_nl_go", type="primary") and description.strip():
            with st.spinner("Drawing..."):
                st.session_state['studio_result'] = run_chart_request(analyzer, description.strip(), dark=dark)
        if st.session_state.get('studio_result'):
            render_chart_result(st.session_state['studio_result'], "pesapilot_chart.png", "studio_dl_nl")

    with tab_build:
        c1, c2, c3 = st.columns(3)
        labels = {k: v.label for k, v in RENDERERS.items()}
        with c1:
            chart_type = st.selectbox("Chart type", ["auto"] + list(RENDERERS), format_func=lambda k: "Let PesaPilot choose" if k == 'auto' else labels[k], key="b_type")
            metric = st.selectbox("Measure", ["amount", "count", "transaction_cost", "average"],
                                  format_func={'amount': 'Amount (KES)', 'count': 'Number of transactions',
                                               'transaction_cost': 'M-Pesa fees', 'average': 'Average amount'}.get, key="b_metric")
        with c2:
            group_by = st.selectbox("Group by", [None, "merchant_category", "recipient", "type", "date", "week", "month", "weekday", "hour"],
                                    format_func=lambda g: "(chart default)" if g is None else g.replace('merchant_', '').title(), key="b_group")
            tx_type = st.selectbox("Transactions", ["spending", "income", "all"], key="b_tx")
        with c3:
            category = st.selectbox("Only category", [None] + list(MpesaParser.CATEGORIES),
                                    format_func=lambda c: "(all)" if c is None else c.title(), key="b_cat")
            top_n = st.slider("Top N", 3, 30, 10, key="b_top")
        period_mode = st.radio("Period", ["Last N days", "Date range", "All time"], horizontal=True, key="b_period")
        date_from = date_to = None
        label = None
        if period_mode == "Last N days":
            n_days = st.slider("Days", 7, 730, 90, key="b_days")
            today = dt.date.today()
            date_from, date_to, label = (today - dt.timedelta(days=n_days - 1)).isoformat(), today.isoformat(), f"last {n_days} days"
        elif period_mode == "Date range":
            picked = st.date_input("From / to", value=(dt.date.today() - dt.timedelta(days=89), dt.date.today()), key="b_range")
            if isinstance(picked, (tuple, list)) and len(picked) == 2:
                date_from, date_to = picked[0].isoformat(), picked[1].isoformat()
                label = f"{date_from} to {date_to}"
        else:
            label = "all time"
        if st.button("Build chart", key="studio_build_go", type="primary"):
            spec = chart_generator.make_spec(chart_type=chart_type, metric=metric, group_by=group_by, transaction_type=tx_type,
                                             category_filter=category, top_n=top_n, date_from=date_from, date_to=date_to, period_label=label)
            with st.spinner("Drawing..."):
                result = chart_generator.generate_from_spec(analyzer, spec, dark=dark, commentary=True)
                png = chart_generator.figure_to_png_bytes(result['fig'])
                text = chart_generator.compose_chart_text(result) if png else (result['error'] or 'No data for that chart.')
                st.session_state['studio_built'] = {'text': text, 'png': png}
        if st.session_state.get('studio_built'):
            render_chart_result(st.session_state['studio_built'], "pesapilot_chart.png", "studio_dl_build")


def page_forecast(analyzer: MpesaAnalyzer) -> None:
    st.title("Spending Forecast")
    st.caption("Backtested on your own history: an ensemble of Prophet and a robust seasonal model")

    horizon_label = st.radio("Forecast horizon", ["7 days", "14 days", "30 days"], horizontal=True)
    horizon_days = int(horizon_label.split()[0])

    with st.spinner("Training forecast model..."):
        forecast_data: dict[str, Any] = analyzer.get_forecast(horizon_days=horizon_days)

    if not forecast_data.get('sufficient_data'):
        st.info(forecast_data.get('message', 'Not enough transaction history yet for a forecast.'))
        return

    trend_emoji = {'Increasing': '📈', 'Decreasing': '📉', 'Stable': '➡️'}.get(forecast_data.get('trend', 'Stable'), '')
    risk_emoji = {'Low': '🟢', 'Moderate': '🟡', 'High': '🔴'}.get(forecast_data.get('risk_level', 'Low'), '')
    metric_cards([
        ("Predicted Spend", fmt_ksh(forecast_data.get('total_predicted', 0))),
        ("Likely Range", f"{fmt_ksh(forecast_data.get('total_lower', 0))} to {fmt_ksh(forecast_data.get('total_upper', 0))}"),
        ("Trend vs recent pace", f"{trend_emoji} {forecast_data.get('trend', 'Stable')}"),
        ("Risk Level", f"{risk_emoji} {forecast_data.get('risk_level', 'Low')}"),
        ("Confidence", forecast_data.get('confidence', 'n/a')),
    ])
    st.markdown("")
    st.subheader("Historical Spending + Forecast")
    show_plot(pc.forecast_figure(forecast_data), "Nothing to chart yet.", 'f_fig')

    insight: str = forecast_data.get('insight', '')
    if insight:
        st.subheader("AI Insight")
        info_card(insight)

    backtest = forecast_data.get('backtest') or {}
    weights = forecast_data.get('model_weights') or {}
    err = backtest.get('error_pct_7d')
    st.caption(
        f"Model: {forecast_data.get('model')} · {forecast_data.get('history_days', 0)} days of history"
        + (f" · typical error on 7-day totals in backtests: {err:.0f}% over {backtest.get('folds', 0)} weeks" if err is not None else '')
        + (f" · blend: {weights.get('prophet', 0) * 100:.0f}% Prophet / {weights.get('stat', 0) * 100:.0f}% seasonal" if weights else '')
    )


def page_budgets(analyzer: MpesaAnalyzer) -> None:
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
            category_input: str = st.selectbox("Category", list(MpesaParser.CATEGORIES), format_func=lambda c: c.title())
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
                result = analyzer.set_budget(category_input, limit_input, period=period_input, alert_threshold_pct=threshold_input)
                if result.get('success'):
                    st.session_state.budget_flash = f"Budget saved: {category_input.title()} — KES {limit_input:,.0f} per {period_input}."
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


def page_ask_ai(analyzer: MpesaAnalyzer) -> None:
    st.title("Ask PesaPilot")
    st.caption("Ask anything about your M-Pesa transactions: same commands as the WhatsApp bot")

    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []

    suggestions: list[str] = [
        "What did I spend most on this month?",
        "Financial health score",
        "Treemap of my spending by category",
        "Recurring payments",
        "Forecast my spending",
        "Any unusual spending?",
        "Calendar heatmap of my spending",
        "My budgets",
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
            if msg.get('png'):
                st.image(msg['png'], width='stretch')
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
            reply = assistant.answer(analyzer, question, dark=True, dashboard=True)
        png = chart_generator.figure_to_png_bytes(reply.fig) if reply.fig is not None else None
        st.session_state.chat_history.append({
            'role': 'bot', 'content': reply.text, 'sql': reply.sql, 'results': reply.results, 'png': png,
        })
        st.session_state.chat_history = st.session_state.chat_history[-MAX_CHAT_HISTORY:]
        st.rerun()


def page_transactions(analyzer: MpesaAnalyzer, days: Optional[int]) -> None:
    st.title("Recent Transactions")
    with st.spinner("Loading transactions..."):
        recent_txs = analyzer.db.get_transactions(days=days, limit=5000)
    if recent_txs:
        df: pd.DataFrame = pd.DataFrame(recent_txs)
        cols_show = [c for c in ['timestamp', 'type', 'amount', 'recipient', 'merchant_category', 'balance'] if c in df.columns]
        df_show = df[cols_show].copy()
        if 'amount' in df_show.columns:
            df_show['amount'] = df_show['amount'].apply(fmt_money)
        if 'balance' in df_show.columns:
            df_show['balance'] = df_show['balance'].apply(fmt_money)

        fc1, fc2 = st.columns(2)
        with fc1:
            tx_types = ['All'] + sorted(df['type'].dropna().unique().tolist())
            selected_type = st.selectbox("Transaction type", tx_types)
        with fc2:
            cats = ['All'] + sorted(df['merchant_category'].dropna().unique().tolist())
            selected_cat = st.selectbox("Category", cats)

        mask = pd.Series(True, index=df.index)
        if selected_type != 'All':
            mask &= df['type'] == selected_type
        if selected_cat != 'All':
            mask &= df['merchant_category'] == selected_cat

        st.dataframe(df_show[mask], width='stretch', height=500)
        st.caption(f"Showing {int(mask.sum())} of the latest {len(df)} transactions in this period")
    else:
        st.info("No transactions found. Load your M-Pesa XML backup to get started.")


def page_anomalies(analyzer: MpesaAnalyzer) -> None:
    st.title("Unusual Transactions")
    st.caption(
        "Transactions that stand out from YOUR OWN normal pattern for that recipient or category, plus possible "
        "duplicate payments and large first-time payees. Some flagged items are perfectly legitimate one-offs."
    )

    anom_days: int = st.slider("Lookback period (days)", 14, 730, 90, key="anomaly_days_slider")
    force_refresh: bool = st.button("Re-run detection now", width='content')

    with st.spinner("Scanning your spending pattern..."):
        smart_result: dict[str, Any] = analyzer.get_smart_anomalies(days=anom_days, force_refresh=force_refresh)

    flagged_txs: list[dict[str, Any]] = smart_result.get('anomalies', [])
    insight_text: str = smart_result.get('insight', '')
    if insight_text:
        info_card(insight_text)
        st.markdown("")

    if flagged_txs:
        st.subheader(f"{len(flagged_txs)} Flagged Transaction(s)")
        show_plot(pc.anomaly_scatter(analyzer.get_frame(days=anom_days), flagged_txs), "Nothing to chart.", 'a_scatter')
        for a in flagged_txs[:20]:
            score = float(a.get('score') or 0)
            reasons = a.get('reasons') or ['Unusual against your normal pattern']
            st.markdown(f"""
            <div class="anomaly-badge">
                <strong>{html.escape(str(a.get('recipient', 'Unknown')))}</strong> — KES {float(a.get('amount', 0)):,.2f}
                &nbsp;·&nbsp; {html.escape(str(a.get('merchant_category', 'other')).title())}
                &nbsp;·&nbsp; {html.escape(str(a.get('timestamp', ''))[:16])}
                &nbsp;·&nbsp; unusualness: {score:.1f}/10<br>
                {html.escape('; '.join(str(r) for r in reasons))}
            </div>
            """, unsafe_allow_html=True)
            st.markdown("")
    else:
        st.success(f"No unusual transactions detected in the last {anom_days} days.")


def main() -> None:
    refuse_to_run_on_a_server()
    require_dashboard_password()
    analyzer: MpesaAnalyzer = get_analyzer()

    with st.sidebar:
        st.markdown("## 💸 PesaPilot")
        st.markdown("*Your M-Pesa Financial Advisor*")
        st.divider()

        page: str = st.radio("Navigate", PAGES)
        st.divider()

        period_label_choice: str = st.selectbox("Analysis period", list(PERIOD_OPTIONS) + [CUSTOM_PERIOD_LABEL], index=1)
        days: Optional[int]
        if period_label_choice == CUSTOM_PERIOD_LABEL:
            days = st.slider("Number of days", min_value=CUSTOM_DAYS_MIN, max_value=CUSTOM_DAYS_MAX,
                             value=CUSTOM_DAYS_DEFAULT, step=1)
        else:
            days = PERIOD_OPTIONS[period_label_choice]

        if st.button("Refresh Data", width='stretch'):
            analyzer.clear_cache()
            st.rerun()

    if page == "Dashboard":
        page_dashboard(analyzer, days)
    elif page == "Smart Insights":
        page_insights(analyzer)
    elif page == "Chart Studio":
        page_chart_studio(analyzer)
    elif page == "Forecast":
        page_forecast(analyzer)
    elif page == "Budgets":
        page_budgets(analyzer)
    elif page == "Ask AI":
        page_ask_ai(analyzer)
    elif page == "Transactions":
        page_transactions(analyzer, days)
    elif page == "Anomalies":
        page_anomalies(analyzer)


if __name__ == "__main__":
    main()
