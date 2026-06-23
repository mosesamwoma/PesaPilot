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
from typing import Optional
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

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

        for i, (bar, value) in enumerate(zip(bars, chart_data.values)):
            ax.text(value, bar.get_y() + bar.get_height()/2, f' KES {value:,.0f}', 
                   va='center', ha='left', fontsize=10, fontweight='bold', color='#333333')

        ax.set_ylim(-0.5, len(chart_data)-0.5)
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Bar chart error: {e}")
        return None

def generate_pie_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str = "🥧 Spending Distribution") -> Optional[str]:
    try:
        if df is None or df.empty or category_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        chart_data = df.groupby(category_col)[value_col].sum().sort_values(ascending=False)
        if chart_data.empty:
            return _empty_chart(title)

        if len(chart_data) > 8:
            other_sum = chart_data.iloc[8:].sum()
            chart_data = chart_data.iloc[:8].copy()
            if other_sum > 0:
                chart_data['Other'] = other_sum

        fig, ax = plt.subplots(figsize=(11, 9), facecolor='white', edgecolor='#e0e0e0')
        colors = sns.color_palette("husl", len(chart_data))
        
        wedges, texts, autotexts = ax.pie(
            chart_data.values,
            labels=chart_data.index,
            autopct='%1.1f%%',
            startangle=90,
            colors=colors,
            explode=[0.08]*len(chart_data),
            shadow=True,
            textprops={'fontsize': 11, 'weight': 'bold'}
        )

        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(10)

        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Pie chart error: {e}")
        return None

def generate_line_chart(df: pd.DataFrame, date_col: str, value_col: str, title: str = "📈 Daily Spending Trend") -> Optional[str]:
    try:
        if df is None or df.empty or date_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        df_sorted = df.sort_values(by=date_col)
        if df_sorted.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(13, 7), facecolor='white', edgecolor='#e0e0e0')
        
        ax.plot(df_sorted[date_col], df_sorted[value_col], marker='o', linewidth=3, 
               markersize=8, color='#FF6B6B', label='Daily Spending', markerfacecolor='#FF6B6B', markeredgecolor='white', markeredgewidth=1.5)
        ax.fill_between(range(len(df_sorted)), df_sorted[value_col], alpha=0.25, color='#FF6B6B')

        max_val = df_sorted[value_col].max()
        min_val = df_sorted[value_col].min()
        avg_val = df_sorted[value_col].mean()
        
        ax.axhline(y=avg_val, color='#4CAF50', linestyle='--', linewidth=2, alpha=0.7, label=f'Avg: KES {avg_val:,.0f}')
        ax.text(0.02, 0.95, f'Max: KES {max_val:,.0f}\nMin: KES {min_val:,.0f}\nAvg: KES {avg_val:,.0f}', 
               transform=ax.transAxes, fontsize=10, verticalalignment='top',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5), family='monospace', weight='bold')

        ax.set_xlabel('Date', fontsize=12, fontweight='bold', color='#333333')
        ax.set_ylabel('Amount (KES)', fontsize=12, fontweight='bold', color='#333333')
        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')
        ax.grid(True, alpha=0.3, linestyle='--', color='#cccccc')
        ax.legend(loc='upper left', fontsize=10, framealpha=0.9)
        plt.xticks(rotation=45, ha='right')

        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Line chart error: {e}")
        return None

def generate_heatmap_chart(df: pd.DataFrame, date_col: str, category_col: str, value_col: str, title: str = "🔥 Weekly Spending Heatmap") -> Optional[str]:
    try:
        if df is None or df.empty or date_col not in df.columns or category_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        df = df.copy()
        df = df[df.get('type', 'debit').isin(['debit', 'payment', 'withdrawal'])]
        
        if df.empty:
            return _empty_chart(title)

        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col])
        
        if df.empty:
            return _empty_chart(title)

        df['day'] = df[date_col].dt.day_name()
        df[category_col] = df[category_col].fillna('Other')
        df[value_col] = pd.to_numeric(df[value_col], errors='coerce').fillna(0)

        pivot = df.pivot_table(
            values=value_col,
            index=category_col,
            columns='day',
            aggfunc='sum',
            fill_value=0
        )

        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        available_days = [d for d in day_order if d in pivot.columns]

        if not available_days or pivot.empty or pivot.values.max() == 0:
            return _empty_chart(title)

        pivot = pivot[available_days]

        fig, ax = plt.subplots(figsize=(13, 8), facecolor='white', edgecolor='#e0e0e0')
        im = ax.imshow(pivot.values, cmap='YlOrRd', aspect='auto', interpolation='nearest')
        
        cbar = plt.colorbar(im, ax=ax, label='Amount (KES)', shrink=0.8)
        cbar.ax.tick_params(labelsize=10)

        ax.set_xticks(range(len(pivot.columns)))
        ax.set_yticks(range(len(pivot.index)))
        ax.set_xticklabels(pivot.columns, fontsize=11, weight='bold')
        ax.set_yticklabels(pivot.index, fontsize=11, weight='bold')

        ax.set_xlabel('Day of Week', fontsize=12, fontweight='bold', color='#333333')
        ax.set_ylabel('Category', fontsize=12, fontweight='bold', color='#333333')
        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')

        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                text = ax.text(j, i, f'{pivot.values[i, j]:.0f}',
                              ha="center", va="center", color="black" if pivot.values[i, j] < pivot.values.max()/2 else "white", 
                              fontsize=9, fontweight='bold')

        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Heatmap chart error: {e}")
        return None

