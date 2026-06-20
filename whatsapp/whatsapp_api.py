import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import logging
import re
import io
import base64
from datetime import datetime, time
from dotenv import load_dotenv
from src.analyzer import MpesaAnalyzer
from typing import Optional
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

plt.style.use('seaborn-v0_8-darkgrid')
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
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    plt.close()
    return img_b64

def _empty_chart(title: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 6), facecolor='white')
    ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=16, color='gray')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    ax.axis('off')
    plt.tight_layout()
    return _encode_figure()

def generate_bar_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str = "Spending by Category") -> Optional[str]:
    try:
        if df is None or df.empty or category_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        chart_data = df.groupby(category_col)[value_col].sum().sort_values(ascending=True)
        if chart_data.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(12, 7), facecolor='white')
        bars = ax.barh(chart_data.index, chart_data.values, color=sns.color_palette("husl", len(chart_data)), edgecolor='black', linewidth=0.5)
        
        ax.set_xlabel('Amount (KES)', fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.grid(axis='x', alpha=0.3)

        for bar, value in zip(bars, chart_data.values):
            ax.text(value, bar.get_y() + bar.get_height() / 2, f' KES {value:,.0f}', va='center', ha='left', fontsize=10, fontweight='bold')

        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Bar chart error: {e}")
        return None

def generate_pie_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str = "Spending Distribution") -> Optional[str]:
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

        fig, ax = plt.subplots(figsize=(12, 8), facecolor='white')
        colors = sns.color_palette("husl", len(chart_data))
        wedges, texts, autotexts = ax.pie(
            chart_data.values,
            labels=chart_data.index,
            autopct='%1.1f%%',
            startangle=90,
            colors=colors,
            explode=[0.05] * len(chart_data)
        )

        for text in texts:
            text.set_fontsize(10)
            text.set_fontweight('bold')

        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(9)

        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Pie chart error: {e}")
        return None

def generate_line_chart(df: pd.DataFrame, date_col: str, value_col: str, title: str = "Spending Trend") -> Optional[str]:
    try:
        if df is None or df.empty or date_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        daily = df.groupby(df[date_col].dt.date)[value_col].sum().sort_index()

        if daily.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(14, 7), facecolor='white')
        ax.plot(daily.index, daily.values, marker='o', linewidth=3, markersize=8, color='#2E86AB', markerfacecolor='#A23B72', markeredgewidth=2, markeredgecolor='#2E86AB')
        
        ax.fill_between(range(len(daily)), daily.values, alpha=0.3, color='#2E86AB')
        
        ax.set_xlabel('Date', fontsize=11, fontweight='bold')
        ax.set_ylabel('Amount (KES)', fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        plt.xticks(rotation=45, ha='right')
        ax.grid(True, alpha=0.3)

        for i, (date, value) in enumerate(zip(daily.index, daily.values)):
            ax.text(i, value, f'KES {value:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Line chart error: {e}")
        return None

def generate_heatmap_chart(df: pd.DataFrame, date_col: str, category_col: str, value_col: str, title: str = "Spending Heatmap") -> Optional[str]:
    try:
        if df is None or df.empty:
            return _empty_chart(title)

        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col])
        df['week'] = df[date_col].dt.isocalendar().week
        df['day_name'] = df[date_col].dt.day_name()

        pivot = df.pivot_table(values=value_col, index=category_col, columns='day_name', aggfunc='sum', fill_value=0)
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        pivot = pivot[[d for d in day_order if d in pivot.columns]]

        fig, ax = plt.subplots(figsize=(14, 8), facecolor='white')
        sns.heatmap(pivot, annot=True, fmt='.0f', cmap='YlOrRd', cbar_kws={'label': 'Amount (KES)'}, ax=ax, linewidths=0.5, linecolor='gray')
        
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Day of Week', fontsize=11, fontweight='bold')
        ax.set_ylabel('Category', fontsize=11, fontweight='bold')
        
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Heatmap error: {e}")
        return None

