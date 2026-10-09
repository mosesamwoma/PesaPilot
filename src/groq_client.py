import os
import hashlib
import logging
import time
from typing import Optional
from groq import Groq
from dotenv import load_dotenv

from src.sql_guard import is_safe_select_sql
from src.timeutil import now_nairobi

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
- Use emojis sparingly: at most 2 per response, only where they add meaning, never stacked and never one per line.
"""

class _ResponseCache:

    def __init__(self):
        self._store: dict = {}

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
        now = time.time()
        self._store = {k: v for k, v in self._store.items() if now < v['expires_at']}
        return len(self._store)


_cache = _ResponseCache()


TTL_SQL        = 3600
TTL_INSIGHTS   =  600
TTL_ADVICE     =  900
TTL_CHAT       =  300


class GroqClient:
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY must be set")
        self.client = Groq(api_key=api_key)

        self.model_fast = os.getenv('LLM_MODEL_FAST', 'openai/gpt-oss-20b')
        self.model_smart = os.getenv('LLM_MODEL_SMART', 'openai/gpt-oss-120b')

        legacy = os.getenv('LLM_MODEL')
        if legacy:
            self.model_fast = legacy

        self.temperature = float(os.getenv('LLM_TEMPERATURE', 0.6))

        self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', 1536))
        self.reasoning_effort = os.getenv('LLM_REASONING_EFFORT', 'low')
        self.timeout = int(os.getenv('API_TIMEOUT', 20))

    def _chat(self, system: str, user: str, model: Optional[str] = None, timeout: Optional[int] = None,
              max_tokens: Optional[int] = None) -> str:
        resolved_model = model or self.model_fast
        resolved_timeout = timeout if timeout is not None else self.timeout
        try:
            kwargs = {}
            if 'gpt-oss' in resolved_model.lower():
                kwargs['reasoning_effort'] = self.reasoning_effort
            resp = self.client.chat.completions.create(
                model=resolved_model,
                temperature=self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                timeout=resolved_timeout,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user',   'content': user},
                ],
                **kwargs,
            )
            choice = resp.choices[0]
            content = (choice.message.content or "").strip()

            if choice.finish_reason == 'length':
                logger.warning(
                    f"Groq response TRUNCATED (finish_reason=length, "
                    f"model={resolved_model}, max_tokens={max_tokens or self.max_tokens}, "
                    f"chars_returned={len(content)})"
                )

            return content
        except Exception as e:
            logger.error(f"Groq API error (model={resolved_model}, timeout={resolved_timeout}): {e}")
            return ""

    def _cached_chat(self, system: str, user: str, ttl: int, model: Optional[str] = None,
                      max_tokens: Optional[int] = None) -> str:
        cached = _cache.get(system, user)
        if cached is not None:
            return cached
        response = self._chat(system, user, model=model, max_tokens=max_tokens)
        if response:
            _cache.set(system, user, response, ttl=ttl)
        return response

    @staticmethod
    def invalidate_cache():
        _cache.clear()

    @staticmethod
    def cache_size() -> int:
        return _cache.size

    def generate_sql(self, question: str, schema: str, days: Optional[int] = None,
                      row_limit: Optional[int] = None) -> str:
        today = now_nairobi().strftime("%Y-%m-%d")
        if days is not None:
            date_rule = f"- Filter to the last {days} days from today ({today})"
        else:
            date_rule = (
                f"- Today is {today}. If the question names or implies a time range "
                '("last month", "this year", "in August", "August 2025", "last 7 days", '
                "\"Q1\", an explicit date range, etc.), resolve it yourself into a concrete "
                "WHERE clause on the timestamp column using real calendar dates computed from "
                "today — never guess or default to a year from your training data. A bare month "
                "name with no year means the most recent occurrence of that month (this year if "
                "it hasn't happened yet, otherwise last year). If the question gives no time "
                "reference at all, query the full transaction history with no date filter."
            )
        limit_rule = (
            f"- Limit {row_limit} rows" if row_limit is not None
            else "- Do not add an arbitrary LIMIT — return every matching row unless the question asks for a specific top-N"
        )
        system = f"""You are a PostgreSQL expert. Generate ONE SQL SELECT query.

Schema:
{schema}

