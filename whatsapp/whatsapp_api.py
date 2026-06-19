# whatsapp/whatsapp_api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
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

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# ──────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────

WHATSAPP_PIN = os.getenv('WHATSAPP_PIN')
WHATSAPP_API_PORT = int(os.getenv('WHATSAPP_API_PORT', 8000))

if not WHATSAPP_PIN:
    raise ValueError("WHATSAPP_PIN must be set in .env")

DANGEROUS_KEYWORDS = [
    'DELETE', 'DROP', 'TRUNCATE', 'UPDATE',
    'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC'
]

# ──────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────

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

# ──────────────────────────────────────────────────────────────────────────
# Security Functions
# ──────────────────────────────────────────────────────────────────────────

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

# ──────────────────────────────────────────────────────────────────────────
# Chart Generation
# ──────────────────────────────────────────────────────────────────────────

def _encode_figure() -> str:
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    plt.close()
    return img_b64


def _empty_chart(title: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=14)
    ax.set_title(title, fontsize=14, fontweight='bold')
    plt.tight_layout()
    return _encode_figure()


def generate_bar_chart(df: pd.DataFrame, category_col: str, value_col: str, title: str = "Spending by Category") -> Optional[str]:
    try:
        if df is None or df.empty or category_col not in df.columns or value_col not in df.columns:
            return _empty_chart(title)

        chart_data = df.groupby(category_col)[value_col].sum().sort_values(ascending=True)

        if chart_data.empty:
            return _empty_chart(title)

        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.barh(chart_data.index, chart_data.values,
                       color=sns.color_palette("husl", len(chart_data)))
        ax.set_xlabel('Amount (KES)')
        ax.set_title(title, fontsize=14, fontweight='bold')

        for bar, value in zip(bars, chart_data.values):
            ax.text(value, bar.get_y() + bar.get_height() / 2,
                    f'KES {value:,.0f}', va='center', ha='left', fontsize=9)

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

        fig, ax = plt.subplots(figsize=(10, 8))
        wedges, texts, autotexts = ax.pie(
            chart_data.values,
            labels=chart_data.index,
            autopct='%1.1f%%',
            startangle=90,
            colors=sns.color_palette("husl", len(chart_data))
        )

        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')

        ax.set_title(title, fontsize=14, fontweight='bold')
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

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(daily.index, daily.values, marker='o', linewidth=2, markersize=4)
        ax.set_xlabel('Date')
        ax.set_ylabel('Amount (KES)')
        ax.set_title(title, fontsize=14, fontweight='bold')
        plt.xticks(rotation=45, ha='right')
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        return _encode_figure()
    except Exception as e:
        logger.error(f"Line chart error: {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PesaPilot API",
    version="1.0",
    docs_url=None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:8000", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

analyzer = MpesaAnalyzer()

# ──────────────────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "PesaPilot API",
        "timestamp": datetime.now().isoformat()
    }

