# src/groq_client.py
import os
import re
import hashlib
import logging
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

KENYA_SYSTEM_PROMPT = """You are PesaPilot — a sharp, warm, street-smart Kenyan financial advisor who lives inside M-Pesa statements. You talk like a trusted friend who happens to be excellent with money: relaxed, encouraging, never preachy, never judgmental.

CONTEXT YOU UNDERSTAND DEEPLY:
- M-Pesa (sending, paying, withdrawing, Lipa Na M-Pesa, till numbers, paybill)
- Saccos (savings & credit cooperatives — dividends, share capital, BOSA/FOSA loans)
- Money Market Funds (MMF) — e.g. unit trusts from firms like Sanlam, CIC, Britam, Old Mutual, NCBA, Madison — typically 9-15% annual returns, withdrawable in 1-3 days
- Treasury Bills/Bonds via CBK (91/182/364-day T-bills, infrastructure bonds) — government-backed, currently competitive double-digit yields
- KPLC tokens, school fees cycles, matatu/fare costs, chama contributions
- Typical Kenyan income brackets and cost-of-living realities (rent, fare, food, fees, family obligations/\"black tax\")

HOW YOU RESPOND — 7 RULES:
1. SHOW THE FULL PICTURE — always pair amounts with percentages (e.g. "KES 8,400 on food — that's 32% of your spending").
2. COMPARE TO AVERAGES — benchmark against the user's own average, a sensible budget rule (e.g. 50/30/20), or what's reasonable for that category.
3. GIVE ACTIONABLE TIPS — at least one specific, doable next step, not vague advice like "spend less."
4. REFERENCE KENYAN OPTIONS — when relevant, mention Saccos, Money Market Funds, or Treasury Bills (T-bills) as concrete places to grow savings. Never mention Fuliza or recommend a specific bank/account name — keep it generic ("a Money Market Fund", "your local Sacco").
5. RECOMMEND BUDGETS — suggest simple, practical splits (e.g. needs/wants/savings) sized to their actual numbers.
6. ENCOURAGE EMERGENCY FUNDS — gently nudge toward building 1-3 months of expenses in something liquid like an MMF.
7. CELEBRATE SMALL WINS — if spending dropped, savings rose, or a habit improved, say so warmly before suggesting more.

STYLE RULES:
- Use KES with commas (e.g. KES 12,500).
- Keep jargon out — explain simply, no database/technical language ever.
- Be concise but complete: prioritize the 2-3 most useful insights over an exhaustive list.
- Tone: warm, encouraging, like a knowledgeable friend — never condescending or robotic.
- End most answers with one clear, practical next step.
- USE EMOJIS naturally to boost engagement — 3 to 6 per response, placed next to the idea they reinforce, never stacked in rows and never one per line. Suggested palette (pick what fits, don't force all of them):
  💰 money/amounts · 📊 spending breakdowns · 📈 increasing trend · 📉 decreasing trend
  ✅ wins/good habits · ⚠️ caution/overspending · 💡 tips · 🎯 goals/targets
  🏦 Sacco · 📌 T-Bills/Bonds · 🌱 growing savings · 🔥 streaks · 👏 celebration
- Every response should open with one emoji that sets the tone and close with one emoji next to the final next-step line.
"""

# ─────────────────────────────────────────────────────────────
# Simple in-memory cache
# ─────────────────────────────────────────────────────────────
class _ResponseCache:
    """
    Lightweight TTL cache keyed on a SHA-256 hash of (system, user).

    TTL buckets (seconds):
      - SQL generation       →  1 hour   (schema never changes mid-session)
      - Insights / summary   →  10 min   (data changes only when new SMS is added)
      - Budget / investment  →  15 min   (advice is stable over a session)
      - General chat         →  5 min    (conversational — shorter freshness)
    """

    def __init__(self):
        self._store: dict = {}   # key → {'response': str, 'expires_at': float}

    @staticmethod
    def _key(system: str, user: str) -> str:
        raw = f"{system}||{user}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, system: str, user: str):
        key = self._key(system, user)
        entry = self._store.get(key)
        if entry and time.time() < entry['expires_at']:
            logger.debug(f"Cache HIT  [{key[:12]}]")
            return entry['response']
        if entry:
            logger.debug(f"Cache MISS (expired) [{key[:12]}]")
            del self._store[key]
        return None

    def set(self, system: str, user: str, response: str, ttl: int):
        key = self._key(system, user)
        self._store[key] = {
            'response':   response,
            'expires_at': time.time() + ttl,
        }
        logger.debug(f"Cache SET  [{key[:12]}] ttl={ttl}s")

    def clear(self):
        self._store.clear()
        logger.info("Cache cleared")

    @property
    def size(self) -> int:
        # Prune expired entries while we're here
        now = time.time()
        self._store = {k: v for k, v in self._store.items() if now < v['expires_at']}
        return len(self._store)


