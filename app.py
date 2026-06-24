import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from src.database import SupabaseDB
from src.groq_client import GroqClient
from src.analyzer import MpesaAnalyzer
import seaborn as sns
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="PesaPilot Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "PesaPilot - AI Financial Assistant for Kenya"}
)

# Initialize services
@st.cache_resource
def init_services():
    try:
        db = SupabaseDB()
        groq = GroqClient()
        analyzer = MpesaAnalyzer()
        return db, groq, analyzer
    except Exception as e:
        logger.error(f"Initialization error: {e}")
        st.error("Failed to initialize services")
        return None, None, None

db, groq, analyzer = init_services()

if not db:
    st.stop()

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .metric-value {
        font-size: 28px;
        font-weight: bold;
        margin: 10px 0;
    }
    .metric-label {
        font-size: 14px;
        opacity: 0.9;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.title("💰 PesaPilot - Kenya's AI Financial Assistant")
st.markdown("Smart spending analysis, forecasting & Kenyan financial advice powered by AI")

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    days = st.slider("📅 Days to analyze:", 7, 90, 30)
    
    st.divider()
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()
    
    st.divider()
    
    st.subheader("ℹ️ About")
    st.info("""
    🤖 **PesaPilot v2.1**
    
    Your personal AI financial advisor for Kenya.
    
    📊 Track M-Pesa spending
    📈 Forecast future costs
    💡 Get smart advice
    
    Commands: Ask anything about your money!
    """)

st.divider()

# Main metrics
try:
    summary = db.get_summary()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "📊 Transactions",
            f"{summary.get('total_transactions', 0)}",
            delta="transactions"
        )
    
    with col2:
        st.metric(
            "💸 Total Spent",
            f"KES {summary.get('total_spent', 0):,.0f}",
            delta=None
        )
    
    with col3:
        st.metric(
            "💵 Total Received",
            f"KES {summary.get('total_received', 0):,.0f}",
            delta=None
        )
    
    with col4:
        balance = summary.get('balance', 0)
        st.metric(
            "⚖️ Current Balance",
            f"KES {balance:,.0f}",
            delta=f"{'Positive' if balance > 0 else 'Low'}"
        )

except Exception as e:
    st.error(f"Error loading summary: {str(e)}")
    logger.error(f"Summary error: {e}")

st.divider()

# Main tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Dashboard",
    "💬 Ask AI",
    "📋 Transactions",
    "⚠️ Anomalies",
    "🧮 Analysis",
    "ℹ️ Help"
])

# TAB 1: Dashboard
with tab1:
    st.header("📊 Dashboard")
    
    col1, col2 = st.columns(2)
    
    # Daily Trend
    with col1:
        st.subheader("📈 Daily Spending Trend")
        try:
            data = db.get_daily_trend(days=days)
            if data and len(data) > 0:
                df = pd.DataFrame(data)
                if not df.empty and 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date')
                    
                    fig, ax = plt.subplots(figsize=(10, 5), facecolor='white')
                    
                    if 'total_spent' in df.columns:
                        ax.plot(df['date'], df['total_spent'], marker='o', linewidth=2.5, 
                               color='#FF6B6B', markersize=5, label='Spent')
                    if 'total_received' in df.columns:
                        ax.plot(df['date'], df['total_received'], marker='s', linewidth=2.5, 
                               color='#4CAF50', markersize=5, label='Received')
                    
                    ax.set_title('Daily Trend (Last 7 Days)', fontweight='bold', fontsize=12)
                    ax.set_xlabel('Date', fontsize=10)
                    ax.set_ylabel('Amount (KES)', fontsize=10)
                    ax.legend(fontsize=9)
                    ax.grid(True, alpha=0.2)
                    plt.xticks(rotation=45)
                    plt.tight_layout()
                    st.pyplot(fig)
                else:
                    st.info("📊 No trend data available")
            else:
                st.info("📊 No trend data available")
        except Exception as e:
            st.error(f"Error: {str(e)}")
            logger.error(f"Trend chart error: {e}")
    
    # Category Spending
    with col2:
        st.subheader("💰 Spending by Category")
        try:
            data = db.get_spending_by_category(days=days)
            if data and len(data) > 0:
                df = pd.DataFrame(data)
                if not df.empty and 'merchant_category' in df.columns:
                    fig, ax = plt.subplots(figsize=(10, 5), facecolor='white')
                    category_data = df.groupby('merchant_category')['total_amount'].sum().sort_values(ascending=False).head(8)
                    
                    ax.barh(category_data.index, category_data.values, color='#2196F3', edgecolor='#333', linewidth=0.8)
                    ax.set_xlabel('Amount (KES)', fontsize=10)
                    ax.set_title('Top Categories', fontweight='bold', fontsize=12)
                    ax.grid(axis='x', alpha=0.2)
                    
                    for i, v in enumerate(category_data.values):
                        ax.text(v, i, f' KES {v:,.0f}', va='center', fontsize=9, fontweight='bold')
                    
                    plt.tight_layout()
                    st.pyplot(fig)
                else:
                    st.info("💰 No category data available")
            else:
                st.info("💰 No category data available")
        except Exception as e:
            st.error(f"Error: {str(e)}")
            logger.error(f"Category chart error: {e}")
    
    # Distribution & Top Merchants
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🥧 Distribution")
        try:
            data = db.get_spending_by_category(days=days)
            if data and len(data) > 0:
                df = pd.DataFrame(data)
                if not df.empty:
                    fig, ax = plt.subplots(figsize=(9, 6), facecolor='white')
                    category_data = df.groupby('merchant_category')['total_amount'].sum().sort_values(ascending=False).head(8)
                    
                    ax.pie(category_data.values, labels=category_data.index, autopct='%1.1f%%', 
                           startangle=90, colors=sns.color_palette("husl", len(category_data)))
                    ax.set_title('Spending Distribution', fontweight='bold', fontsize=12)
                    plt.tight_layout()
                    st.pyplot(fig)
                else:
                    st.info("🥧 No distribution data")
            else:
                st.info("🥧 No distribution data")
        except Exception as e:
            st.error(f"Error: {str(e)}")
            logger.error(f"Pie chart error: {e}")
    
    with col2:
        st.subheader("⭐ Top Recipients")
        try:
            data = db.get_top_merchants(days=days, limit=10)
            if data and len(data) > 0:
                df = pd.DataFrame(data).head(8).sort_values('total_amount', ascending=True)
                
                fig, ax = plt.subplots(figsize=(9, 5), facecolor='white')
                ax.barh(df['recipient'].astype(str), df['total_amount'], 
                       color='#FF9800', edgecolor='#333', linewidth=0.8)
                ax.set_xlabel('Amount (KES)', fontsize=10)
                ax.set_title('Top 8 Recipients', fontweight='bold', fontsize=12)
                ax.grid(axis='x', alpha=0.2)
                plt.tight_layout()
                st.pyplot(fig)
            else:
                st.info("⭐ No merchant data")
        except Exception as e:
            st.error(f"Error: {str(e)}")
            logger.error(f"Top merchants error: {e}")

