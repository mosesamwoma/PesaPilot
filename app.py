# app.py (root level - was src/streamlit_app.py)
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import logging
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


@st.cache_resource
def get_analyzer():
    return MpesaAnalyzer()


def fmt_ksh(amount) -> str:
    if amount is None:
        return "KES 0"
    return f"KES {float(amount):,.0f}"


def main():
    analyzer = get_analyzer()

    # Sidebar
    with st.sidebar:
        st.markdown("## 💸 PesaPilot")
        st.markdown("*Your M-Pesa Financial Advisor*")
        st.divider()

        page = st.radio("Navigate", ["📊 Dashboard", "💬 Ask AI", "📋 Transactions", "⚠️ Anomalies", "📤 Load Data"])
        st.divider()

        days = st.slider("Analysis period (days)", 7, 180, 30)

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Load dashboard data
    with st.spinner("Loading your financial data..."):
        data = analyzer.get_dashboard_data(days=days)

    summary = data.get('summary', {})
    category_data = data.get('spending_by_category', [])
    daily_trend = data.get('daily_trend', [])
    anomalies = data.get('anomalies', [])
    top_merchants = data.get('top_merchants', [])
    recent_txs = data.get('recent_transactions', [])
    insights = data.get('insights', '')

    # ── DASHBOARD ──────────────────────────────────────────────────────────
    if page == "📊 Dashboard":
        st.title("📊 Financial Dashboard")
        st.caption(f"Last {days} days · M-Pesa transaction analysis")

        c1, c2, c3, c4 = st.columns(4)
        metrics = [
            (c1, "Total Transactions", summary.get('total_transactions', 0)),
            (c2, "Total Spent", fmt_ksh(summary.get('total_spent', 0))),
            (c3, "Total Received", fmt_ksh(summary.get('total_received', 0))),
            (c4, "Avg Transaction", fmt_ksh(summary.get('avg_spend', 0))),
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
                df_trend = pd.DataFrame(daily_trend)
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
                    legend=dict(bgcolor='rgba(0,0,0,0)'),
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis=dict(gridcolor='#2d3250'),
                    yaxis=dict(gridcolor='#2d3250'),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No trend data available.")

        with col_right:
            st.subheader("Spending by Category")
            if category_data:
                df_cat = pd.DataFrame(category_data)
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
                df_merch = pd.DataFrame(top_merchants)
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
                    coloraxis_showscale=False,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis=dict(autorange='reversed'),
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

    # ── ASK AI ─────────────────────────────────────────────────────────────
    elif page == "💬 Ask AI":
        st.title("💬 Ask PesaPilot")
        st.caption("Ask anything about your M-Pesa transactions in plain English")

        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []

        suggestions = [
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
        question = st.chat_input("Ask about your spending...") or pending

        if question:
            st.session_state.chat_history.append({'role': 'user', 'content': question})
            with st.spinner("Thinking..."):
                result = analyzer.ask_question(question)
            bot_msg = {
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
            df = pd.DataFrame(recent_txs)
            cols_show = [c for c in ['timestamp', 'type', 'amount', 'recipient', 'merchant_category', 'balance'] if c in df.columns]
            df_show = df[cols_show].copy()
            if 'amount' in df_show.columns:
                df_show['amount'] = df_show['amount'].apply(lambda x: f"KES {x:,.2f}" if x else '')
            if 'balance' in df_show.columns:
                df_show['balance'] = df_show['balance'].apply(lambda x: f"KES {x:,.2f}" if x else '')

            fc1, fc2 = st.columns(2)
            with fc1:
                tx_types = ['All'] + sorted(df['type'].dropna().unique().tolist())
                selected_type = st.selectbox("Transaction type", tx_types)
            with fc2:
                cats = ['All'] + sorted(df['merchant_category'].dropna().unique().tolist())
                selected_cat = st.selectbox("Category", cats)

            mask = pd.Series([True] * len(df))
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
                score = float(a.get('zscore', 0))
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

    # ── LOAD DATA ───────────────────────────────────────────────────────────
    elif page == "📤 Load Data":
        st.title("📤 Load M-Pesa Data")
        st.markdown("Upload your SMS backup XML file exported from **SMS Backup & Restore** app.")

        uploaded = st.file_uploader("Upload SMS backup XML", type=['xml'])
        if uploaded:
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            try:
                with st.spinner("Parsing and uploading transactions..."):
                    count = analyzer.load_transactions(tmp_path, csv_output='data/processed/mpesa_transactions.csv')
                if count > 0:
                    st.success(f"✅ Successfully loaded {count} transactions!")
                    st.balloons()
                    st.cache_resource.clear()
                else:
                    st.warning("No M-Pesa transactions found in the file.")
            except Exception as e:
                st.error(f"Error loading data: {e}")
            finally:
                os.unlink(tmp_path)

        st.divider()
        st.subheader("Or load from local path")
        local_path = st.text_input("XML file path", "data/raw/sms-20260616115048.xml")
        if st.button("Load from path", use_container_width=True):
            try:
                with st.spinner("Loading..."):
                    count = analyzer.load_transactions(local_path)
                st.success(f"✅ Loaded {count} transactions!")
                st.cache_resource.clear()
            except Exception as e:
                st.error(f"Error: {e}")


if __name__ == "__main__":
    main()