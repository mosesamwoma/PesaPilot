# src/analyzer.py
import logging
from typing import Dict, List, Optional
from src.database import SupabaseDB
from src.groq_client import GroqClient
from src import forecasting

logger = logging.getLogger(__name__)


def _aggregate_query_results(results: List[Dict], top_group_limit: int = 8) -> Dict:
    """Turn raw SQL result rows into Python-computed aggregates (sums/avgs/
    counts) so the LLM narrates numbers instead of eyeballing/recomputing
    them from a dumped row list. Generic — works for whatever columns the
    dynamically-generated SQL happened to return.
    """
    if not results:
        return {"row_count": 0}

    sample = results[0]
    numeric_cols = [
        k for k, v in sample.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]

    agg: Dict = {"row_count": len(results)}

    for col in numeric_cols:
        vals = [r.get(col) for r in results if isinstance(r.get(col), (int, float))]
        if not vals:
            continue
        agg[col] = {
            "sum": round(sum(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "count": len(vals),
        }

    # Group the primary numeric column (prefer 'amount') by the first
    # categorical column present, so the model gets a ranked breakdown
    # without needing to sum raw rows itself.
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
            break  # one grouping is enough — keep the payload compact

    return agg


class MpesaAnalyzer:
    def __init__(self):
        self.db = SupabaseDB()
        self.groq = GroqClient()
        self._cache: Dict = {}

    def build_context_string(self, days: int = 30) -> str:
        """Build a rich, human-readable context block from current financial data
        so the AI has the full picture instead of just the raw question."""
        try:
            summary = self.db.get_range_summary(days=days) or {}
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
            aggregates = _aggregate_query_results(results)
            analysis = self.groq.analyze_results(question, sql, aggregates, context=context)

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
            summary = self.db.get_range_summary(days=days)
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

    # ── FORECAST (NEW) ─────────────────────────────────────────────────────
    def get_forecast(self, horizon_days: int = 7) -> Dict:
        """Generate (or reuse a cached) Prophet spending forecast for the given
        horizon, aggregating the existing transaction history into daily totals,
        plus a Groq-generated natural-language summary of the projection."""
        try:
            transactions = self.db.get_transactions(days=forecasting.TRAIN_HISTORY_DAYS, limit=5000)
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
        """Convenience helper for the dashboard: both the 7-day and 30-day
        forecasts in a single call (each independently cached by horizon)."""
        return {
            'horizon_7': self.get_forecast(horizon_days=7),
            'horizon_30': self.get_forecast(horizon_days=30),
        }
    # ── END FORECAST ───────────────────────────────────────────────────────

    def parse_and_insert_sms(self, sms_content: str) -> Dict:
        """Parse a single M-Pesa SMS text and insert it into the database.
        Called by the WhatsApp /parse-sms endpoint for manual PIN-based entry."""
        from src.parse_sms import MpesaParser
        parser = MpesaParser()
        tx = parser._parse_sms_text(sms_content)

        if not tx:
            return {'success': False, 'error': 'Could not parse SMS — unrecognised format'}

        tx_id = tx.get('transaction_id')
        if not tx_id:
            return {'success': False, 'error': 'No transaction ID found in SMS'}

        import pandas as pd
        df = pd.DataFrame([tx])
        inserted = self.db.insert_transactions(df)
        self._cache.clear()
        self.groq.invalidate_cache()  # new transactions → stale Groq responses
        forecasting.invalidate_cache()  # new transactions → stale forecast

        if inserted == 0:
            # upsert succeeded but row already existed — still a success
            pass

        tx_type = tx.get('type', 'debit')
        amount = tx.get('amount', 0) or 0
        recipient = tx.get('recipient', 'Unknown')
        # tx.get('balance', 0) only falls back to 0 when the key is MISSING —
        # _extract_balance() returns an explicit None when no "balance is Ksh..."
        # phrase is found (e.g. airtime/bundle SMS), so the key IS present with
        # value None and the default above is skipped. Formatting None with
        # ':,.2f' raises TypeError, which crashed manual SMS entry for any
        # message without a balance line. `or 0` catches that None case too.
        balance = tx.get('balance', 0) or 0
        category = tx.get('merchant_category', 'other')

        if tx_type == 'credit':
            summary = (
                f"✅ Received KES {amount:,.2f}\n"
                f"From: {recipient}\n"
                f"Balance: KES {balance:,.2f}\n"
                f"Transaction ID: {tx_id}"
            )
        else:
            summary = (
                f"✅ Paid KES {amount:,.2f}\n"
                f"To: {recipient}\n"
                f"Category: {category.title()}\n"
                f"Balance: KES {balance:,.2f}\n"
                f"Transaction ID: {tx_id}"
            )

        return {'success': True, 'summary': summary, 'transaction': tx}

    def load_transactions(self, xml_path: str, csv_output: str = None) -> int:
        from src.parse_sms import MpesaParser
        parser = MpesaParser()
        df = parser.parse_xml_to_csv(xml_path, output_path=csv_output)
        if df.empty:
            logger.warning("No transactions to load")
            return 0
        count = self.db.insert_transactions(df)
        self._cache.clear()
        self.groq.invalidate_cache()  # new transactions → stale Groq responses
        forecasting.invalidate_cache()  # new transactions → stale forecast
        return count