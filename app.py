import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from src.analyzer import MpesaAnalyzer
import json
from datetime import datetime
import logging

# Page config
st.set_page_config(
    page_title="💰 PesaPilot - AI Financial Assistant",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .insight-box {
        background-color: #f0f2f6;
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
        border-left: 4px solid #1f77b4;
    }
    .metric-card {
        background-color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #666;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .user-message {
        background-color: #e3f2fd;
        text-align: right;
    }
    .assistant-message {
        background-color: #f5f5f5;
        text-align: left;
    }
    .stButton > button {
        width: 100%;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'analyzer' not in st.session_state:
    st.session_state.analyzer = MpesaAnalyzer()

if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'dashboard_data' not in st.session_state:
    with st.spinner("Loading data..."):
        st.session_state.dashboard_data = st.session_state.analyzer.get_dashboard_data()

# Header
st.markdown('<div class="main-header">💰 PesaPilot</div>', unsafe_allow_html=True)
st.caption("AI-Powered Financial Assistant for M-PESA Data")

# Sidebar
with st.sidebar:
    st.title("📊 Navigation")
    
    page = st.radio(
        "Select Page",
        ["📈 Dashboard", "💬 Chat", "📋 Transactions", "🔍 Anomalies", "📊 Insights"]
    )
    
    st.divider()
    
    st.subheader("📅 Date Range")
    days = st.slider("Days to show", 7, 90, 30)
    
    st.divider()
    
    st.subheader("ℹ️ About")
    st.info(
        "PesaPilot analyzes your M-PESA transactions using AI. "
        "Ask questions about your spending, get insights, and track your finances."
    )
    
    if st.button("🔄 Refresh Data"):
        with st.spinner("Refreshing..."):
            st.session_state.dashboard_data = st.session_state.analyzer.get_dashboard_data()
            st.session_state.messages = []
        st.rerun()

# Main content
if page == "📈 Dashboard":
    st.header("📈 Financial Dashboard")
    
    data = st.session_state.dashboard_data
    
    if data.get('success'):
        # Metrics
        summary = data.get('summary', {})
        daily_df = pd.DataFrame(summary.get('daily', []))
        category_df = pd.DataFrame(summary.get('categories', []))
        
        # Calculate metrics
        total_spent = daily_df['total_spent'].sum() if not daily_df.empty else 0
        total_received = daily_df['total_received'].sum() if not daily_df.empty else 0
        total_tx = daily_df['total_transactions'].sum() if not daily_df.empty else 0
        avg_spend = daily_df['avg_spend'].mean() if not daily_df.empty else 0
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">Ksh {total_spent:,.2f}</div>
                    <div class="metric-label">💰 Total Spent</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">Ksh {total_received:,.2f}</div>
                    <div class="metric-label">📈 Total Received</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">Ksh {avg_spend:,.2f}</div>
                    <div class="metric-label">📊 Avg Daily Spend</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-value">{int(total_tx):,}</div>
                    <div class="metric-label">📝 Total Transactions</div>
                </div>
            """, unsafe_allow_html=True)
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            if not daily_df.empty:
                fig = px.line(
                    daily_df,
                    x='date',
                    y=['total_spent', 'total_received'],
                    title='Daily Spending & Receiving Trend',
                    labels={'value': 'Amount (Ksh)', 'variable': 'Type', 'date': 'Date'},
                    color_discrete_map={'total_spent': '#ff6b6b', 'total_received': '#51cf66'}
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No daily data available")
        
        with col2:
            if not category_df.empty:
                fig = px.pie(
                    category_df,
                    values='total_spent',
                    names='merchant_category',
                    title='Spending by Category',
                    hole=0.3,
                    color_discrete_sequence=px.colors.qualitative.Set3
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No category data available")
        
        # Recent transactions
        st.subheader("📋 Recent Transactions")
        transactions = pd.DataFrame(data.get('transactions', []))
        if not transactions.empty:
            display_cols = ['timestamp', 'type', 'amount', 'recipient', 'merchant_category']
            st.dataframe(
                transactions[display_cols].head(10),
                use_container_width=True,
                column_config={
                    'timestamp': st.column_config.DatetimeColumn('Date'),
                    'amount': st.column_config.NumberColumn('Amount (Ksh)', format="%.2f"),
                    'type': st.column_config.TextColumn('Type'),
                    'recipient': st.column_config.TextColumn('Recipient'),
                    'merchant_category': st.column_config.TextColumn('Category')
                }
            )
        else:
            st.info("No recent transactions")

elif page == "💬 Chat":
    st.header("💬 Ask About Your Finances")
    st.caption("Ask questions in plain English about your M-PESA transactions")
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                st.markdown(message["content"])
            else:
                st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about your spending..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get response
        with st.chat_message("assistant"):
            with st.spinner("🤔 Analyzing..."):
                response = st.session_state.analyzer.ask_question(prompt)
                
                if response.get('success'):
                    st.markdown(response['analysis'])
                    
                    # Show SQL in expander
                    with st.expander("🔍 View SQL Query"):
                        st.code(response['sql'], language='sql')
                    
                    # Show results if any
                    if response.get('result_count', 0) > 0:
                        with st.expander(f"📊 View Results ({response['result_count']} rows)"):
                            results_df = pd.DataFrame(response['results'])
                            st.dataframe(results_df, use_container_width=True)
                            
                            # Download button
                            csv = results_df.to_csv(index=False)
                            st.download_button(
                                "📥 Download CSV",
                                csv,
                                "query_results.csv",
                                "text/csv"
                            )
                else:
                    st.error(f"❌ Error: {response.get('error', 'Unknown error')}")
                
                # Add assistant message to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.get('analysis', "I couldn't process your question.")
                })

elif page == "📋 Transactions":
    st.header("📋 Transaction History")
    
    # Get transactions
    data = st.session_state.dashboard_data
    transactions = pd.DataFrame(data.get('transactions', []))
    
    if not transactions.empty:
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            type_filter = st.selectbox("Filter by Type", ["All"] + sorted(transactions['type'].unique().tolist()))
        with col2:
            cat_filter = st.selectbox("Filter by Category", ["All"] + sorted(transactions['merchant_category'].unique().tolist()))
        with col3:
            min_amount = st.number_input("Min Amount (Ksh)", min_value=0, value=0, step=50)
        
        # Apply filters
        filtered = transactions.copy()
        if type_filter != "All":
            filtered = filtered[filtered['type'] == type_filter]
        if cat_filter != "All":
            filtered = filtered[filtered['merchant_category'] == cat_filter]
        if min_amount > 0:
            filtered = filtered[filtered['amount'] >= min_amount]
        
        # Display count
        st.caption(f"Showing {len(filtered)} transactions")
        
        # Display table
        st.dataframe(
            filtered[['timestamp', 'type', 'amount', 'recipient', 'merchant_category', 'balance']],
            use_container_width=True,
            column_config={
                'timestamp': st.column_config.DatetimeColumn('Date'),
                'amount': st.column_config.NumberColumn('Amount (Ksh)', format="%.2f"),
                'balance': st.column_config.NumberColumn('Balance (Ksh)', format="%.2f"),
                'type': st.column_config.TextColumn('Type'),
                'recipient': st.column_config.TextColumn('Recipient'),
                'merchant_category': st.column_config.TextColumn('Category')
            }
        )
        
        # Download
        csv = filtered.to_csv(index=False)
        st.download_button(
            "📥 Download All Transactions CSV",
            csv,
            "transactions.csv",
            "text/csv"
        )
    else:
        st.info("No transactions found. Load data first using the CLI.")

elif page == "🔍 Anomalies":
    st.header("🔍 Anomaly Detection")
    
    col1, col2 = st.columns(2)
    with col1:
        threshold = st.slider("Anomaly Threshold (Z-score)", 1.0, 5.0, 3.0, 0.5)
    with col2:
        days_back = st.slider("Days to analyze", 7, 90, 30)
    
    if st.button("🔍 Scan for Anomalies", use_container_width=True):
        with st.spinner("Analyzing transactions..."):
            anomalies = st.session_state.analyzer.db.detect_anomalies(
                threshold=threshold,
                days_back=days_back
            )
            
            if not anomalies.empty:
                st.warning(f"⚠️ Found {len(anomalies)} anomalous transactions")
                
                # Display anomalies
                st.dataframe(
                    anomalies[['transaction_id', 'amount', 'recipient', 'timestamp', 'zscore']],
                    use_container_width=True,
                    column_config={
                        'transaction_id': st.column_config.TextColumn('ID'),
                        'amount': st.column_config.NumberColumn('Amount (Ksh)', format="%.2f"),
                        'zscore': st.column_config.NumberColumn('Z-Score', format="%.2f"),
                        'timestamp': st.column_config.DatetimeColumn('Date'),
                        'recipient': st.column_config.TextColumn('Recipient')
                    }
                )
                
                # Visualization
                fig = px.scatter(
                    anomalies,
                    x='timestamp',
                    y='amount',
                    color='zscore',
                    title='Anomalous Transactions',
                    labels={'zscore': 'Anomaly Score', 'amount': 'Amount (Ksh)'},
                    color_continuous_scale='Viridis'
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Insights
                with st.expander("💡 AI Analysis of Anomalies"):
                    with st.spinner("Generating insights..."):
                        analysis = st.session_state.analyzer.groq.analyze_results(
                            "Analyze these anomalous transactions and explain what might be causing them",
                            "SELECT * FROM anomalies",
                            anomalies.to_dict('records'),
                            len(anomalies)
                        )
                        st.markdown(analysis)
            else:
                st.success("✅ No anomalies detected!")

elif page == "📊 Insights":
    st.header("📊 AI-Generated Financial Insights")
    
    data = st.session_state.dashboard_data
    
    if data.get('success'):
        # Show insights
        st.markdown('<div class="insight-box">', unsafe_allow_html=True)
        st.markdown(data.get('insights', 'No insights available'))
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.divider()
        
        # Additional analysis
        st.subheader("📈 Quick Stats")
        
        col1, col2 = st.columns(2)
        
        with col1:
            summary = data.get('summary', {})
            categories = pd.DataFrame(summary.get('categories', []))
            
            if not categories.empty:
                st.write("**Top Spending Categories**")
                top_categories = categories.nlargest(5, 'total_spent')
                st.dataframe(
                    top_categories[['merchant_category', 'total_spent', 'transaction_count']],
                    use_container_width=True,
                    column_config={
                        'merchant_category': 'Category',
                        'total_spent': st.column_config.NumberColumn('Total Spent (Ksh)', format="%.2f"),
                        'transaction_count': 'Count'
                    }
                )
        
        with col2:
            trends = pd.DataFrame(data.get('trends', []))
            if not trends.empty:
                st.write("**Spending Trends**")
                fig = px.line(
                    trends,
                    x='period',
                    y='spending',
                    title='Spending Over Time',
                    labels={'spending': 'Amount (Ksh)', 'period': 'Period'}
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.error(f"❌ Error loading insights: {data.get('error', 'Unknown error')}")

# Footer
st.divider()
st.caption(f"💰 PesaPilot v1.0 | Powered by Groq AI | Data updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")