# src/analyzer.py
import logging
from typing import Dict, List, Optional
from src.database import SupabaseDB
from src.groq_client import GroqClient

logger = logging.getLogger(__name__)

class MpesaAnalyzer:
    def __init__(self):
        self.db = SupabaseDB()
        self.groq = GroqClient()
        self._cache: Dict = {}

    def ask_question(self, question: str) -> Dict:
        try:
            schema = self.db.get_schema()
            sql = self.groq.generate_sql(question, schema)
            logger.info(f"Generated SQL: {sql}")

            if not sql or not sql.upper().startswith('SELECT'):
                return {
                    'question': question,
                    'sql': sql,
                    'results': [],
                    'analysis': self.groq.chat(question),
                    'error': None,
                }

            results = self.db.execute_query(sql)
            analysis = self.groq.analyze_results(question, sql, results)

            return {
                'question': question,
                'sql': sql,
                'results': results,
                'analysis': analysis,
                'error': None,
            }
        except Exception as e:
            logger.error(f"ask_question failed: {e}")
            return {
                'question': question,
                'sql': '',
                'results': [],
                'analysis': f"Sorry, I couldn't process that question. Error: {str(e)}",
                'error': str(e),
            }

    def get_dashboard_data(self, days: int = 30, force_refresh: bool = False) -> Dict:
        cache_key = f'dashboard_{days}'
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        try:
            summary = self.db.get_summary()
            category_spend = self.db.get_spending_by_category(days=days)
            daily_trend = self.db.get_daily_trend(days=days)
            anomalies = self.db.get_anomalies()
            top_merchants = self.db.get_top_merchants(days=days)
            recent_txs = self.db.get_transactions(days=days, limit=50)
            insights = self.groq.generate_insights(summary) if summary else ""

            data = {
                'summary': summary,
                'spending_by_category': category_spend,
                'daily_trend': daily_trend,
                'anomalies': anomalies,
                'top_merchants': top_merchants,
                'recent_transactions': recent_txs,
                'insights': insights,
            }
            self._cache[cache_key] = data
            return data
        except Exception as e:
            logger.error(f"get_dashboard_data failed: {e}")
            return {}

    def load_transactions(self, xml_path: str, csv_output: str = None) -> int:
        from src.parse_sms import MpesaParser
        parser = MpesaParser()
        df = parser.parse_xml_to_csv(xml_path, output_path=csv_output)
        if df.empty:
            logger.warning("No transactions to load")
            return 0
        count = self.db.insert_transactions(df)
        self._cache.clear()
        return count