Rules:
- Return ONLY SQL, no markdown, no comments, a single statement
{date_rule}
- Exclude type='credit' for spending
- Use only the tables, views and functions listed in the schema
{limit_rule}"""
        sql = self._cached_chat(system, question, ttl=TTL_SQL, model=self.model_smart)
        sql = sql.replace('```sql', '').replace('```', '').strip()

        if not is_safe_select_sql(sql):
            logger.warning(f"Rejected unsafe/invalid SQL from LLM: {sql!r}")
            return ""

        return sql

    def analyze_results(self, question: str, sql: str, aggregates: dict, context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

You are answering a question backed by pre-computed aggregate numbers from real transaction data (already summed/averaged/counted in Python — trust these numbers exactly, do not recompute or estimate them yourself). Ground your answer strictly in the numbers given. Apply Rules 1-7. Max 180 words."""
        user_parts = []
        if context:
            user_parts.append(f"Financial context:\n{context}")
        user_parts.append(f"Question: {question}")
        user_parts.append(f"Aggregated results: {aggregates}")
        user = "\n\n".join(user_parts)
        return self._cached_chat(system, user, ttl=TTL_CHAT, model=self.model_smart, max_tokens=1200)

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

    def generate_chart_spec(self, description: str, system_prompt: str) -> str:
        return self._cached_chat(system_prompt, description, ttl=TTL_CHAT, model=self.model_fast, max_tokens=400)

    def budget_plan(self, context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

The user wants a concrete budget plan. Using their real spending context if given (or sensible Kenyan defaults if not), produce:
1. A short read of their current spending split (amounts + %).
2. A recommended budget split sized to their actual income/spend numbers — use a 50/30/20 style frame (needs/wants/savings) adapted to their reality, with KES amounts per bucket, not just percentages.
3. One specific category to trim and by how much (KES).
4. One concrete place to put the savings bucket (Sacco, MMF, or T-Bill) with a rough expected return.
Apply Rules 1-7. Max 220 words. Use headers/bullets, no SQL/database language."""
        user = f"Financial context:\n{context}" if context else "No transaction context available — give a general but practical Kenyan budget framework, and ask one clarifying question about their income at the end."
        return self._cached_chat(system, user, ttl=TTL_ADVICE, model=self.model_smart, max_tokens=1800)

    def investment_advice(self, context: str = "") -> str:
        system = KENYA_SYSTEM_PROMPT + """

The user is asking where to invest or grow savings. Using their real financial context if given:
1. State how much they realistically have available to invest/save (from net flow or balance), with the % of income that represents.
2. Recommend 2-3 concrete Kenyan options matched to their amount and likely time horizon — e.g. Money Market Fund for liquidity/emergency fund, Treasury Bills/Bonds for fixed, longer-term safety, a Sacco for disciplined saving + dividends/loan access. Give rough indicative return ranges, framed as approximate, not guaranteed.
3. Suggest a simple split across these (e.g. percentages) rather than picking just one.
4. End with one encouraging, concrete next step they can do this week.
Never mention Fuliza or name a specific bank/provider. Apply Rules 1-7. Max 220 words. No database/SQL language."""
        user = f"Financial context:\n{context}" if context else "No transaction context available — ask one quick question about their monthly surplus, then give a general Kenyan investment framework (MMF, T-Bills, Sacco) anyway."
        return self._cached_chat(system, user, ttl=TTL_ADVICE, model=self.model_smart, max_tokens=1800)

    def generate_forecast_insights(self, forecast_data: dict) -> str:
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

    def generate_anomaly_insights(self, anomalies: list) -> str:
        if not anomalies:
            return ""
        system = KENYA_SYSTEM_PROMPT + """

You are explaining transactions an ML model flagged as unusual FOR THIS SPECIFIC USER compared to their own normal spending pattern in that same category — not compared to other people. Apply Rules 1-7 wherever they fit. For each item, name the amount, recipient/category, and briefly why it stands out relative to their usual pattern in that category. Don't be alarmist — some flagged transactions are perfectly legitimate one-offs (a big one-time purchase, a rare emergency). End with one practical next step (e.g. review it, or ignore if expected). Max 180 words. No database/SQL/model/technical language — never say "IsolationForest", "z-score", or "outlier model" by name."""
        lines = [
            f"KES {a.get('amount', 0):,.0f} to {a.get('recipient', 'Unknown')} "
            f"({a.get('merchant_category', 'other')}) on {a.get('timestamp', '')} "
            f"— unusualness score {a.get('score', 0)}"
            for a in anomalies[:6]
        ]
        user = "Flagged transactions:\n" + "\n".join(lines)
        return self._cached_chat(system, user, ttl=TTL_INSIGHTS, model=self.model_fast)

    def budget_alert_message(self, alert: dict) -> str:
        category = str(alert.get('category', 'this category')).title()
        spent = alert.get('amount_spent', 0)
        limit = alert.get('limit_amount', 0)
        pct = alert.get('pct_used', 0)
        level = alert.get('alert_level', 'warning')
        period = alert.get('period', 'monthly')

        system = KENYA_SYSTEM_PROMPT + """

You are sending a short, PROACTIVE, UNPROMPTED WhatsApp budget alert — the user did not ask for this right now, so respect their time. Apply Rules 1-7 where they fit but keep it SHORT: 2-4 sentences max, not a full breakdown. State the category, amount spent vs limit, and percentage clearly. If alert_level is 'over', be direct but not judgmental — suggest one concrete way to course-correct for the rest of the period. If alert_level is 'warning' (near budget), be encouraging — a friendly heads-up, not a scolding. End with one short next step. No headers, no bullet lists — just 2-4 warm sentences. Use at most ONE emoji in this message — a short unprompted ping shouldn't feel decorated."""
        user = (
            f"Category: {category}\n"
            f"Period: {period}\n"
            f"Spent so far: KES {spent:,.0f}\n"
            f"Budget limit: KES {limit:,.0f}\n"
            f"Percentage used: {pct}%\n"
            f"Alert level: {'OVER budget' if level == 'over' else 'Approaching budget limit'}"
        )
        result = self._cached_chat(system, user, ttl=TTL_CHAT, model=self.model_fast)
        if result:
            return result

        icon = "🚨" if level == "over" else "⚠️"
        verb = "gone over" if level == "over" else "is close to"
        return (
            f"{icon} Budget check: your {category} spending {verb} its {period} limit — "
            f"KES {spent:,.0f} of KES {limit:,.0f} ({pct}%)."
        )
