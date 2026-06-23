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

    def build_context_string(self, days: int = 30) -> str:
        """Build a rich, human-readable context block from current financial data
        so the AI has the full picture instead of just the raw question."""
        try:
            summary = self.db.get_summary() or {}
            category_data = self.db.get_spending_by_category(days=days) or []
            daily_trend = self.db.get_daily_trend(days=days) or []
            top_merchants = self.db.get_top_merchants(days=days, limit=5) or []
            anomalies = self.db.get_anomalies(days=days) or []

            total_spent = summary.get('total_spent', 0) or 0
            lines = []

            lines.append(
                f"Summary (last {days} days): {summary.get('total_transactions', 0)} transactions, "
                f"Total Spent KES {total_spent:,.0f}, "
                f"Total Received KES {summary.get('total_received', 0):,.0f}, "
                f"Balance KES {summary.get('balance', 0):,.0f}."
            )

            if category_data and total_spent > 0:
                cat_lines = []
                for c in sorted(category_data, key=lambda x: x.get('total_amount', 0), reverse=True)[:6]:
                    amt = c.get('total_amount', 0)
                    pct = (amt / total_spent * 100) if total_spent else 0
                    cat_lines.append(f"{c.get('merchant_category', 'Other')}: KES {amt:,.0f} ({pct:.1f}%)")
                lines.append("Top spending categories: " + "; ".join(cat_lines))

            if top_merchants:
                merch_lines = [
                    f"{m.get('recipient', 'Unknown')}: KES {m.get('total_amount', 0):,.0f}"
                    for m in top_merchants[:5]
                ]
                lines.append("Top merchants/recipients: " + "; ".join(merch_lines))

            if daily_trend:
                recent = daily_trend[-7:] if len(daily_trend) > 7 else daily_trend
                trend_lines = [f"{d.get('date')}: KES {d.get('total_spent', 0):,.0f}" for d in recent]
                lines.append("Recent daily spend: " + "; ".join(trend_lines))

            if anomalies:
                anom_lines = [
                    f"KES {a.get('amount', 0):,.0f} to {a.get('recipient', 'unknown')} on {a.get('timestamp', '')}"
                    for a in anomalies[:3]
                ]
                lines.append("Unusual transactions detected: " + "; ".join(anom_lines))

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"build_context_string failed: {e}")
            return ""

    def ask_question(self, question: str, days: int = 90) -> Dict:
        try:
            context = self.build_context_string(days=days)
            schema = self.db.get_schema()
            sql = self.groq.generate_sql(question, schema)
            logger.info(f"Generated SQL: {sql}")

            if not sql or not sql.upper().startswith('SELECT'):
                return {
                    'question': question,
                    'sql': sql,
                    'results': [],
                    'analysis': self.groq.chat(question, context=context),
                    'error': None,
                }

            results = self.db.execute_query(sql)
            analysis = self.groq.analyze_results(question, sql, results, context=context)

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
            context = self.build_context_string(days=days)
            insights = self.groq.generate_insights(summary, extra_context=context) if summary else ""

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