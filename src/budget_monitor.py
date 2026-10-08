import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from src.timeutil import today_nairobi

logger = logging.getLogger(__name__)

ALERT_WARNING = "warning"
ALERT_OVER = "over"


def period_start_for(period: str, today: Optional[date] = None) -> date:
    today = today or today_nairobi()
    period = (period or "monthly").lower()
    if period == "weekly":
        return today - timedelta(days=today.weekday())
    return today.replace(day=1)


def evaluate_budgets(
    budget_status_rows: List[Dict],
    already_alerted: Set[Tuple[str, str, str]],
) -> List[Dict]:
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
            continue

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
