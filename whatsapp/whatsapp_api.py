# whatsapp/whatsapp_api.py - FIXED (No GZIPMiddleware)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import logging
import re
from datetime import datetime
from dotenv import load_dotenv
from src.analyzer import MpesaAnalyzer
from typing import Optional
import pandas as pd

load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────

WHATSAPP_PIN = os.getenv('WHATSAPP_PIN', '1234')
WHATSAPP_API_PORT = int(os.getenv('WHATSAPP_API_PORT', 8000))

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
    """Block only destructive SQL operations"""
    question_upper = question.upper()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in question_upper:
            return False
    if '--' in question or '/*' in question:
        return False
    return True

def is_valid_mpesa_sms(text: str) -> bool:
    """Validate M-Pesa SMS format"""
    text_upper = text.upper()
    return any(x in text_upper for x in ['KSH', 'KESH', 'MPESA', 'CONFIRMED'])

def clean_response(text: str) -> str:
    """Remove database jargon"""
    jargon = ['postgresql', 'postgres', 'schema', 'database', 'query', 'sql', 'rpc']
    for word in jargon:
        text = re.sub(word, '', text, flags=re.IGNORECASE)
    return re.sub(r' +', ' ', text).strip()

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
    """Health check"""
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
    """Ask question about M-Pesa transactions"""
    try:
        question = request.question.strip()

        if not question or len(question) < 2 or len(question) > 500:
            raise HTTPException(status_code=400, detail="Invalid question length")

        if not is_safe_question(question):
            logger.warning(f"🚨 BLOCKED: Destructive operation attempted")
            raise HTTPException(status_code=403, detail="Invalid query")

        logger.info(f"📨 Question: {question[:50]}")

        question_lower = question.lower().strip()

        # ─ HELP ─────────────────────────────────────────────────────────────
        if question_lower == 'help':
            help_text = """🤖 PesaPilot Assistant

💬 Ask about spending:
  • "What did I spend on food?"
  • "How much to Safaricom?"
  • "Top 5 expenses?"
  • "Unusual spending?"

📊 Reports:
  • "Summary" (30 days)
  • "Summary 90 days"
  • "Summary 180 days"
  • "Summary all time"

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
        logger.info(f"🔄 AI processing")
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
    """Parse and store M-Pesa SMS directly"""
    try:
        sms = request.sms_content.strip()

        if not sms or len(sms) < 20 or len(sms) > 1000:
            return ParseSMSResponse(
                success=False,
                summary="",
                error="Invalid SMS length"
            )

        if not is_valid_mpesa_sms(sms):
            return ParseSMSResponse(
                success=False,
                summary="",
                error="Not M-Pesa SMS"
            )

        logger.info(f"📝 Parsing SMS ({len(sms)} chars)")

        from src.parse_sms import MpesaParser

        parser = MpesaParser()
        tx = parser._parse_sms_text(sms)

        if not tx:
            return ParseSMSResponse(
                success=False,
                summary="",
                error="Could not parse SMS"
            )

        if not tx.get('transaction_id') or not tx.get('amount') or tx.get('amount') <= 0:
            return ParseSMSResponse(
                success=False,
                summary="",
                error="Missing required fields"
            )

        logger.info(f"💾 Storing: {tx.get('transaction_id')}")

        df = pd.DataFrame([tx])
        count = analyzer.db.insert_transactions(df)

        if count == 0:
            logger.warning(f"⚠️ Duplicate transaction")
            return ParseSMSResponse(
                success=False,
                summary="",
                error="Transaction already exists"
            )

        summary = f"""✅ Stored!

💰 Type: {tx.get('type', 'unknown').upper()}
📊 Amount: KES {tx.get('amount', 0):,.2f}
👤 To/From: {tx.get('recipient', 'Unknown')[:30]}
🏷️ Category: {tx.get('merchant_category', 'other')}
📅 Date: {tx.get('readable_date', 'N/A')}"""

        logger.info(f"✅ Stored: {tx.get('transaction_id')}")

        return ParseSMSResponse(
            success=True,
            summary=summary,
            error=None
        )

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