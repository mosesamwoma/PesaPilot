# app.py
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import logging
from typing import Optional, Any
from src.analyzer import MpesaAnalyzer

logging.basicConfig(level=logging.INFO)

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
    margin=dict(l=0, r=0, t=10, b=0),
)


@st.cache_resource
def get_analyzer() -> MpesaAnalyzer:
    """Return a cached instance of the analyzer."""
    return MpesaAnalyzer()


def fmt_ksh(amount: Optional[float]) -> str:
    """Format a number as Kenyan Shillings."""
    if amount is None:
        return "KES 0"
    return f"KES {float(amount):,.0f}"


def main() -> None:
    """Main Streamlit application."""
    analyzer: MpesaAnalyzer = get_analyzer()

    # Sidebar
    with st.sidebar:
        st.markdown("## 💸 PesaPilot")
        st.markdown("*Your M-Pesa Financial Advisor*")
        st.divider()

        page: str = st.radio("Navigate", ["📊 Dashboard", "💬 Ask AI", "📋 Transactions", "⚠️ Anomalies"])
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
                    **PLOTLY_DARK,
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
                        **PLOTLY_DARK,
                        xaxis=dict(gridcolor='#2d3250'),
                        yaxis=dict(gridcolor='#2d3250'),
                        bargap=0.05,
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No debit transactions to chart.")
            else:
                st.info("No transaction data available.")

    # ── ASK AI ─────────────────────────────────────────────────────────────
    elif page == "💬 Ask AI":
        st.title("💬 Ask PesaPilot")
        st.caption("Ask anything about your M-Pesa transactions in plain English")

        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []

        suggestions: list[str] = [
            "What did I spend most on this month?",
            "How much did I send to Safaricom?",
            "What are my top 5 expenses?",
            "Compare my spending this week vs last week",
            "Which day do I spend the most?",
        ]
        st.markdown("**Quick questions:**")
        cols = st.columns(len(suggestions))
        for i, (col, q) in enumerate(zip(cols, suggestions)):
            if col.button(q, key=f"sugg_{i}", use_container_width=True):
                st.session_state.pending_question = q

        st.divider()

        for msg in st.session_state.chat_history:
            if msg['role'] == 'user':
                st.markdown(f'<div class="chat-msg-user">🧑 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-msg-bot">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
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
                result: dict[str, Any] = analyzer.ask_question(question)
            bot_msg: dict[str, Any] = {
                'role': 'bot',
                'content': result['analysis'],
                'sql': result.get('sql', ''),
                'results': result.get('results', []),
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