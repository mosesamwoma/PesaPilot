import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import threading
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal, Optional
from uuid import UUID

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import assistant, chart_generator
from src.analyzer import MpesaAnalyzer
from src.chat_common import daily_summary_text, period_summary_text
from src.security import (
    SlidingWindowLimiter, env_int, extract_token, install_log_redaction, load_api_token, token_matches,
)
from src.timeutil import now_nairobi

load_dotenv()

logging.basicConfig(level=logging.WARNING)
install_log_redaction()
logger = logging.getLogger(__name__)

WHATSAPP_API_PORT = int(os.getenv('WHATSAPP_API_PORT', 8000))
API_BIND = os.getenv('API_BIND_HOST', '127.0.0.1')

API_TOKEN = load_api_token()

MAX_QUESTION_CHARS = 2000
MAX_SMS_CHARS = 2000
MAX_BODY_BYTES = 32 * 1024

_auth_failures = SlidingWindowLimiter(env_int('API_AUTH_FAIL_LIMIT', 10), 300)
_request_limiter = SlidingWindowLimiter(env_int('API_RATE_LIMIT_PER_MIN', 120), 60)
_ai_limiter = SlidingWindowLimiter(env_int('API_AI_RATE_LIMIT_PER_MIN', 30), 60)

analyzer: Optional[MpesaAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_analyzer() -> MpesaAnalyzer:
    global analyzer
    if analyzer is None:
        with _analyzer_lock:
            if analyzer is None:
                analyzer = MpesaAnalyzer()
    return analyzer


def _too_many(limiter: SlidingWindowLimiter, key: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many requests",
        headers={"Retry-After": str(limiter.retry_after(key))},
    )


def require_api_key(request: Request) -> None:
    client = request.client.host if request.client else 'unknown'
    if token_matches(extract_token(request.headers), API_TOKEN):
        if not _request_limiter.hit('all'):
            raise _too_many(_request_limiter, 'all')
        return
    if _auth_failures.blocked(client):
        raise _too_many(_auth_failures, client)
    _auth_failures.hit(client)
    logger.warning("Rejected API request with a missing or wrong token from %s", client)
    raise HTTPException(
        status_code=401,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )


def limit_ai_calls() -> None:
    if not _ai_limiter.hit('all'):
        raise _too_many(_ai_limiter, 'all')


class QuestionRequest(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS)


class AnalysisResponse(BaseModel):
    question: str
    analysis: str
    error: Optional[str] = None
    chart: Optional[str] = None


class ParseSMSRequest(BaseModel):
    sms_content: str = Field(max_length=MAX_SMS_CHARS)


class ParseSMSResponse(BaseModel):
    success: bool
    summary: str
    error: Optional[str] = None


class SetBudgetRequest(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    limit_amount: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    period: str = Field('monthly', max_length=10)
    alert_threshold_pct: int = Field(80, ge=1, le=100)


class BudgetAlertsResponse(BaseModel):
    alerts: list
    count: int


class BudgetAlertAck(BaseModel):
    budget_id: UUID
    period_start: date
    alert_level: Literal['warning', 'over']
    amount_spent: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)


def is_valid_mpesa_sms(text: str) -> bool:
    text_upper = text.upper()
    return any(x in text_upper for x in ['KSH', 'KESH', 'MPESA', 'M-PESA', 'CONFIRMED'])


def generate_daily_summary() -> str:
    try:
        return daily_summary_text(get_analyzer().db.get_today_summary())
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return "Could not generate summary. Please try again."


def generate_period_summary(kind: str) -> str:
    return period_summary_text(get_analyzer().get_period_report(kind), kind)


def period_summary_response(kind: str) -> dict:
    try:
        return {"summary": generate_period_summary(kind)}
    except Exception as e:
        logger.error(f"{kind} summary error: {e}")
        raise HTTPException(status_code=503, detail="Summary unavailable") from e


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if API_BIND not in ('127.0.0.1', 'localhost', '::1'):
        logger.warning(
            "API is listening on %s. Keep the published port on loopback or behind a reverse proxy "
            "with TLS; every route except /health requires API_TOKEN.", API_BIND,
        )
    get_analyzer()
    yield


app = FastAPI(
    title="PesaPilot API", version="1.4", lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
router = APIRouter(dependencies=[Depends(require_api_key)])


class BodyLimitMiddleware:
    def __init__(self, asgi_app, max_bytes: int):
        self.asgi_app = asgi_app
        self.max_bytes = max_bytes

    async def _reject(self, send) -> None:
        body = b'{"detail":"Request body too large"}'
        await send({
            'type': 'http.response.start', 'status': 413,
            'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())],
        })
        await send({'type': 'http.response.body', 'body': body})

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.asgi_app(scope, receive, send)
            return
        for name, value in scope.get('headers', []):
            if name == b'content-length':
                try:
                    too_big = int(value) > self.max_bytes
                except ValueError:
                    too_big = True
                if too_big:
                    await self._reject(send)
                    return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > self.max_bytes:
                    raise HTTPException(status_code=413, detail="Request body too large")
            return message

        await self.asgi_app(scope, limited_receive, send)


app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

_cors_origins = [o.strip() for o in os.getenv('CORS_ORIGINS', '').split(',') if o.strip()]

if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )


@router.get("/daily-summary")
def daily_summary():
    return {"summary": generate_daily_summary()}


@router.get("/weekly-summary")
def weekly_summary():
    return period_summary_response("weekly")


@router.get("/monthly-summary")
def monthly_summary():
    return period_summary_response("monthly")


@router.get("/budget-check", response_model=BudgetAlertsResponse, dependencies=[Depends(limit_ai_calls)])
def budget_check():
    try:
        alerts = get_analyzer().get_pending_budget_alerts()
        return BudgetAlertsResponse(alerts=alerts, count=len(alerts))
    except Exception as e:
        logger.error(f"budget_check endpoint error: {e}")
        return BudgetAlertsResponse(alerts=[], count=0)


@router.post("/budget-alerts/ack")
def budget_alert_ack(request: BudgetAlertAck):
    recorded = get_analyzer().acknowledge_budget_alert(
        str(request.budget_id), request.period_start.isoformat(), request.alert_level, request.amount_spent
    )
    if not recorded:
        raise HTTPException(status_code=409, detail="Alert could not be recorded")
    return {"success": True}


@router.get("/budgets")
def list_budgets():
    return {"budgets": get_analyzer().get_budgets_overview()}


@router.post("/budgets")
def create_budget(request: SetBudgetRequest):
    result = get_analyzer().set_budget(
        category=request.category,
        limit_amount=request.limit_amount,
        period=request.period,
        alert_threshold_pct=request.alert_threshold_pct,
    )
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Could not save budget'))
    return result


@router.get("/anomalies", dependencies=[Depends(limit_ai_calls)])
def list_anomalies(days: int = Query(90, ge=1, le=1000)):
    return get_analyzer().get_smart_anomalies(days=days, force_refresh=False)


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": now_nairobi().isoformat()}


@router.get("/ready")
def ready():
    db_ok = get_analyzer().db.ping()
    if not db_ok:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ready"}


@router.post("/ask", response_model=AnalysisResponse, dependencies=[Depends(limit_ai_calls)])
def ask_question(request: QuestionRequest):
    question = request.question.strip()
    if not question or len(question) > 500 or len(question) < 2:
        raise HTTPException(status_code=400, detail="Question too short (2-500 chars)")
    try:
        reply = assistant.answer(get_analyzer(), question, dark=False, dashboard=False)
    except Exception as e:
        logger.exception("Server error in /ask")
        raise HTTPException(status_code=500, detail="Internal server error") from e

    if reply.intent == 'blocked':
        raise HTTPException(status_code=403, detail="Invalid question")
    chart = chart_generator.figure_to_base64(reply.fig) if reply.fig is not None else None
    return AnalysisResponse(question=request.question, analysis=reply.text, chart=chart, error=reply.error)


@router.post("/parse-sms", response_model=ParseSMSResponse)
def parse_sms(request: ParseSMSRequest):
    try:
        sms_content = request.sms_content.strip()

        if not sms_content:
            raise HTTPException(status_code=400, detail="SMS content required")

        if not is_valid_mpesa_sms(sms_content):
            return ParseSMSResponse(success=False, summary="Not an M-Pesa SMS")

        result = get_analyzer().parse_and_insert_sms(sms_content)

        if result.get('success'):
            return ParseSMSResponse(
                success=True,
                summary=result.get('summary', 'SMS parsed successfully'),
            )
        if result.get('summary'):
            return ParseSMSResponse(success=False, summary=result['summary'], error=result.get('error'))
        return ParseSMSResponse(
            success=False,
            summary=f"{result.get('error', 'Could not parse SMS')}",
            error=result.get('error'),
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("SMS parse error")
        return ParseSMSResponse(success=False, summary="Could not process that SMS. Please try again.")


app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, host=API_BIND, port=WHATSAPP_API_PORT, log_level="warning",
        server_header=False, timeout_keep_alive=5, limit_concurrency=64, timeout_graceful_shutdown=10,
    )
