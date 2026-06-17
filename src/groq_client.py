# src/groq_client.py
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
        self.model = os.getenv('LLM_MODEL', 'llama3-70b-8192')
        self.temperature = float(os.getenv('LLM_TEMPERATURE', 0.3))
        self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', 1000))

    def _chat(self, system: str, user: str) -> str:
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
        system = f"""You are a PostgreSQL expert. Generate a single SQL SELECT query to answer the user's question about M-Pesa transactions.

Schema:
{schema}

Rules:
- Return ONLY the SQL query, no explanation, no markdown, no backticks
- Use proper PostgreSQL syntax
- Always filter to recent data (last 90 days) unless specified
- For spending questions, exclude type = 'credit'
- For income questions, use type = 'credit'
- Limit results to 100 rows unless aggregating
- Use ILIKE for text searches"""

        sql = self._chat(system, question)
        # Strip any accidental markdown
        sql = sql.replace('```sql', '').replace('```', '').strip()
        return sql

    def analyze_results(self, question: str, sql: str, results: list) -> str:
        system = """You are PesaPilot, a friendly M-Pesa financial advisor for Kenyans.
Analyze the query results and give clear, actionable insights.
Use KES currency. Be concise (max 200 words). Give specific numbers. End with one actionable tip."""

        user = f"""Question: {question}
SQL: {sql}
Results: {results[:50]}"""

        return self._chat(system, user)

    def generate_insights(self, summary: dict) -> str:
        system = """You are PesaPilot, a friendly M-Pesa financial advisor for Kenyans.
Generate 3-5 key financial insights from the user's transaction summary.
Use KES currency. Be specific with numbers. Give actionable recommendations.
Format as bullet points."""

        user = f"Transaction summary: {summary}"
        return self._chat(system, user)

    def chat(self, question: str, context: str = "") -> str:
        system = """You are PesaPilot, an AI financial assistant for M-Pesa users in Kenya.
You help users understand their spending habits and improve their finances.
Be friendly, concise, and specific. Use KES currency."""

        user = f"{context}\n\nUser question: {question}" if context else question
        return self._chat(system, user)