import logging
import math
import threading
import time
from datetime import date
from typing import Dict, List, Optional, Union, cast

import pandas as pd

from src.chat_common import normalize_category
from src.database import PostgresDB
from src.groq_client import GroqClient
from src.parse_sms import MpesaParser
from src.security import sanitize_for_prompt
from src.sql_guard import is_safe_select_sql
from src import forecasting
from src import anomaly_detector
from src import insights as insight_engine
from src import budget_monitor
from src.timeutil import report_window, since_nairobi, window_before

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 64
VALID_PERIODS = ('weekly', 'monthly')
MAX_BUDGET_LIMIT = 1_000_000_000
MAX_SQL_ATTEMPTS = 2
ANOMALY_HISTORY_DAYS = 730


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
                key = sanitize_for_prompt(r.get(group_col) or 'Unknown')
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
    top = anomalies[:limit]
    lines = []
    for a in top:
        why = (a.get('reasons') or ['unusual for this recipient or category'])[0]
        lines.append(f"- {str(a.get('timestamp', ''))[:10]}: {why}")
    return f"{len(anomalies)} transaction(s) look unusual against your own pattern. Most notable:\n" + "\n".join(lines)


class MpesaAnalyzer:
    def __init__(self):
        self.db = PostgresDB()
        self.groq = GroqClient()
        self._cache: Dict = {}
        self._cache_lock = threading.RLock()

    def _cache_get(self, key: str):
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry and time.time() - entry[0] < CACHE_TTL_SECONDS:
                return entry[1]
            self._cache.pop(key, None)
        return None

    def _cache_set(self, key: str, value) -> None:
        with self._cache_lock:
            if len(self._cache) >= CACHE_MAX_ENTRIES:
                now = time.time()
                self._cache = {k: v for k, v in self._cache.items() if now - v[0] < CACHE_TTL_SECONDS}
                while len(self._cache) >= CACHE_MAX_ENTRIES:
                    self._cache.pop(next(iter(self._cache)), None)
            self._cache[key] = (time.time(), value)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def get_frame(self, days: Optional[int] = None) -> pd.DataFrame:
        key = f'frame_{days}'
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        frame = self.db.get_frame(days=days)
        self._cache_set(key, frame)
        return frame

    def get_health(self) -> Dict:
        return insight_engine.financial_health(self.get_frame())

    def get_recurring(self, include_lapsed: bool = False) -> List[Dict]:
        return insight_engine.detect_recurring(self.get_frame(), include_lapsed=include_lapsed)

    def get_runway(self) -> Dict:
        return insight_engine.runway(self.get_frame())

    def get_smart_alerts(self) -> List[Dict]:
        return insight_engine.smart_alerts(self.get_frame())

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
                    cat_lines.append(f"{sanitize_for_prompt(c.get('merchant_category') or 'Other', 30)}: KES {amt:,.0f} ({pct:.1f}%)")
                lines.append("Top spending categories: " + "; ".join(cat_lines))

            if top_merchants:
                merch_lines = [
                    f"{sanitize_for_prompt(m.get('recipient') or 'Unknown')}: KES {m.get('total_amount', 0):,.0f}"
                    for m in top_merchants[:5]
                ]
                lines.append("Top merchants/recipients: " + "; ".join(merch_lines))

            if daily_trend:
                recent = daily_trend[-7:] if len(daily_trend) > 7 else daily_trend
                trend_lines = [f"{d.get('date')}: KES {d.get('total_spent', 0):,.0f}" for d in recent]
                lines.append("Recent daily spend: " + "; ".join(trend_lines))

            if anomalies:
                anom_lines = [
                    f"KES {a.get('amount', 0):,.0f} to {sanitize_for_prompt(a.get('recipient') or 'unknown')} "
                    f"on {sanitize_for_prompt(a.get('timestamp') or '', 30)}"
                    for a in anomalies[:3]
                ]
                lines.append("Unusual transactions detected: " + "; ".join(anom_lines))

            facts = insight_engine.facts_text(self.get_frame())
            if facts:
                lines.append("Verified analytics (computed from the full M-Pesa history):\n" + facts)

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"build_context_string failed: {e}")
            return ""

    def ask_question(self, question: str, days: Optional[int] = None, row_limit: Optional[int] = None) -> Dict:
        try:
            context = self.build_context_string(days=days)
            schema = self.db.get_schema()

            sql = ''
            results = None
            feedback = ''
            for attempt in range(MAX_SQL_ATTEMPTS):
                sql = self.groq.generate_sql(question, schema, days=days, row_limit=row_limit, feedback=feedback)
                logger.info(f"Generated SQL (attempt {attempt + 1}): {sql}")
                if not sql:
                    break
                if not is_safe_select_sql(sql):
                    feedback = "the query was rejected by the safety checks; use a single plain SELECT with allowed functions only"
                    continue
                try:
                    results = self.db.execute_query(sql, strict=True)
                    break
                except Exception as query_error:
                    logger.error(f"Generated SQL failed to run: {query_error}")
                    feedback = str(query_error).splitlines()[0] if str(query_error) else 'execution error'
                    results = None

            if results is None:
                return {
                    'question': question,
                    'sql': sql,
                    'results': [],
                    'analysis': self.groq.chat(question, context=context) or LLM_UNAVAILABLE_MESSAGE,
                    'error': None,
                }

            aggregates = _aggregate_query_results(results)
            analysis = self.groq.analyze_results(question, sql, aggregates, context=context) or LLM_UNAVAILABLE_MESSAGE

            return {
                'question': question,
                'sql': sql,
                'results': results,
                'analysis': analysis,
                'error': None,
            }
        except Exception:
            logger.exception("ask_question failed")
            return {
                'question': question,
                'sql': '',
                'results': [],
                'analysis': "Sorry, I couldn't process that question. Please try rephrasing it.",
                'error': 'question_failed',
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
            context = self.build_context_string(days=days)
            insights = self.groq.generate_insights(summary, extra_context=context) if summary else ""

            data = {
                'summary': summary,
                'spending_by_category': category_spend,
                'daily_trend': daily_trend,
                'anomalies': anomalies,
                'top_merchants': top_merchants,
                'insights': insights,
            }
            self._cache_set(cache_key, data)
            return data
        except Exception as e:
            logger.error(f"get_dashboard_data failed: {e}")
            return {}

    def get_forecast(self, horizon_days: int = 7) -> Dict:
        try:
            frame = self.get_frame(days=forecasting.TRAIN_HISTORY_DAYS)
            result = forecasting.generate_forecast(frame, horizon_days=horizon_days)

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
            frame = self.db.get_frame(days=ANOMALY_HISTORY_DAYS)
            since = pd.Timestamp(since_nairobi(days)) if days is not None else None
                
            baselines = anomaly_detector.compute_baselines(frame)
            if baselines:
                self.db.save_spending_baselines(baselines)

            self.db.drop_obsolete_anomaly_models(anomaly_detector.OBSOLETE_MODELS)
            flagged_all = anomaly_detector.detect_anomalies(frame)
            flagged = [a for a in flagged_all if since is None or pd.Timestamp(a['timestamp']) >= since]
            if flagged_all:
                self.db.save_anomalies(flagged_all)
            self.db.prune_anomalies(anomaly_detector.MODEL_NAME, None, [str(a['transaction_id']) for a in flagged_all])

            reasons = {str(a['transaction_id']): a for a in flagged}
            saved = []
            for row in self.db.get_saved_anomalies(days=days, limit=None):
                info = reasons.get(str(row.get('tx_uuid')))
                if info is None or row.get('model') != info.get('model'):
                    continue
                row['reasons'] = info['reasons']
                row['rules'] = info['rules']
                row['score'] = info['score']
                saved.append(row)
            saved.sort(key=lambda r: (float(r.get('score') or 0), float(r.get('amount') or 0)), reverse=True)

            insight = self.groq.generate_anomaly_insights(saved) if saved else ""
            if saved and not insight:
                insight = _anomaly_fallback_text(saved)

            result = {
                'anomalies': saved,
                'baselines': baselines,
                'count': len(saved),
                'insight': insight or "No unusual transactions detected in your recent spending: everything looks consistent with your normal pattern.",
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
        if not isinstance(limit_amount, (int, float)) or isinstance(limit_amount, bool) or not math.isfinite(limit_amount):
            return {'success': False, 'error': 'Budget limit must be a number'}
        if limit_amount <= 0:
            return {'success': False, 'error': 'Budget limit must be greater than 0'}
        if limit_amount > MAX_BUDGET_LIMIT:
            return {'success': False, 'error': 'Budget limit is too large'}
        if not 1 <= alert_threshold_pct <= 100:
            return {'success': False, 'error': 'Alert threshold must be between 1 and 100'}
        budget = self.db.upsert_budget(normalized, limit_amount, period, alert_threshold_pct)
        self.clear_cache()
        if not budget:
            return {'success': False, 'error': f"Could not save budget for {category}"}
        return {'success': True, 'budget': budget}

    def get_budgets_overview(self) -> List[Dict]:
        return self.db.get_budget_status()

    def get_period_report(self, kind: str, today: Optional[date] = None) -> Dict:
        start, end = report_window(kind, today)
        previous_start, previous_end = window_before(kind, start)
        current = self.db.get_period_report(start, end)
        previous = self.db.get_period_report(previous_start, previous_end)
        budgets = [
            row for row in self.db.get_budget_status()
            if str(row.get('period') or 'monthly').lower() == kind
        ]
        return {'kind': kind, 'current': current, 'previous': previous, 'budgets': budgets}

    def get_pending_budget_alerts(self) -> List[Dict]:
        try:
            status_rows = self.db.get_budget_status()
            if not status_rows:
                return []

            recent = self.db.get_recent_budget_alerts(since_days=45)
            already_alerted = {
                (str(r['budget_id']), str(r['period_start']), r['alert_level']) for r in recent
            }

            due = budget_monitor.evaluate_budgets(status_rows, already_alerted)
            return [
                {
                    'budget_id': str(alert['budget_id']),
                    'period_start': alert['period_start'],
                    'alert_level': alert['alert_level'],
                    'amount_spent': alert['amount_spent'],
                    'category': alert['category'],
                    'message': self.groq.budget_alert_message(alert),
                }
                for alert in due
            ]
        except Exception as e:
            logger.error(f"get_pending_budget_alerts failed: {e}")
            return []

    def acknowledge_budget_alert(self, budget_id: str, period_start: str,
                                 alert_level: str, amount_spent: float) -> bool:
        if alert_level not in (budget_monitor.ALERT_WARNING, budget_monitor.ALERT_OVER):
            return False
        return self.db.record_budget_alert(
            budget_id=budget_id,
            period_start=period_start,
            alert_level=alert_level,
            amount_spent=amount_spent,
        )

    def check_budget_alerts(self) -> List[Dict]:
        results = []
        for alert in self.get_pending_budget_alerts():
            if self.acknowledge_budget_alert(
                alert['budget_id'], alert['period_start'], alert['alert_level'], alert['amount_spent']
            ):
                results.append({
                    'category': alert['category'],
                    'alert_level': alert['alert_level'],
                    'message': alert['message'],
                })
        return results

    def generate_dynamic_chart(self, description: str, dark: bool = True, commentary: bool = True) -> Dict:
        from src import chart_generator
        return chart_generator.generate_dynamic_chart(self, description, dark=dark, commentary=commentary)

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
        self.clear_cache()
        self.groq.invalidate_cache()
        forecasting.invalidate_cache()

        if inserted == 0:
            return {'success': False, 'error': 'Could not save transaction to the database'}

        tx_type = tx.get('type', 'debit')
        amount = tx.get('amount', 0) or 0
        recipient = tx.get('recipient', 'Unknown')
        balance = tx.get('balance')
        category = tx.get('merchant_category') or 'other'
        cost = tx.get('transaction_cost') or 0
        balance_line = (
            f"Balance: KES {balance:,.2f}\n" if balance is not None
            else "Balance: not shown in this SMS\n"
        )

        if tx_type == 'credit':
            summary = (
                f"Money in KES {amount:,.2f}\n"
                f"From: {recipient}\n"
                f"{balance_line}"
                f"Transaction ID: {tx_id}"
            )
        else:
            verb = {
                'withdrawal': 'Withdrew', 'airtime': 'Bought airtime for', 'debit': 'Debited',
            }.get(tx_type, 'Paid')
            summary = (
                f"{verb} KES {amount:,.2f}\n"
                f"To: {recipient}\n"
                f"Category: {category.title()}\n"
                f"Fee: KES {cost:,.2f}\n"
                f"{balance_line}"
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
        self.clear_cache()
        self.groq.invalidate_cache()
        forecasting.invalidate_cache()
        return count