def generate_top_merchants_chart(df: pd.DataFrame, recipient_col: str, value_col: str, title: str = "🏆 Top 10 Merchants") -> Optional[str]:
    try:
        if df is None or df.empty or recipient_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)
        
        if 'type' in df.columns:
            df = df[df['type'].isin(['debit', 'payment', 'withdrawal'])]
        
        if df.empty:
            return _empty_chart(title)
        
        chart_data = df.groupby(recipient_col)[value_col].sum().sort_values(ascending=True).tail(10)
        
        if chart_data.empty:
            return _empty_chart(title)
        
        fig, ax = plt.subplots(figsize=(13, 8), facecolor='white', edgecolor='#e0e0e0')
        colors = sns.color_palette("RdYlGn_r", len(chart_data))
        bars = ax.barh(chart_data.index, chart_data.values, color=colors, edgecolor='#333333', linewidth=1.2)
        
        ax.set_xlabel('Total Amount (KES)', fontsize=12, fontweight='bold', color='#333333')
        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')
        ax.grid(axis='x', alpha=0.3, linestyle='--', color='#cccccc')
        
        for bar, value in zip(bars, chart_data.values):
            ax.text(value, bar.get_y() + bar.get_height()/2, f' KES {value:,.0f}', 
                   va='center', ha='left', fontsize=10, fontweight='bold', color='#333333')
        
        plt.tight_layout()
        return _encode_figure()
    
    except Exception as e:
        logger.error(f"Top merchants chart error: {e}")
        return None

def generate_histogram_chart(df: pd.DataFrame, value_col: str, title: str = "📊 Transaction Distribution") -> Optional[str]:
    try:
        if df is None or df.empty or value_col not in df.columns:
            return _empty_chart(title)
        
        if 'type' in df.columns:
            df = df[df['type'].isin(['debit', 'payment', 'withdrawal'])]
        
        if df.empty:
            return _empty_chart(title)
        
        amounts = df[value_col].dropna()
        amounts = amounts[amounts > 0]
        
        if amounts.empty or len(amounts) < 2:
            return _empty_chart(title)
        
        fig, ax = plt.subplots(figsize=(13, 7), facecolor='white', edgecolor='#e0e0e0')
        n, bins, patches = ax.hist(amounts, bins=25, color='#2196F3', edgecolor='#333333', linewidth=1, alpha=0.8)
        
        mean_val = amounts.mean()
        median_val = amounts.median()
        std_val = amounts.std()
        
        ax.axvline(mean_val, color='#FF6B6B', linestyle='--', linewidth=2.5, label=f'Mean: KES {mean_val:,.0f}', alpha=0.8)
        ax.axvline(median_val, color='#4CAF50', linestyle='--', linewidth=2.5, label=f'Median: KES {median_val:,.0f}', alpha=0.8)
        
        ax.text(0.98, 0.95, f'Mean: KES {mean_val:,.0f}\nMedian: KES {median_val:,.0f}\nStd Dev: KES {std_val:,.0f}\nTotal: {len(amounts)} transactions', 
               transform=ax.transAxes, fontsize=10, verticalalignment='top', horizontalalignment='right',
               bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.7), family='monospace', weight='bold')
        
        ax.set_xlabel('Amount (KES)', fontsize=12, fontweight='bold', color='#333333')
        ax.set_ylabel('Frequency', fontsize=12, fontweight='bold', color='#333333')
        ax.set_title(title, fontsize=15, fontweight='bold', pad=20, color='#333333')
        ax.grid(axis='y', alpha=0.3, linestyle='--', color='#cccccc')
        ax.legend(loc='upper right', fontsize=10, framealpha=0.9)
        
        plt.tight_layout()
        return _encode_figure()
    
    except Exception as e:
        logger.error(f"Histogram chart error: {e}")
        return None