# Module-level singleton — shared across all GroqClient instances
_cache = _ResponseCache()


# ─────────────────────────────────────────────────────────────
# TTL constants (seconds)
# ─────────────────────────────────────────────────────────────
TTL_SQL        = 3600   # 1 hour  — SQL for the same question won't change
TTL_INSIGHTS   =  600   # 10 min  — dashboard insights
TTL_ADVICE     =  900   # 15 min  — budget / investment advice
TTL_CHAT       =  300   #  5 min  — general conversational answers


# ─────────────────────────────────────────────────────────────
# SQL safety guard (defense-in-depth for LLM-generated SQL)
# ─────────────────────────────────────────────────────────────
_FORBIDDEN_SQL_KEYWORDS = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|'
    r'EXEC|EXECUTE|CREATE|ATTACH|REPLACE|MERGE|CALL)\b',
    re.IGNORECASE
)


def is_safe_select_sql(sql: str) -> bool:
    """Cheap guard before any LLM-generated SQL touches the DB.

    Checks:
      - Non-empty, starts with SELECT
      - No stacked statements (a stray ';' before the end)
      - No DDL/DML keywords (DROP, DELETE, UPDATE, INSERT, ALTER, ...)

    This is a belt-and-suspenders check, not a substitute for running
    queries against a read-only DB role/user.
    """
    if not sql:
        return False
    cleaned = sql.strip()
    if not cleaned.upper().startswith('SELECT'):
        return False
    body = cleaned.rstrip(';').strip()
    if ';' in body:                          # stacked statements
        return False
    if _FORBIDDEN_SQL_KEYWORDS.search(body):
        return False
    return True


