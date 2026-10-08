from datetime import date, datetime, timedelta, timezone
from typing import Optional
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