# ──────────────────────────────────────────────────────────────────────────
# Ask Question
# ──────────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AnalysisResponse)
async def ask_question(request: QuestionRequest):
    try:
        question = request.question.strip()

        if not question or len(question) < 2 or len(question) > 500:
            raise HTTPException(status_code=400, detail="Invalid question length")

        if not is_safe_question(question):
            logger.warning("🚨 BLOCKED: Destructive operation attempted")
            raise HTTPException(status_code=403, detail="Invalid query")

        logger.info(f"📨 Question: {question[:50]}")

        question_lower = question.lower().strip()

        # ─ CHARTS ───────────────────────────────────────────────────────────
        chart_keywords = ['chart', 'graph', 'visualize', 'show me', 'plot', 'pie', 'bar', 'trend']

        if any(k in question_lower for k in chart_keywords):
            logger.info("📊 Chart requested")

            data = analyzer.get_dashboard_data(days=30)
            category_data = data.get('spending_by_category', [])
            daily_trend   = data.get('daily_trend', [])

            df_cat   = pd.DataFrame(category_data) if category_data else pd.DataFrame()
            df_trend = pd.DataFrame(daily_trend)   if daily_trend   else pd.DataFrame()

            chart_img = None
            analysis  = ""

            if 'pie' in question_lower or 'distribution' in question_lower:
                chart_img = generate_pie_chart(
                    df_cat, 'merchant_category', 'total_amount',
                    'Spending Distribution by Category'
                )
                analysis = "📊 Here is your spending distribution by category:"

            elif 'trend' in question_lower or 'line' in question_lower or 'over time' in question_lower:
                chart_img = generate_line_chart(
                    df_trend, 'date', 'total_spent',
                    'Daily Spending Trend'
                )
                analysis = "📈 Here is your spending trend over time:"

            else:
                chart_img = generate_bar_chart(
                    df_cat, 'merchant_category', 'total_amount',
                    'Spending by Category'
                )
                analysis = "📊 Here is your spending by category:"

            if not chart_img:
                analysis = "Could not generate chart. Try again."

            return AnalysisResponse(
                question=question,
                analysis=analysis,
                chart=chart_img
            )

        # ─ HELP ─────────────────────────────────────────────────────────────
        if question_lower == 'help':
            help_text = """🤖 PesaPilot Assistant

💬 Ask about spending:
  • "What did I spend on food?"
  • "How much to Safaricom?"
  • "Top 5 expenses?"
  • "Unusual spending?"

📊 Charts:
  • "Chart categories" — bar chart
  • "Pie chart" — distribution
  • "Trend" — line chart over time

📊 Reports:
  • "Summary" (30 days)
  • "Summary 90 days"
  • "Summary 180 days"
  • "Summary all time"

📝 Manual SMS entry:
  • PIN|PASTE_YOUR_SMS_HERE

Just ask naturally! 💬"""
            return AnalysisResponse(question=request.question, analysis=help_text)

        # ─ SUMMARY ──────────────────────────────────────────────────────────
        if 'summary' in question_lower:
            days = 30
            if 'all time' in question_lower:
                days = 365
            elif '180' in question_lower:
                days = 180
            elif '90' in question_lower:
                days = 90
            elif 'week' in question_lower:
                days = 7

            logger.info(f"📊 Summary: {days} days")
            summary = analyzer.db.get_summary()

            if summary and summary.get('total_transactions', 0) > 0:
                analysis = f"""📊 Summary ({days} days)

💰 Transactions: {summary.get('total_transactions', 0)}
💸 Spent: KES {summary.get('total_spent', 0):,.0f}
💵 Received: KES {summary.get('total_received', 0):,.0f}
📈 Avg/day: KES {summary.get('total_spent', 0) / max(days, 1):,.0f}"""
            else:
                analysis = "No data found."

            return AnalysisResponse(question=request.question, analysis=analysis)

        # ─ AI QUESTION ──────────────────────────────────────────────────────
        logger.info("🔄 AI processing")
        result = analyzer.ask_question(question)

        analysis = clean_response(result.get('analysis', 'No response'))

        return AnalysisResponse(
            question=request.question,
            analysis=analysis,
            error=result.get('error')
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Error")

# ──────────────────────────────────────────────────────────────────────────
# Parse SMS
# ──────────────────────────────────────────────────────────────────────────

@app.post("/parse-sms", response_model=ParseSMSResponse)
async def parse_sms(request: ParseSMSRequest):
    try:
        sms = request.sms_content.strip()

        if not sms or len(sms) < 20 or len(sms) > 1000:
            return ParseSMSResponse(success=False, summary="", error="Invalid SMS length")

        if not is_valid_mpesa_sms(sms):
            return ParseSMSResponse(success=False, summary="", error="Not M-Pesa SMS")

        logger.info(f"📝 Parsing SMS ({len(sms)} chars)")

        from src.parse_sms import MpesaParser

        parser = MpesaParser()
        tx = parser._parse_sms_text(sms)

        if not tx:
            return ParseSMSResponse(success=False, summary="", error="Could not parse SMS")

        if not tx.get('transaction_id') or not tx.get('amount') or tx.get('amount') <= 0:
            return ParseSMSResponse(success=False, summary="", error="Missing required fields")

        logger.info(f"💾 Storing: {tx.get('transaction_id')}")

        df = pd.DataFrame([tx])
        count = analyzer.db.insert_transactions(df)

        if count == 0:
            return ParseSMSResponse(success=False, summary="", error="Transaction already exists")

        summary = f"""✅ Stored!

💰 Type: {tx.get('type', 'unknown').upper()}
📊 Amount: KES {tx.get('amount', 0):,.2f}
👤 To/From: {tx.get('recipient', 'Unknown')[:30]}
🏷️ Category: {tx.get('merchant_category', 'other')}
📅 Date: {tx.get('readable_date', 'N/A')}"""

        logger.info(f"✅ Stored: {tx.get('transaction_id')}")

        return ParseSMSResponse(success=True, summary=summary, error=None)

    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Error")

# ──────────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn

    print('\n═══════════════════════════════════════════════════════')
    print('🚀 PesaPilot API')
    print('═══════════════════════════════════════════════════════')
    print(f'🔗 http://localhost:{WHATSAPP_API_PORT}')
    print(f'📊 Health: http://localhost:{WHATSAPP_API_PORT}/health')
    print('═══════════════════════════════════════════════════════\n')

    uvicorn.run(app, host='0.0.0.0', port=WHATSAPP_API_PORT, log_level='warning')