def generate_daily_summary() -> str:
    try:
        analyzer = MpesaAnalyzer()
        summary = analyzer.db.get_summary()
        
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
• Average per transaction: KES {spent/max(transactions, 1):,.0f}
• Spending velocity: {'High' if spent > 5000 else 'Moderate' if spent > 1000 else 'Low'}
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

        chart_keywords = {
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

        chart_type = None
        for key in chart_keywords.keys():
            if key in question_lower:
                chart_type = key
                break

        if chart_type:
            logger.info(f"📊 {chart_type.upper()}")
            data = analyzer.get_dashboard_data(days=30)
            chart_img = None
            analysis = ""

            if chart_type in ['bar', 'chart', 'graph', 'bar chart']:
                df = pd.DataFrame(data.get('spending_by_category', []))
                chart_img = generate_bar_chart(df, 'merchant_category', 'total_amount')
                top_cat = df.nlargest(1, 'total_amount')
                if not top_cat.empty:
                    top_name = top_cat.iloc[0]['merchant_category']
                    top_amount = top_cat.iloc[0]['total_amount']
                    analysis = f"📊 **Spending Breakdown by Category**\n\n🔝 Top: {top_name} (KES {top_amount:,.0f})\n✅ Chart generated showing all categories ranked by spending"

            elif chart_type in ['pie', 'pie chart']:
                df = pd.DataFrame(data.get('spending_by_category', []))
                chart_img = generate_pie_chart(df, 'merchant_category', 'total_amount')
                total = df['total_amount'].sum()
                analysis = f"🥧 **Spending Distribution Overview**\n\n💰 Total: KES {total:,.0f}\n✅ Percentages shown for each category"

            elif chart_type in ['trend', 'line', 'line chart', 'over days', 'over time', 'spending over', 'daily trend', 'spending trend']:
                df = pd.DataFrame(data.get('daily_trend', []))
                chart_img = generate_line_chart(df, 'date', 'total_spent')
                if not df.empty:
                    max_day = df.loc[df['total_spent'].idxmax()]
                    analysis = f"📈 **7-Day Spending Trend**\n\n📍 Peak Day: {max_day['date']} (KES {max_day['total_spent']:,.0f})\n✅ Shows daily spending pattern with average line"

            elif chart_type in ['heatmap', 'heat map', 'weekly']:
                raw_data = analyzer.db.get_transactions(days=90, limit=1000)
                df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                if not df.empty:
                    chart_img = generate_heatmap_chart(df, 'timestamp', 'merchant_category', 'amount')
                    analysis = "🔥 **Weekly Spending Heatmap**\n\n📅 Shows spending patterns across days and categories\n✅ Darker colors = higher spending"

            elif chart_type in ['merchants', 'top merchants', 'top recipients', 'recipients', 'top spending']:
                raw_data = analyzer.db.get_transactions(days=30, limit=500)
                df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                if not df.empty:
                    chart_img = generate_top_merchants_chart(df, 'recipient', 'amount')
                    top_recipient = df.nlargest(1, 'amount')
                    if not top_recipient.empty:
                        analysis = f"🏆 **Top 10 Recipients**\n\n💸 #1: {top_recipient.iloc[0]['recipient']} (KES {top_recipient.iloc[0]['amount']:,.0f})\n✅ Your most frequent spending targets"

            elif chart_type in ['histogram', 'distribution', 'amount distribution']:
                raw_data = analyzer.db.get_transactions(days=30, limit=500)
                df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                if not df.empty:
                    chart_img = generate_histogram_chart(df, 'amount')
                    amounts = df[df['amount'] > 0]['amount']
                    analysis = f"📊 **Transaction Amount Analysis**\n\n📈 Average: KES {amounts.mean():,.0f}\n📌 Most Common: KES {amounts.median():,.0f}\n✅ Distribution shows spending pattern"

            if not chart_img:
                analysis = "❌ No data available yet. Start by sending M-Pesa SMS or using: PIN-SMS_CONTENT"

            return AnalysisResponse(question=question, analysis=analysis, chart=chart_img)

        if question_lower == 'help':
            help_text = """🤖 **PesaPilot v2.1 - Your AI Financial Assistant**

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

📋 **REPORTS**:
  • "Summary" → Last 30 days
  • "Daily summary" / "Today" → Today's overview
  • "90 days" / "All time" → Extended periods

📱 **MANUAL SMS**:
  • PIN-PASTE_SMS_HERE (e.g., 3749-UFMD8OKA...)

✨ Just ask naturally! Charts & analysis are smart."""
            return AnalysisResponse(question=request.question, analysis=help_text)

        if 'daily' in question_lower or 'today' in question_lower:
            analysis = generate_daily_summary()
            return AnalysisResponse(question=request.question, analysis=analysis)

        if 'summary' in question_lower:
            days = 30
            if 'all time' in question_lower or 'year' in question_lower:
                days = 365
            elif '180' in question_lower:
                days = 180
            elif '90' in question_lower:
                days = 90
            elif 'week' in question_lower:
                days = 7

            logger.info(f"📊 Summary: {days}d")
            summary = analyzer.db.get_summary()

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
• Daily Average: KES {spent / max(days, 1):,.0f}
• Per Transaction: KES {spent / max(transactions, 1):,.0f}
• Spending Trend: {'📈 Increasing' if spent > received else '📉 Decreasing'}"""
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

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ Server error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)[:100]}")

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