def generate_top_merchants_chart(df: pd.DataFrame, recipient_col: str, value_col: str, title: str = "Top Merchants") -> Optional[str]:
    try:
        if df is None or df.empty or recipient_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        top_merchants = df.groupby(recipient_col)[value_col].agg(['sum', 'count']).sort_values('sum', ascending=False).head(10)
        
        if top_merchants.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(12, 7), facecolor='white')
        bars = ax.barh(range(len(top_merchants)), top_merchants['sum'].values, color=sns.color_palette("coolwarm", len(top_merchants)), edgecolor='black', linewidth=0.5)
        
        ax.set_yticks(range(len(top_merchants)))
        ax.set_yticklabels([name[:20] for name in top_merchants.index], fontsize=10)
        ax.set_xlabel('Total Amount (KES)', fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.grid(axis='x', alpha=0.3)

        for i, (bar, value, count) in enumerate(zip(bars, top_merchants['sum'].values, top_merchants['count'].values)):
            ax.text(value, bar.get_y() + bar.get_height() / 2, f' KES {value:,.0f} ({int(count)} txs)', va='center', ha='left', fontsize=9, fontweight='bold')

        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Top merchants chart error: {e}")
        return None

def generate_histogram_chart(df: pd.DataFrame, value_col: str, title: str = "Spending Distribution") -> Optional[str]:
    try:
        if df is None or df.empty or value_col not in df.columns:
            return _empty_chart(title)

        data = df[value_col].dropna()
        if data.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(12, 7), facecolor='white')
        n, bins, patches = ax.hist(data, bins=20, color='#2E86AB', edgecolor='black', linewidth=0.7, alpha=0.8)
        
        for patch in patches:
            patch.set_facecolor(plt.cm.viridis(patch.get_height() / max(n)))

        ax.set_xlabel('Amount (KES)', fontsize=11, fontweight='bold')
        ax.set_ylabel('Frequency', fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.grid(axis='y', alpha=0.3)

        mean_val = data.mean()
        median_val = data.median()
        ax.axvline(mean_val, color='red', linestyle='--', linewidth=2, label=f'Mean: KES {mean_val:,.0f}')
        ax.axvline(median_val, color='green', linestyle='--', linewidth=2, label=f'Median: KES {median_val:,.0f}')
        ax.legend(fontsize=10)

        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Histogram error: {e}")
        return None

analyzer = MpesaAnalyzer()

def generate_daily_summary() -> str:
    """Generate daily summary at 7 AM"""
    try:
        summary = analyzer.db.get_summary()
        insights = analyzer.db.get_insights()

        if not summary or summary.get('total_transactions', 0) == 0:
            return "📊 No transactions today yet."

        highest = (insights.get('highest_payment', 0) if insights else 0)
        top_cat = (insights.get('top_category', 'N/A') if insights else 'N/A')
        avg_spend = summary.get('total_spent', 0) / max(summary.get('total_transactions', 1), 1)

        msg = f"""📊 Daily Summary - {datetime.now().strftime('%A, %B %d, %Y')}

💰 Stats:
  • Transactions: {summary.get('total_transactions', 0)}
  • Spent: KES {summary.get('total_spent', 0):,.0f}
  • Received: KES {summary.get('total_received', 0):,.0f}
  • Balance: KES {summary.get('balance', 0):,.0f}

📈 Insights:
  • Top Category: {top_cat}
  • Highest Payment: KES {highest:,.0f}
  • Avg Transaction: KES {avg_spend:,.0f}

💡 Tip: Review your spending patterns to identify savings opportunities.

Use 'Help' for more options."""
        
        logger.info("✅ Daily summary generated")
        return msg
    except Exception as e:
        logger.error(f"Error generating daily summary: {e}")
        return "❌ Error generating summary."

scheduler = BackgroundScheduler()
scheduler.add_job(lambda: logger.info("📅 Daily summary ready at 7 AM"), CronTrigger(hour=7, minute=0))
scheduler.start()

app = FastAPI(title="PesaPilot API", version="2.0", docs_url=None, redoc_url=None)

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost", "http://localhost:8000", "http://localhost:3000"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "PesaPilot API", "timestamp": datetime.now().isoformat()}

@app.post("/ask", response_model=AnalysisResponse)
async def ask_question(request: QuestionRequest):
    try:
        question = request.question.strip()

        if not question or len(question) < 2 or len(question) > 500:
            raise HTTPException(status_code=400, detail="Question too short or too long (2-500 chars)")

        if not is_safe_question(question):
            logger.warning("🚨 BLOCKED: Destructive operation attempted")
            raise HTTPException(status_code=403, detail="Invalid question - contains forbidden keywords")

        logger.info(f"📨 Q: {question[:50]}")

        question_lower = question.lower().strip()

        chart_keywords = {
            'bar': ('Spending by Category', 'merchant_category', 'total_amount'),
            'pie': ('Spending Distribution', 'merchant_category', 'total_amount'),
            'trend': ('Daily Spending Trend', 'date', 'total_spent'),
            'line': ('Daily Spending Trend', 'date', 'total_spent'),
            'heatmap': ('Weekly Spending Heatmap', None, None),
            'merchants': ('Top 10 Merchants', 'recipient', 'amount'),
            'histogram': ('Transaction Amount Distribution', 'amount', None),
            'chart': ('Spending by Category', 'merchant_category', 'total_amount'),
            'graph': ('Spending by Category', 'merchant_category', 'total_amount'),
            'visualize': ('Spending by Category', 'merchant_category', 'total_amount'),
        }

        chart_type = None
        for key in chart_keywords.keys():
            if key in question_lower:
                chart_type = key
                break

        if chart_type:
            logger.info(f"📊 Chart: {chart_type}")
            data = analyzer.get_dashboard_data(days=30)
            chart_img = None
            analysis = ""

            if chart_type == 'bar' or chart_type == 'chart' or chart_type == 'graph':
                df = pd.DataFrame(data.get('spending_by_category', []))
                chart_img = generate_bar_chart(df, 'merchant_category', 'total_amount', '📊 Spending by Category')
                analysis = "📊 Here's your spending breakdown by category:"

            elif chart_type == 'pie':
                df = pd.DataFrame(data.get('spending_by_category', []))
                chart_img = generate_pie_chart(df, 'merchant_category', 'total_amount', '🥧 Spending Distribution')
                analysis = "🥧 Here's your spending distribution:"

            elif chart_type in ['trend', 'line']:
                df = pd.DataFrame(data.get('daily_trend', []))
                chart_img = generate_line_chart(df, 'date', 'total_spent', '📈 Daily Spending Trend')
                analysis = "📈 Here's your spending trend over time:"

            elif chart_type == 'heatmap':
                df = pd.DataFrame(data.get('daily_trend', []) + data.get('spending_by_category', []))
                if not df.empty:
                    chart_img = generate_heatmap_chart(df, 'date', 'merchant_category', 'total_amount', '🔥 Weekly Spending Heatmap')
                    analysis = "🔥 Here's your spending heatmap by day and category:"

            elif chart_type == 'merchants':
                raw_data = analyzer.db.get_transactions(days=30, limit=500)
                df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                if not df.empty:
                    chart_img = generate_top_merchants_chart(df, 'recipient', 'amount', '🏆 Top 10 Merchants')
                    analysis = "🏆 Here are your top merchants:"

            elif chart_type == 'histogram':
                raw_data = analyzer.db.get_transactions(days=30, limit=500)
                df = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
                if not df.empty:
                    chart_img = generate_histogram_chart(df, 'amount', '📊 Transaction Amount Distribution')
                    analysis = "📊 Here's your transaction distribution:"

            if not chart_img:
                analysis = "❌ No data available for chart."

            return AnalysisResponse(question=question, analysis=analysis, chart=chart_img)

        if question_lower == 'help':
            help_text = """🤖 PesaPilot Assistant v2.0

💬 Ask about spending:
  • "What did I spend on food?"
  • "How much to Safaricom?"
  • "Top 5 expenses?"

📊 Charts (Visual Analytics):
  • "Bar chart" — spending by category
  • "Pie chart" — distribution
  • "Trend" — line chart trend
  • "Heatmap" — weekly activity
  • "Top merchants" — top 10
  • "Histogram" — amount distribution

📊 Reports:
  • "Summary" (30d) / "90 days" / "All time"
  • "Daily summary" — today's overview

📝 Manual SMS:
  • PIN-PASTE_YOUR_SMS_HERE

AI-Powered Analysis — just ask naturally! 💬"""
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
                analysis = f"""📊 Summary ({days} days)

💰 Transactions: {summary.get('total_transactions', 0)}
💸 Spent: KES {summary.get('total_spent', 0):,.0f}
💵 Received: KES {summary.get('total_received', 0):,.0f}
📈 Avg/day: KES {summary.get('total_spent', 0) / max(days, 1):,.0f}
⚖️ Balance: KES {summary.get('balance', 0):,.0f}"""
            else:
                analysis = "📭 No transactions found."

            return AnalysisResponse(question=request.question, analysis=analysis)

        logger.info("🔄 AI processing")
        result = analyzer.ask_question(question)

        if result.get('error'):
            analysis = f"⚠️ {clean_response(result.get('error', 'Error processing question'))}"
        else:
            analysis = clean_response(result.get('analysis', 'No response'))

        return AnalysisResponse(question=request.question, analysis=analysis, error=result.get('error'))

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ Server error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)[:100]}")

