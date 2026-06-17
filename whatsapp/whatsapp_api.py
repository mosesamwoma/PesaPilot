# whatsapp_api.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import logging
from dotenv import load_dotenv
from src.analyzer import MpesaAnalyzer

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# FastAPI Setup
# ──────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PesaPilot WhatsApp API",
    version="1.0",
    description="M-Pesa financial assistant via WhatsApp"
)

analyzer = MpesaAnalyzer()

# ──────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str

class AnalysisResponse(BaseModel):
    question: str
    analysis: str
    sql: str = None
    error: str = None

# ──────────────────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "PesaPilot WhatsApp API",
        "version": "1.0"
    }

# ──────────────────────────────────────────────────────────────────────────
# Ask Question Endpoint
# ──────────────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AnalysisResponse)
async def ask_question(request: QuestionRequest):
    """
    Process a natural language question about M-Pesa transactions.
    
    Example:
        POST /ask
        {
            "question": "What did I spend on food this month?"
        }
    """
    try:
        if not request.question or len(request.question.strip()) < 2:
            raise HTTPException(status_code=400, detail="Question too short")

        logger.info(f"📨 Question: {request.question}")

        # Special commands
        question_lower = request.question.lower().strip()

        if question_lower == 'help':
            return AnalysisResponse(
                question=request.question,
                analysis="""🤖 PesaPilot WhatsApp Assistant

Ask me anything about your M-Pesa transactions:
- "What did I spend on food this month?"
- "How much did I send to Safaricom?"
- "What are my top 5 expenses?"
- "Compare this week vs last week"
- "Which day do I spend the most?"
- "Show me anomalies"
- "Summary"

I analyze your M-Pesa history and give you insights powered by AI."""
            )

        if question_lower == 'summary':
            summary = analyzer.db.get_summary()
            if summary:
                analysis = f"""📊 Your M-Pesa Summary

💰 Total Transactions: {summary.get('total_transactions', 0)}
💸 Total Spent: KES {summary.get('total_spent', 0):,.0f}
💵 Total Received: KES {summary.get('total_received', 0):,.0f}
📈 Average Spend: KES {summary.get('avg_spend', 0):,.0f}
🔄 Debits: {summary.get('debit_count', 0)}
📥 Credits: {summary.get('credit_count', 0)}"""
            else:
                analysis = "No transaction data found. Load your M-Pesa backup first."
            
            return AnalysisResponse(
                question=request.question,
                analysis=analysis
            )

        # Regular AI question
        result = analyzer.ask_question(request.question)

        logger.info(f"✅ Response generated")
        logger.info(f"SQL: {result.get('sql', 'N/A')[:100]}")

        return AnalysisResponse(
            question=result['question'],
            analysis=result['analysis'],
            sql=result.get('sql'),
            error=result.get('error')
        )

    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────────────────────────────────
# Dashboard Data Endpoint (Optional)
# ──────────────────────────────────────────────────────────────────────────

@app.get("/dashboard")
async def get_dashboard():
    """Get dashboard data for WhatsApp display"""
    try:
        data = analyzer.get_dashboard_data(days=30)
        return data
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ──────────────────────────────────────────────────────────────────────────
# Run Server (Local Testing)
# ──────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')