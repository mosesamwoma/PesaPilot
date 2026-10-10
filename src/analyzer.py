import logging
import time
from typing import Dict, List, Optional, Union, cast

import pandas as pd

from src.chat_common import normalize_category
from src.database import PostgresDB
from src.groq_client import GroqClient
from src.parse_sms import MpesaParser
from src.sql_guard import is_safe_select_sql
from src import forecasting
from src import anomaly_detector
from src import budget_monitor

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
VALID_PERIODS = ('weekly', 'monthly')


def _aggregate_query_results(results: List[Dict], top_group_limit: int = 8) -> Dict:
    if not results:
        return {"row_count": 0}

    sample = results[0]
    numeric_cols = [
        k for k, v in sample.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]

    agg: Dict = {"row_count": len(results)}

    for col in numeric_cols:
        vals: List[Union[int, float]] = [
            cast(Union[int, float], r.get(col))
            for r in results if isinstance(r.get(col), (int, float))
        ]
        if not vals:
            continue
        agg[col] = {
            "sum": round(sum(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "count": len(vals),
        }

    amount_col = 'amount' if 'amount' in numeric_cols else (numeric_cols[0] if numeric_cols else None)
    for group_col in ('merchant_category', 'recipient', 'type'):
        if group_col in sample and amount_col:
            totals: Dict = {}
            for r in results:
                key = r.get(group_col) or 'Unknown'
                val = r.get(amount_col)
                if isinstance(val, (int, float)):
                    totals[key] = totals.get(key, 0) + val
            if totals:
                ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_group_limit]
                agg[f"by_{group_col}"] = [
                    {"key": k, "total": round(v, 2)} for k, v in ranked
                ]
            break

    return agg


LLM_UNAVAILABLE_MESSAGE = "I couldn't reach the AI service just now. Please try again in a moment."


def _anomaly_fallback_text(anomalies: List[Dict], limit: int = 5) -> str:
    top = sorted(anomalies, key=lambda a: float(a.get('amount') or 0), reverse=True)[:limit]
    lines = [
        f"- KES {float(a.get('amount') or 0):,.0f} to {a.get('recipient', 'Unknown')} on {str(a.get('timestamp', ''))[:10]}"
        for a in top
    ]
    return f"{len(anomalies)} transaction(s) look unusual for their category. Largest:\n" + "\n".join(lines)


class MpesaAnalyzer:
    def __init__(self):
        self.db = PostgresDB()
        self.groq = GroqClient()
        self._cache: Dict = {}

    def _cache_get(self, key: str):
        entry = self._cache.get(key)
        if entry and time.time() - entry[0] < CACHE_TTL_SECONDS:
            return entry[1]
        self._cache.pop(key, None)
        return None

    def _cache_set(self, key: str, value) -> None:
        self._cache[key] = (time.time(), value)

    def clear_cache(self) -> None:
        self._cache.clear()

    def build_context_string(self, days: Optional[int] = None) -> str:
        try:
            summary = self.db.get_range_summary(days=days) or {}
            category_data = self.db.get_spending_by_category(days=days) or []
            daily_trend = self.db.get_daily_trend(days=days) or []
            top_merchants = self.db.get_top_merchants(days=days, limit=5) or []
            anomalies = self.db.get_anomalies(days=days) or []

            total_spent = summary.get('total_spent', 0) or 0
            total_cost = summary.get('total_transaction_cost', 0) or 0
            lines = []

            period_label = f"last {days} days" if days is not None else "full history"
            lines.append(
                f"Summary ({period_label}): {summary.get('total_transactions', 0)} transactions, "
                f"Total Spent KES {total_spent:,.0f}, "
                f"Total Received KES {summary.get('total_received', 0):,.0f}, "
                f"Balance KES {summary.get('balance', 0):,.0f}."
            )
            if total_cost > 0:
                cost_pct = (total_cost / total_spent * 100) if total_spent else 0
                lines.append(
                    f"M-Pesa transaction fees paid: KES {total_cost:,.0f}"
                    f" ({cost_pct:.1f}% of total spending) — this is money lost to charges, "
                    f"not to purchases, and is worth calling out separately when relevant."
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

    def ask_question(self, question: str, days: Optional[int] = None, row_limit: Optional[int] = None) -> Dict:
        try:
            context = self.build_context_string(days=days)
            schema = self.db.get_schema()
            sql = self.groq.generate_sql(question, schema, days=days, row_limit=row_limit)
            logger.info(f"Generated SQL: {sql}")

            if not is_safe_select_sql(sql):
                return {
                    'question': question,
                    'sql': sql,
                    'results': [],
                    'analysis': self.groq.chat(question, context=context) or LLM_UNAVAILABLE_MESSAGE,
                    'error': None,
                }

            results = self.db.execute_query(sql)
            aggregates = _aggregate_query_results(results)
            analysis = self.groq.analyze_results(question, sql, aggregates, context=context) or LLM_UNAVAILABLE_MESSAGE

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

    def get_dashboard_data(self, days: Optional[int] = None, force_refresh: bool = False) -> Dict:
        cache_key = f'dashboard_{days}'
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        try:
            summary = self.db.get_range_summary(days=days)
            category_spend = self.db.get_spending_by_category(days=days)
            daily_trend = self.db.get_daily_trend(days=days)
            anomalies = self.db.get_anomalies(days=days)
            top_merchants = self.db.get_top_merchants(days=days, limit=10)
            recent_txs = self.db.get_transactions(days=days, limit=None)
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
            self._cache_set(cache_key, data)
            return data
        except Exception as e:
            logger.error(f"get_dashboard_data failed: {e}")
            return {}

    def get_forecast(self, horizon_days: int = 7) -> Dict:
        try:
            transactions = self.db.get_transactions(days=forecasting.TRAIN_HISTORY_DAYS, limit=None)
            result = forecasting.generate_forecast(transactions, horizon_days=horizon_days)

            if not result.get('sufficient_data'):
                result['insight'] = result.get(
                    'message',
                    "I need a bit more transaction history before I can forecast your spending."
                )
                return result

            result['insight'] = self.groq.generate_forecast_insights(result)
            return result
        except Exception as e:
            logger.error(f"get_forecast failed: {e}")
            fallback_msg = "Could not generate a forecast right now. Please try again later."
            return {
                'sufficient_data': False,
                'history_days': 0,
                'min_required_days': forecasting.MIN_HISTORY_DAYS,
                'message': fallback_msg,
                'insight': fallback_msg,
            }

    def get_forecast_bundle(self) -> Dict:
        return {
            'horizon_7': self.get_forecast(horizon_days=7),
            'horizon_30': self.get_forecast(horizon_days=30),
        }

    def get_smart_anomalies(self, days: Optional[int] = None, force_refresh: bool = False) -> Dict:
        cache_key = f'smart_anomalies_{days}'
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        try:
            transactions = self.db.get_transactions(days=days, limit=None)

            baselines = anomaly_detector.compute_baselines(transactions)
            if baselines:
                self.db.save_spending_baselines(baselines)

            flagged = anomaly_detector.detect_anomalies(transactions)
            if flagged:
                self.db.save_anomalies(flagged)

            current_models = {str(a['transaction_id']): a.get('model') for a in flagged}
            saved = [
                a for a in self.db.get_saved_anomalies(days=days, limit=None)
                if current_models.get(str(a.get('tx_uuid'))) == a.get('model')
            ]
            insight = self.groq.generate_anomaly_insights(saved) if saved else ""
            if saved and not insight:
                insight = _anomaly_fallback_text(saved)

            result = {
                'anomalies': saved,
                'baselines': baselines,
                'count': len(saved),
                'insight': insight or "No unusual transactions detected in your recent spending — everything looks consistent with your normal pattern. ",
            }
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"get_smart_anomalies failed: {e}")
            return {
                'anomalies': [],
                'baselines': [],
                'count': 0,
                'insight': "Could not run anomaly detection right now. Please try again later.",
            }

    def set_budget(self, category: str, limit_amount: float, period: str = 'monthly',
                    alert_threshold_pct: int = 80) -> Dict:
        normalized = normalize_category(category)
        if normalized is None:
            return {'success': False, 'error': f"Unknown category '{category}'"}
        period = (period or 'monthly').strip().lower()
        if period not in VALID_PERIODS:
            return {'success': False, 'error': "Period must be 'weekly' or 'monthly'"}
        if not limit_amount or limit_amount <= 0:
            return {'success': False, 'error': 'Budget limit must be greater than 0'}
        if not 1 <= alert_threshold_pct <= 100:
            return {'success': False, 'error': 'Alert threshold must be between 1 and 100'}
        budget = self.db.upsert_budget(normalized, limit_amount, period, alert_threshold_pct)
        self._cache.clear()
        if not budget:
            return {'success': False, 'error': f"Could not save budget for {category}"}
        return {'success': True, 'budget': budget}

    def get_budgets_overview(self) -> List[Dict]:
        return self.db.get_budget_status()

    def check_budget_alerts(self) -> List[Dict]:
        try:
            status_rows = self.db.get_budget_status()
            if not status_rows:
                return []

            recent = self.db.get_recent_budget_alerts(since_days=45)
            already_alerted = {
                (r['budget_id'], r['period_start'], r['alert_level']) for r in recent
            }

            due = budget_monitor.evaluate_budgets(status_rows, already_alerted)
            if not due:
                return []

            results = []
            for alert in due:
                message = self.groq.budget_alert_message(alert)
                sent = self.db.record_budget_alert(
                    budget_id=alert['budget_id'],
                    period_start=alert['period_start'],
                    alert_level=alert['alert_level'],
                    amount_spent=alert['amount_spent'],
                )
                if sent:
                    results.append({
                        'category': alert['category'],
                        'alert_level': alert['alert_level'],
                        'message': message,
                    })
            return results
        except Exception as e:
            logger.error(f"check_budget_alerts failed: {e}")
            return []

    def generate_dynamic_chart(self, description: str, dark: bool = True) -> Dict:
        from src import chart_generator
        return chart_generator.generate_dynamic_chart(self, description, dark=dark)

    def parse_and_insert_sms(self, sms_content: str) -> Dict:
        parser = MpesaParser()
        tx = parser._parse_sms_text(sms_content)

        if not tx:
            return {'success': False, 'error': 'Could not parse SMS — unrecognised format'}

        tx_id = tx.get('transaction_id')
        if not tx_id:
            return {'success': False, 'error': 'No transaction ID found in SMS'}

        if self.db.transaction_exists(tx_id):
            return {
                'success': False,
                'error': 'duplicate',
                'summary': f"ℹ️ Transaction {tx_id} is already recorded.",
            }

        df = pd.DataFrame([tx])
        inserted = self.db.insert_transactions(df, overwrite=False)
        self._cache.clear()
        self.groq.invalidate_cache()
        forecasting.invalidate_cache()

        if inserted == 0:
            return {'success': False, 'error': 'Could not save transaction to the database'}

        tx_type = tx.get('type', 'debit')
        amount = tx.get('amount', 0) or 0
        recipient = tx.get('recipient', 'Unknown')
        balance = tx.get('balance', 0) or 0
        category = tx.get('merchant_category', 'other')
        cost = tx.get('transaction_cost') or 0

        if tx_type == 'credit':
            summary = (
                f"Money in KES {amount:,.2f}\n"
                f"From: {recipient}\n"
                f"Balance: KES {balance:,.2f}\n"
                f"Transaction ID: {tx_id}"
            )
        else:
            verb = {'withdrawal': 'Withdrew', 'airtime': 'Bought airtime for'}.get(tx_type, 'Paid')
            summary = (
                f"{verb} KES {amount:,.2f}\n"
                f"To: {recipient}\n"
                f"Category: {category.title()}\n"
                f"Fee: KES {cost:,.2f}\n"
                f"Balance: KES {balance:,.2f}\n"
                f"Transaction ID: {tx_id}"
            )

        return {'success': True, 'summary': summary, 'transaction': tx}

    def load_transactions(self, xml_path: str, csv_output: Optional[str] = None) -> int:
        parser = MpesaParser()
        df = parser.parse_xml_to_csv(xml_path, output_path=csv_output)
        if df.empty:
            logger.warning("No transactions to load")
            return 0
        count = self.db.insert_transactions(df)
        self._cache.clear()
        self.groq.invalidate_cache()
        forecasting.invalidate_cache()
        return count