@app.post("/parse-sms", response_model=ParseSMSResponse)
async def parse_sms(request: ParseSMSRequest):
    try:
        sms = request.sms_content.strip()

        if not sms or len(sms) < 20 or len(sms) > 1000:
            return ParseSMSResponse(success=False, summary="", error="SMS must be 20-1000 chars")

        if not is_valid_mpesa_sms(sms):
            return ParseSMSResponse(success=False, summary="", error="Not a valid M-Pesa SMS")

        logger.info(f"📝 SMS: {len(sms)}c")

        from src.parse_sms import MpesaParser

        parser = MpesaParser()
        tx = parser._parse_sms_text(sms)

        if not tx:
            return ParseSMSResponse(success=False, summary="", error="Failed to parse SMS")

        if not tx.get('transaction_id') or not tx.get('amount') or tx.get('amount') <= 0:
            return ParseSMSResponse(success=False, summary="", error="Missing transaction ID or amount")

        logger.info(f"💾 Storing: {tx.get('transaction_id')}")

        df = pd.DataFrame([tx])
        count = analyzer.db.insert_transactions(df)

        if count == 0:
            return ParseSMSResponse(success=False, summary="", error="Duplicate transaction")

        summary = f"""✅ Stored!

💰 Type: {tx.get('type', '?').upper()}
📊 Amount: KES {tx.get('amount', 0):,.2f}
👤 To/From: {tx.get('recipient', 'Unknown')[:25]}
🏷️ Category: {tx.get('merchant_category', 'other')}
📅 Date: {tx.get('readable_date', 'N/A')}
🔑 ID: {tx.get('transaction_id', 'N/A')[:8]}"""

        logger.info(f"✅ OK: {tx.get('transaction_id')}")
        return ParseSMSResponse(success=True, summary=summary, error=None)

    except Exception as e:
        logger.error(f"❌ Parse error: {str(e)}")
        return ParseSMSResponse(success=False, summary="", error=f"Parse error: {str(e)[:50]}")

if __name__ == '__main__':
    import uvicorn
    print('\n🚀 PesaPilot API v2.0\n')
    uvicorn.run(app, host='0.0.0.0', port=WHATSAPP_API_PORT, log_level='warning')