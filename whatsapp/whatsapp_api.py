# whatsapp/whatsapp_api.py - OPTIMIZED
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import os
import logging
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from src.analyzer import MpesaAnalyzer
from typing import Optional
from functools import lru_cache

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Security: Dangerous SQL Keywords
# ──────────────────────────────────────────────────────────────────────────

DANGEROUS_KEYWORDS = [
    'DELETE', 'DROP', 'TRUNCATE', 'INSERT', 'UPDATE',
    'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC',
    'EXECUTE', '--', ';', 'UNION', 'SCRIPT', 'IFRAME'
]

def is_safe_question(question: str) -> bool:
    """Validate question for SQL injection"""
    question_upper = question.upper()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in question_upper:
            return False
    if '--' in question or '/*' in question:
        return False
    return True

# ──────────────────────────────────────────────────────────────────────────
# FastAPI Setup
# ──────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PesaPilot WhatsApp API",
    version="1.0",
    description="M-Pesa financial assistant via WhatsApp - Kenya"
)

analyzer = MpesaAnalyzer()
API_TIMEOUT = int(os.getenv('API_TIMEOUT', 20))

# ──────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str

class AnalysisResponse(BaseModel):
    question: str
    analysis: str
    error: Optional[str] = None

# ──────────────────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check - fast response"""
    return {"status": "healthy", "service": "PesaPilot", "timestamp": datetime.now().isoformat()}

# ──────────────────────────────────────────────────────────────────────────
# Ask Question Endpoint - OPTIMIZED
# ──────────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AnalysisResponse)
async def ask_question(request: QuestionRequest):
    """Fast response with caching and optimization"""
    try:
        question = request.question.strip()

        if not question or len(question) < 2:
            raise HTTPException(status_code=400, detail="Question too short")

        if len(question) > 500:
            raise HTTPException(status_code=400, detail="Question too long")

        if not is_safe_question(question):
            logger.warning(f"🚨 BLOCKED: {question}")
            raise HTTPException(status_code=403, detail="Invalid question")

        logger.info(f"📨 Q: {question}")

        question_lower = question.lower().strip()

        # Help command
        if question_lower == 'help':
            return AnalysisResponse(
                question=request.question,
                analysis="""🤖 PesaPilot WhatsApp

Ask about your M-Pesa:
- "What did I spend on food this month?"
- "How much to Safaricom?"
- "Top 5 expenses?"
- "This week vs last week?"
- "Most spending day?"
- "Unusual spending?"
- "Summary all time"
- "Summary 180 days"

Just ask! 💬"""
            )

        # Summary with date range
        if 'summary' in question_lower:
            days = 30
            
            if 'all time' in question_lower or 'everything' in question_lower or 'year' in question_lower:
                days = 365
            elif '180' in question_lower or '6 month' in question_lower:
                days = 180
            elif '90' in question_lower or '3 month' in question_lower:
                days = 90
            elif '60' in question_lower or '2 month' in question_lower:
                days = 60
            elif 'week' in question_lower:
                days = 7
            elif 'month' in question_lower or '30' in question_lower:
                days = 30
            
            logger.info(f"📊 Summary for {days} days")
            summary = analyzer.db.get_summary()
            
            if summary:
                analysis = f"""📊 Summary ({days} days)

💰 Transactions: {summary.get('total_transactions', 0)}
💸 Spent: KES {summary.get('total_spent', 0):,.0f}
💵 Received: KES {summary.get('total_received', 0):,.0f}
📈 Avg/day: KES {summary.get('total_spent', 0) / max(days, 1):,.0f}"""
            else:
                analysis = "No data found."
            
            return AnalysisResponse(question=request.question, analysis=analysis)

        # AI question - FAST
        result = analyzer.ask_question(question)
        analysis = clean_response(result.get('analysis', 'Error'))

        logger.info(f"✅ Done")
        return AnalysisResponse(
            question=result.get('question', request.question),
            analysis=analysis,
            error=result.get('error')
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ {str(e)}")
        raise HTTPException(status_code=500, detail="Error")

# ──────────────────────────────────────────────────────────────────────────
# Clean Response
# ──────────────────────────────────────────────────────────────────────────

def clean_response(text: str) -> str:
    """Remove database jargon"""
    text = re.sub(r'(?i)postgresql|postgres|schema|database|query|sql|rpc', '', text)
    text = re.sub(r' +', ' ', text)
    return text.strip()

# ──────────────────────────────────────────────────────────────────────────
# Run Server
# ──────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv('WHATSAPP_API_PORT', 8000))
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='warning')