# TAB 2: Ask AI
with tab2:
    st.header("💬 Ask AI")
    
    user_question = st.text_input("❓ Ask about your spending (or type a command):")
    
    if user_question:
        with st.spinner("🤖 Thinking..."):
            try:
                # Get rich context
                summary = db.get_summary()
                categories = db.get_spending_by_category(days=days)
                merchants = db.get_top_merchants(days=days, limit=5)
                daily_trend = db.get_daily_trend(days=7)
                
                context = {
                    'summary': summary,
                    'categories': categories,
                    'merchants': merchants,
                    'daily_trend': daily_trend
                }
                
                result = groq.ask_question(user_question, context)
                
                if result.get('success'):
                    st.markdown(result.get('analysis', 'No response'))
                else:
                    st.error(f"Error: {result.get('analysis', 'Failed to process')}")
            
            except Exception as e:
                st.error(f"Error: {str(e)}")
                logger.error(f"AI error: {e}")
    
    # Quick buttons
    st.divider()
    st.subheader("🎯 Quick Questions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📊 Bar chart", use_container_width=True):
            st.session_state.question = "Bar chart"
            st.rerun()
    
    with col2:
        if st.button("🥧 Pie chart", use_container_width=True):
            st.session_state.question = "Pie chart"
            st.rerun()
    
    with col3:
        if st.button("📈 Trend", use_container_width=True):
            st.session_state.question = "Trend"
            st.rerun()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("💰 Summary", use_container_width=True):
            st.session_state.question = "Summary"
            st.rerun()
    
    with col2:
        if st.button("⭐ Merchants", use_container_width=True):
            st.session_state.question = "Top merchants"
            st.rerun()
    
    with col3:
        if st.button("ℹ️ Help", use_container_width=True):
            st.session_state.question = "Help"
            st.rerun()

# TAB 3: Transactions
with tab3:
    st.header("📋 Transactions")
    
    try:
        data = db.get_transactions(days=days, limit=100)
        if data and len(data) > 0:
            df = pd.DataFrame(data)
            
            # Filters
            col1, col2, col3 = st.columns(3)
            
            with col1:
                transaction_type = st.multiselect(
                    "Filter by Type:",
                    df['type'].unique() if 'type' in df.columns else [],
                    default=df['type'].unique() if 'type' in df.columns else []
                )
            
            with col2:
                category = st.multiselect(
                    "Filter by Category:",
                    df['merchant_category'].unique() if 'merchant_category' in df.columns else [],
                    default=df['merchant_category'].unique() if 'merchant_category' in df.columns else []
                )
            
            with col3:
                min_amount = st.number_input("Min Amount:", min_value=0, value=0)
            
            # Apply filters
            if transaction_type:
                df = df[df['type'].isin(transaction_type)]
            if category:
                df = df[df['merchant_category'].isin(category)]
            if min_amount > 0:
                df = df[df['amount'] >= min_amount]
            
            # Display
            if not df.empty:
                display_cols = ['timestamp', 'amount', 'type', 'recipient', 'merchant_category', 'balance']
                display_cols = [col for col in display_cols if col in df.columns]
                
                st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
                
                # Stats
                st.divider()
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("📊 Transactions", len(df))
                
                with col2:
                    total = df['amount'].sum() if 'amount' in df.columns else 0
                    st.metric("💰 Total", f"KES {total:,.0f}")
                
                with col3:
                    avg = df['amount'].mean() if 'amount' in df.columns else 0
                    st.metric("📈 Average", f"KES {avg:,.0f}")
            else:
                st.info("No transactions match filters")
        else:
            st.info("No transactions available")
    except Exception as e:
        st.error(f"Error: {str(e)}")
        logger.error(f"Transactions error: {e}")

