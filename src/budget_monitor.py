# src/budget_monitor.py
"""
Budget goals + proactive alert engine for PesaPilot.

Works off the `budgets`, `budget_alerts`, and `budget_status` objects that
already exist in schema/init_db.sql:
  - budgets        : the category limits the user has set
  - budget_status  : a VIEW that computes spent_this_period live per budget
  - budget_alerts  : a log of alerts already sent, so the same breach never
                      pings the user twice in the same period

This module has no knowledge of Supabase/Groq/WhatsApp — it is a plain
function-based engine (mirrors src/forecasting.py's design) that decides
WHICH alerts are due given the current budget_status rows and a set of
alerts already sent. `src/analyzer.py` does the DB reads/writes and calls
into this module for the actual decision logic, then `whatsapp_api.py`
turns the result into WhatsApp messages.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

ALERT_WARNING = "warning"   # crossed alert_threshold_pct but still under 100%
ALERT_OVER = "over"         # crossed 100% of the budget limit

# Alert ordering matters: if a user is already over-budget we don't also
# want to separately ping them for "near" the same period — over supersedes
# warning for a given check, but each is tracked independently in
# budget_alerts so a category that later also breaches 100% still gets its
# own distinct "over" ping even after a "warning" ping already fired.


def period_start_for(period: str, today: date = None) -> date:
    """The first day of the CURRENT budget period, matching the same
    date_trunc('week'/'month', NOW()) logic used by the budget_status SQL
    view, so alert de-duplication keys line up with what the view reports."""
    today = today or date.today()
    period = (period or "monthly").lower()
    if period == "weekly":
        return today - timedelta(days=today.weekday())  # Monday
    # default: monthly
    return today.replace(day=1)


def evaluate_budgets(
    budget_status_rows: List[Dict],
    already_alerted: Set[Tuple[str, str, str]],
) -> List[Dict]:
    """Given the live budget_status rows and a set of
    (budget_id, period_start_iso, alert_level) tuples that have ALREADY
    been sent, return the list of NEW alerts that are due right now.

    Each budget_status row is expected to have:
      budget_id, category, period, limit_amount, alert_threshold_pct,
      spent_this_period
    """
    due: List[Dict] = []

    for row in budget_status_rows or []:
        try:
            budget_id = row["budget_id"]
            limit_amount = float(row.get("limit_amount") or 0)
            spent = float(row.get("spent_this_period") or 0)
            threshold_pct = float(row.get("alert_threshold_pct") or 80)
            period = row.get("period", "monthly")
        except (KeyError, TypeError, ValueError):
            logger.warning(f"Skipping malformed budget_status row: {row}")
            continue

        if limit_amount <= 0:
            continue

        pct_used = (spent / limit_amount) * 100
        p_start = period_start_for(period).isoformat()

        # Over-budget takes priority and is checked first.
        if pct_used >= 100:
            key = (budget_id, p_start, ALERT_OVER)
            if key not in already_alerted:
                due.append({
                    "budget_id": budget_id,
                    "category": row.get("category"),
                    "period": period,
                    "period_start": p_start,
                    "alert_level": ALERT_OVER,
                    "limit_amount": limit_amount,
                    "amount_spent": spent,
                    "pct_used": round(pct_used, 1),
                })
            continue  # don't also fire a "warning" once already over

        if pct_used >= threshold_pct:
            key = (budget_id, p_start, ALERT_WARNING)
            if key not in already_alerted:
                due.append({
                    "budget_id": budget_id,
                    "category": row.get("category"),
                    "period": period,
                    "period_start": p_start,
                    "alert_level": ALERT_WARNING,
                    "limit_amount": limit_amount,
                    "amount_spent": spent,
                    "pct_used": round(pct_used, 1),
                })

    return due