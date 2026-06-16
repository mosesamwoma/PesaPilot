import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from src.analyzer import MpesaAnalyzer
import json
from datetime import datetime

# Page config
st.set_page_config(
    page_title="PesaPilot - Financial Assistant",
    page_icon="💰",
    layout="wide"
)

# Initialize analyzer
@st.cache_resource
def get_analyzer():
    return MpesaAnalyzer()

analyzer = get_analyzer()

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .insight-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .metric-card {
        background-color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    </style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="main-header">💰 PesaPilot</div>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.title("📊 Navigation")
    
    page = st.radio(
        "Select Page",
        ["📈 Dashboard", "💬 Chat", "📋 Transactions", "🔍 Anomalies"]
    )
    
    st.divider()
    
    st.subheader("📅 Date Range")
    days = st.slider("Days to show", 7, 90, 30)
    
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

# Main content
if page == "📈 Dashboard":
    st.header("Financial Dashboard")
    
    # Get data
    data = analyzer.get_dashboard_data()
    
    if data.get('success'):
        # Metrics
        col1, col2, col3, col4 = st.columns(4)
        
        summary = data.get('summary', {})
        daily_df = pd.DataFrame(summary.get('daily', []))
        category_df = pd.DataFrame(summary.get('categories', []))
        
        with col1:
            total_spent = daily_df['total_spent'].sum() if not daily_df.empty else 0
            st.metric("💰 Total Spent", f"Ksh {total_spent:,.2f}")
        
        with col2:
            total_received = daily_df['total_received'].sum() if not daily_df.empty else 0
            st.metric("📈 Total Received", f"Ksh {total_received:,.2f}")
        
        with col3:
            avg_spend = daily_df['avg_spend'].mean() if not daily_df.empty else 0
            st.metric("📊 Avg Daily Spend", f"Ksh {avg_spend:,.2f}")
        
        with col4:
            total_tx = daily_df['total_transactions'].sum() if not daily_df.empty else 0
            st.metric("📝 Total Transactions", f"{int(total_tx):,}")
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            if not daily_df.empty:
                fig = px.line(
                    daily_df,
                    x='date',
                    y=['total_spent', 'total_received'],
                    title='Daily Spending & Receiving Trend',
                    labels={'value': 'Amount (Ksh)', 'variable': 'Type'}
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            if not category_df.empty:
                fig = px.pie(
                    category_df,
                    values='total_spent',
                    names='merchant_category',
                    title='Spending by Category'
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Insights
        st.subheader("💡 AI Insights")
        st.markdown(f'<div class="insight-box">{data["insights"]}</div>', unsafe_allow_html=True)
        
        # Anomalies
        anomalies = pd.DataFrame(data.get('anomalies', []))
        if not anomalies.empty:
            st.subheader("⚠️ Anomalies Detected")
            st.dataframe(anomalies[['transaction_id', 'amount', 'recipient', 'timestamp', 'zscore']])

elif page == "💬 Chat":
    st.header("💬 Ask About Your Transactions")
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about your spending..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get response
        with st.chat_message("assistant"):
            with st.spinner("Analyzing..."):
                response = analyzer.ask_question(prompt)
                if response.get('success'):
                    st.markdown(response['analysis'])
                    
                    # Show SQL in expander
                    with st.expander("🔍 View SQL"):
                        st.code(response['sql'], language='sql')
                    
                    # Show results if any
                    if response.get('results'):
                        with st.expander("📊 View Results"):
                            st.dataframe(pd.DataFrame(response['results']))
                else:
                    st.error(f"Error: {response.get('error', 'Unknown error')}")
                
                # Add assistant message to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.get('analysis', "I couldn't process your question.")
                })

elif page == "📋 Transactions":
    st.header("📋 Transaction History")
    
    # Get transactions
    transactions = analyzer.db.get_transactions(days=days)
    
    if not transactions.empty:
        # Filters
        col1, col2 = st.columns(2)
        with col1:
            type_filter = st.selectbox("Filter by Type", ["All"] + transactions['type'].unique().tolist())
        with col2:
            cat_filter = st.selectbox("Filter by Category", ["All"] + transactions['merchant_category'].unique().tolist())
        
        # Apply filters
        filtered = transactions.copy()
        if type_filter != "All":
            filtered = filtered[filtered['type'] == type_filter]
        if cat_filter != "All":
            filtered = filtered[filtered['merchant_category'] == cat_filter]
        
        # Display
        st.dataframe(
            filtered[['timestamp', 'type', 'amount', 'recipient', 'merchant_category', 'balance']],
            use_container_width=True
        )
        
        # Download
        csv = filtered.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv,
            "transactions.csv",
            "text/csv"
        )

elif page == "🔍 Anomalies":
    st.header("🔍 Anomaly Detection")
    
    # Parameters
    col1, col2 = st.columns(2)
    with col1:
        threshold = st.slider("Anomaly Threshold (Z-score)", 1.0, 5.0, 3.0, 0.5)
    with col2:
        days_back = st.slider("Days to analyze", 7, 90, 30)
    
    # Detect anomalies
    if st.button("🔍 Scan for Anomalies"):
        with st.spinner("Analyzing transactions..."):
            anomalies = analyzer.db.detect_anomalies(threshold=threshold)
            
            if not anomalies.empty:
                st.warning(f"⚠️ Found {len(anomalies)} anomalous transactions")
                
                # Display anomalies
                st.dataframe(
                    anomalies[['transaction_id', 'amount', 'recipient', 'timestamp', 'zscore']]
                )
                
                # Visualization
                fig = px.scatter(
                    anomalies,
                    x='timestamp',
                    y='amount',
                    color='zscore',
                    title='Anomalous Transactions',
                    labels={'zscore': 'Anomaly Score'}
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Insights
                with st.expander("💡 AI Analysis of Anomalies"):
                    analysis = analyzer.groq.analyze_results(
                        "Analyze these anomalous transactions",
                        "SELECT * FROM anomalies",
                        anomalies.to_dict('records')
                    )
                    st.markdown(analysis)
            else:
                st.success("✅ No anomalies detected!")

# Footer
st.divider()
st.caption(f"PesaPilot v1.0 | Powered by Groq AI | Data updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")