# TAB 4: Anomalies
with tab4:
    st.header("⚠️ Anomalies")
    
    try:
        anomalies = db.get_anomalies(threshold=2.5)
        if anomalies and len(anomalies) > 0:
            df = pd.DataFrame(anomalies)
            
            st.warning(f"🚨 Found {len(df)} unusual transactions")
            
            for idx, row in df.iterrows():
                with st.container(border=True):
                    col1, col2, col3 = st.columns([2, 1, 1])
                    
                    with col1:
                        st.markdown(f"**{row.get('recipient', 'Unknown')}**")
                        st.caption(f"📅 {row.get('timestamp', 'N/A')}")
                    
                    with col2:
                        st.metric("Amount", f"KES {row.get('amount', 0):,.0f}")
                    
                    with col3:
                        zscore = row.get('zscore', 0)
                        st.metric("Z-Score", f"{zscore:.2f}")
        else:
            st.success("✅ No anomalies detected!")
    except Exception as e:
        st.error(f"Error: {str(e)}")
        logger.error(f"Anomalies error: {e}")

# TAB 5: Analysis
with tab5:
    st.header("🧮 Detailed Analysis")
    
    try:
        insights = db.get_insights(days=days)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("💸 Total Spent", f"KES {insights.get('total_spent', 0):,.0f}")
        
        with col2:
            st.metric("📍 Top Merchant", insights.get('top_merchant', 'N/A'))
        
        with col3:
            st.metric("📂 Top Category", insights.get('top_category', 'N/A'))
        
        with col4:
            st.metric("📊 Count", insights.get('transaction_count', 0))
        
        st.divider()
        
        # AI Insights
        st.subheader("💡 AI Insights")
        try:
            dashboard_data = analyzer.get_dashboard_data(days=days)
            ai_insights = groq.generate_insights(dashboard_data)
            st.markdown(ai_insights)
        except Exception as e:
            st.info("AI insights coming soon!")
            logger.error(f"AI insights error: {e}")
    
    except Exception as e:
        st.error(f"Error: {str(e)}")
        logger.error(f"Analysis error: {e}")

# TAB 6: Help
with tab6:
    st.header("ℹ️ Help & Commands")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 Chart Commands")
        st.markdown("""
        - **Bar chart** - Spending by category
        - **Pie chart** - Distribution
        - **Trend** - Daily pattern (7 days)
        - **Heatmap** - Weekly grid
        - **Merchants** - Top 10 recipients
        - **Histogram** - Amount distribution
        """)
    
    with col2:
        st.subheader("💬 Question Examples")
        st.markdown("""
        - What did I spend on food?
        - How much to Safaricom?
        - Top 5 expenses?
        - Should I start a Sacco?
        - Budget for next month?
        - How can I save money?
        """)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📋 Report Commands")
        st.markdown("""
        - **Summary** - Last 30 days
        - **Daily summary** - Today's overview
        - **90 days** - 90-day report
        - **All time** - Complete history
        """)
    
    with col2:
        st.subheader("📱 Manual SMS Entry")
        st.markdown("""
        Format: `PIN-SMS_CONTENT`
        
        Example:
        `3749-UFMD8OKA Confirmed. Ksh100 paid to SHOP...`
        
        Send via WhatsApp bot
        """)
    
    st.divider()
    
    st.info("""
    🤖 **PesaPilot v2.1** - Kenya's AI Financial Assistant
    
    💡 **Features:**
    - AI-powered spending analysis
    - Visual charts and insights
    - Anomaly detection
    - M-Pesa transaction tracking
    - Smart financial advice
    - Kenyan financial products info
    
    📞 **Support:**
    - Ask any question about your finances
    - Use WhatsApp bot for instant analysis
    - Check Dashboard for overview
    
    ✨ Made with ❤️ in Kenya
    """)

st.divider()

# Footer
st.markdown("""
<div style="text-align: center; color: #666; font-size: 12px; margin-top: 30px;">
    <p>PesaPilot v2.1 | AI Financial Assistant for Kenya</p>
    <p>Track M-Pesa • Get Insights • Make Better Decisions</p>
</div>
""", unsafe_allow_html=True)