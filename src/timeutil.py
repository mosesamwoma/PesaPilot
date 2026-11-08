from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

NAIROBI = ZoneInfo("Africa/Nairobi")


def now_nairobi() -> datetime:
    return datetime.now(NAIROBI).replace(tzinfo=None)


def today_nairobi() -> date:
    return now_nairobi().date()


def since_nairobi(days: Optional[int]) -> Optional[datetime]:
    if days is None:
        return None
    return now_nairobi() - timedelta(days=days)


def from_epoch_ms(value) -> Optional[datetime]:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, timezone.utc).astimezone(NAIROBI).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def last_full_week(today: Optional[date] = None) -> Tuple[date, date]:
    today = today or today_nairobi()
    start = today - timedelta(days=today.weekday() + 7)
    return start, start + timedelta(days=7)


def last_full_month(today: Optional[date] = None) -> Tuple[date, date]:
    today = today or today_nairobi()
    end = today.replace(day=1)
    start = (end - timedelta(days=1)).replace(day=1)
    return start, end


def report_window(kind: str, today: Optional[date] = None) -> Tuple[date, date]:
    if kind == 'weekly':
        return last_full_week(today)
    if kind == 'monthly':
        return last_full_month(today)
    raise ValueError(f"Unknown report kind: {kind}")


def window_before(kind: str, start: date) -> Tuple[date, date]:
    if kind == 'weekly':
        return start - timedelta(days=7), start
    if kind == 'monthly':
        return (start - timedelta(days=1)).replace(day=1), start
    raise ValueError(f"Unknown report kind: {kind}")
