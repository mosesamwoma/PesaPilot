import os
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class GroqClient:
    def __init__(self):
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY must be set")
        self.client = Groq(api_key=api_key)
        self.model = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')
        self.temperature = float(os.getenv('LLM_TEMPERATURE', 0.6))  # Lower = faster
        self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', 500))  # Reduced from 1000

    def _chat(self, system: str, user: str, timeout: int = 20) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ]
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return ""

    def generate_sql(self, question: str, schema: str) -> str:
        system = f"""You are a PostgreSQL expert. Generate ONE SQL SELECT query.

Schema:
{schema}

Rules:
- Return ONLY SQL, no markdown
- Filter to last 90 days
- Exclude type='credit' for spending
- Limit 100 rows"""

        sql = self._chat(system, question)
        return sql.replace('```sql', '').replace('```', '').strip()

    def analyze_results(self, question: str, sql: str, results: list) -> str:
        system = """You are PesaPilot, M-Pesa financial advisor for Kenya.
Give clear insights. Use KES. Be concise (max 150 words). End with 1 actionable tip."""

        user = f"Question: {question}\nResults: {results[:20]}"
        return self._chat(system, user)

    def generate_insights(self, summary: dict) -> str:
        system = """You are PesaPilot. Generate 3-4 key financial insights.
Use KES. Be specific. Give actionable recommendations."""

        user = f"Summary: {summary}"
        return self._chat(system, user)

    def chat(self, question: str, context: str = "") -> str:
        system = """You are PesaPilot, M-Pesa financial assistant for Kenya.
Help users understand spending. Be friendly, concise, specific. Use KES."""

        user = f"{context}\n\nQuestion: {question}" if context else question
        return self._chat(system, user)