class GroqClient:
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY must be set")
        self.client = Groq(api_key=api_key)

        # Two model tiers:
        #   FAST  -> chat / generate_insights (speed matters, lower stakes)
        #   SMART -> budget_plan / investment_advice / analyze_results / generate_sql
        #            (numeric reasoning + advice quality matters more than latency)
        self.model_fast = os.getenv('LLM_MODEL_FAST', 'llama-3.1-8b-instant')
        self.model_smart = os.getenv('LLM_MODEL_SMART', 'llama-3.3-70b-versatile')

        # Back-compat: if someone still sets LLM_MODEL, use it as the fast default
        legacy = os.getenv('LLM_MODEL')
        if legacy:
            self.model_fast = legacy

        self.temperature = float(os.getenv('LLM_TEMPERATURE', 0.6))
        self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', 600))

    # ------------------------------------------------------------------
    # Internal: raw API call (no caching here — callers decide TTL)
    # ------------------------------------------------------------------
    def _chat(self, system: str, user: str, model: str = None, timeout: int = 20) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=model or self.model_fast,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user},
                ]
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API error (model={model or self.model_fast}): {e}")
            return ""

    # ------------------------------------------------------------------
    # Internal: cache-aware wrapper
    # ------------------------------------------------------------------
    def _cached_chat(self, system: str, user: str, ttl: int, model: str = None) -> str:
        cached = _cache.get(system, user)
        if cached is not None:
            return cached
        response = self._chat(system, user, model=model)
        if response:                          # only cache successful responses
            _cache.set(system, user, response, ttl=ttl)
        return response

    # ------------------------------------------------------------------
    # Public: cache invalidation (call after inserting new transactions)
    # ------------------------------------------------------------------
    @staticmethod
    def invalidate_cache():
        """Clear all cached responses. Call whenever new transactions are added."""
        _cache.clear()

    @staticmethod
    def cache_size() -> int:
        """Return number of live (non-expired) cache entries."""
        return _cache.size

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------
    def generate_sql(self, question: str, schema: str) -> str:
        system = f"""You are a PostgreSQL expert. Generate ONE SQL SELECT query.

Schema:
{schema}

Rules:
- Return ONLY SQL, no markdown
- Filter to last 90 days
- Exclude type='credit' for spending
- Limit 100 rows"""
        sql = self._cached_chat(system, question, ttl=TTL_SQL, model=self.model_smart)
        sql = sql.replace('```sql', '').replace('```', '').strip()

        if not is_safe_select_sql(sql):
            logger.warning(f"Rejected unsafe/invalid SQL from LLM: {sql!r}")
            return ""

        return sql

    def analyze_results(self, question: str, sql: str, aggregates: dict, context: str = "") -> str:
        """Explain query results using Python-computed aggregates (sums/avgs/counts),
        never raw rows — keeps the LLM from doing arithmetic over dumped data."""
        system = KENYA_SYSTEM_PROMPT + """

You are answering a question backed by pre-computed aggregate numbers from real transaction data (already summed/averaged/counted in Python — trust these numbers exactly, do not recompute or estimate them yourself). Ground your answer strictly in the numbers given. Apply Rules 1-7. Max 180 words."""
        user_parts = []
        if context:
            user_parts.append(f"Financial context:\n{context}")
        user_parts.append(f"Question: {question}")
        user_parts.append(f"Aggregated results: {aggregates}")
        user = "\n\n".join(user_parts)
        return self._cached_chat(system, user, ttl=TTL_CHAT, model=self.model_smart)

    def generate_insights(self, summary: dict, extra_context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

Generate 3-4 punchy financial insights for the dashboard. Apply Rules 1-7. Be specific with numbers and percentages. Keep each insight to 1-2 sentences. Use bullet points."""
        user = f"Summary: {summary}"
        if extra_context:
            user += f"\n\nAdditional context:\n{extra_context}"
        return self._cached_chat(system, user, ttl=TTL_INSIGHTS, model=self.model_fast)

    def chat(self, question: str, context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

Answer the user's question conversationally and helpfully. Apply Rules 1-7 wherever the context supports it — don't invent numbers you weren't given. Max 200 words."""
        user = f"Financial context:\n{context}\n\nQuestion: {question}" if context else question
        return self._cached_chat(system, user, ttl=TTL_CHAT, model=self.model_fast)

    def budget_plan(self, context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

The user wants a concrete budget plan. Using their real spending context if given (or sensible Kenyan defaults if not), produce:
1. A short read of their current spending split (amounts + %).
2. A recommended budget split sized to their actual income/spend numbers — use a 50/30/20 style frame (needs/wants/savings) adapted to their reality, with KES amounts per bucket, not just percentages.
3. One specific category to trim and by how much (KES).
4. One concrete place to put the savings bucket (Sacco, MMF, or T-Bill) with a rough expected return.
Apply Rules 1-7. Max 220 words. Use headers/bullets, no SQL/database language."""
        user = f"Financial context:\n{context}" if context else "No transaction context available — give a general but practical Kenyan budget framework, and ask one clarifying question about their income at the end."
        return self._cached_chat(system, user, ttl=TTL_ADVICE, model=self.model_smart)

    def investment_advice(self, context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

The user is asking where to invest or grow savings. Using their real financial context if given:
1. State how much they realistically have available to invest/save (from net flow or balance), with the % of income that represents.
2. Recommend 2-3 concrete Kenyan options matched to their amount and likely time horizon — e.g. Money Market Fund for liquidity/emergency fund, Treasury Bills/Bonds for fixed, longer-term safety, a Sacco for disciplined saving + dividends/loan access. Give rough indicative return ranges, framed as approximate, not guaranteed.
3. Suggest a simple split across these (e.g. percentages) rather than picking just one.
4. End with one encouraging, concrete next step they can do this week.
Never mention Fuliza or name a specific bank/provider. Apply Rules 1-7. Max 220 words. No database/SQL language."""
        user = f"Financial context:\n{context}" if context else "No transaction context available — ask one quick question about their monthly surplus, then give a general Kenyan investment framework (MMF, T-Bills, Sacco) anyway."
        return self._cached_chat(system, user, ttl=TTL_ADVICE, model=self.model_smart)

    # ── FORECAST (NEW) ─────────────────────────────────────────────────────
    def generate_forecast_insights(self, forecast_data: dict) -> str:
        """Turn a Prophet forecast result (see src/forecasting.py) into a short,
        plain-English explanation — clearly framed as a projection, not a fact."""
        horizon = forecast_data.get('horizon_days', 7)
        system = KENYA_SYSTEM_PROMPT + f"""

You are explaining a {horizon}-day spending FORECAST produced by a statistical model — a projection, not something that has already happened. Apply Rules 1-7 wherever they fit. Clearly frame the numbers as predictions ("you're on track to..."), not historical fact. Explain the trend and risk level in plain language, and end with one practical next step tied to the projected risk level. Max 150 words. No database/SQL/model/technical language — never mention Prophet, confidence intervals, or statistics by name."""
        user = (
            f"Forecast horizon: {horizon} days\n"
            f"Historical average daily spend: KES {forecast_data.get('historical_avg_daily', 0):,.0f}\n"
            f"Total predicted spend for this period: KES {forecast_data.get('total_predicted', 0):,.0f}\n"
            f"Average predicted daily spend: KES {forecast_data.get('avg_predicted_daily', 0):,.0f}\n"
            f"Trend: {forecast_data.get('trend', 'Stable')}\n"
            f"Risk level: {forecast_data.get('risk_level', 'Low')}\n"
            f"Based on {forecast_data.get('history_days', 0)} days of transaction history."
        )
        return self._cached_chat(system, user, ttl=TTL_INSIGHTS, model=self.model_fast)
    # ── END FORECAST ───────────────────────────────────────────────────────