import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

from src.timeutil import today_nairobi


@dataclass(frozen=True)
class Period:
    date_from: Optional[date]
    date_to: Optional[date]
    label: str

    @property
    def is_all_time(self) -> bool:
        return self.date_from is None and self.date_to is None


_MONTHS = {
    'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
    'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7, 'august': 8, 'aug': 8,
    'september': 9, 'sep': 9, 'sept': 9, 'october': 10, 'oct': 10, 'november': 11, 'nov': 11,
    'december': 12, 'dec': 12,
}
_MONTH_ALT = '|'.join(sorted(_MONTHS, key=len, reverse=True))
_NUMBER_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'fourteen': 14, 'fifteen': 15, 'twenty': 20, 'thirty': 30,
}
_NUM = r'(\d{1,4}|' + '|'.join(_NUMBER_WORDS) + r')'

_ALL_TIME_RE = re.compile(r'\ball[\s-]?time\b|\bever\b|since the beginning|full history|entire history|\boverall\b')
_ISO_RANGE_RE = re.compile(
    r'(\d{4})-(\d{2})-(\d{2})\s*(?:to|until|through|and|-|–)\s*(\d{4})-(\d{2})-(\d{2})')
_DMY_RANGE_RE = re.compile(
    r'(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:to|until|through|and|-|–)\s*(\d{1,2})/(\d{1,2})/(\d{4})')
_ISO_SINCE_RE = re.compile(r'(?:since|from|after)\s+(\d{4})-(\d{2})-(\d{2})')
_DMY_SINCE_RE = re.compile(r'(?:since|from|after)\s+(\d{1,2})/(\d{1,2})/(\d{4})')
_ISO_UNTIL_RE = re.compile(r'(?:until|till|before|up to)\s+(\d{4})-(\d{2})-(\d{2})')
_ISO_SINGLE_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
_ROLLING_RE = re.compile(
    r'(?:last|past|previous|recent)\s+' + _NUM + r'\s*-?\s*(day|week|month|year)s?\b(?!\s*-?\s*(?:moving|rolling|average|avg|mean|ma\b|smooth|window))')
_ROLLING_SHORT_RE = re.compile(
    r'\b' + _NUM + r'\s*-?\s*(day|week|month)s?\b(?!\s*-?\s*(?:moving|rolling|average|avg|mean|ma\b|smooth|window))')
_QUARTER_RE = re.compile(r'\bq([1-4])(?:\s*(?:of\s*)?(\d{4}))?\b')
_MONTH_RANGE_RE = re.compile(
    r'(?:from\s+)?\b(' + _MONTH_ALT + r')\b\s*(\d{4})?\s*(?:to|until|through|-|–)\s*\b(' + _MONTH_ALT + r')\b\s*(\d{4})?')
_MONTH_YEAR_RE = re.compile(r'\b(' + _MONTH_ALT + r')\b[\s,]*(\d{4})\b')
_MONTH_NAME_RE = re.compile(r'\b(' + _MONTH_ALT + r')\b')
_MAY_CONTEXT_RE = re.compile(r'\b(?:in|for|during|of|last|this|since|from|until|to)\s+may\b|\bmay\s+\d{4}\b|\bmay\s*(?:to|-|–)\s')
_YEAR_RE = re.compile(r'\b(20\d{2})\b')


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token, 1)


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _label(start: Optional[date], end: Optional[date]) -> str:
    if start and end:
        if start == end:
            return start.strftime('%d %b %Y')
        if start.day == 1 and end == _month_bounds(end.year, end.month)[1] and (start.year, start.month) == (end.year, end.month):
            return start.strftime('%B %Y')
        return f"{start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}"
    if start:
        return f"since {start.strftime('%d %b %Y')}"
    if end:
        return f"until {end.strftime('%d %b %Y')}"
    return 'all time'


def _recent_month_year(month: int, today: date) -> int:
    return today.year if month <= today.month else today.year - 1


def resolve_period(text: str, today: Optional[date] = None) -> Optional[Period]:
    q = (text or '').lower()
    if not q.strip():
        return None
    today = today or today_nairobi()

    if _ALL_TIME_RE.search(q):
        return Period(None, None, 'all time')

    m = _ISO_RANGE_RE.search(q)
    if m:
        start = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        end = _safe_date(int(m[4]), int(m[5]), int(m[6]))
        if start and end:
            if end < start:
                start, end = end, start
            return Period(start, end, _label(start, end))
    m = _DMY_RANGE_RE.search(q)
    if m:
        start = _safe_date(int(m[3]), int(m[2]), int(m[1]))
        end = _safe_date(int(m[6]), int(m[5]), int(m[4]))
        if start and end:
            if end < start:
                start, end = end, start
            return Period(start, end, _label(start, end))

    m = _ISO_SINCE_RE.search(q)
    if m:
        start = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if start:
            return Period(start, today, _label(start, None))
    m = _DMY_SINCE_RE.search(q)
    if m:
        start = _safe_date(int(m[3]), int(m[2]), int(m[1]))
        if start:
            return Period(start, today, _label(start, None))
    m = _ISO_UNTIL_RE.search(q)
    if m:
        end = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if end:
            return Period(None, end, _label(None, end))
    m = _ISO_SINGLE_RE.search(q)
    if m:
        single = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if single:
            return Period(single, single, _label(single, single))

    if re.search(r'\bday before yesterday\b', q):
        day = today - timedelta(days=2)
        return Period(day, day, day.strftime('%d %b %Y'))
    if re.search(r'\byesterday\b', q):
        day = today - timedelta(days=1)
        return Period(day, day, 'yesterday')
    if re.search(r'\btoday\b|\btoday\'s\b', q):
        return Period(today, today, 'today')

    if re.search(r'\bthis week\b|\bcurrent week\b', q):
        start = today - timedelta(days=today.weekday())
        return Period(start, today, 'this week')
    if re.search(r'\blast week\b|\bprevious week\b', q):
        start = today - timedelta(days=today.weekday() + 7)
        return Period(start, start + timedelta(days=6), 'last week')
    if re.search(r'\bthis month\b|\bcurrent month\b', q):
        return Period(today.replace(day=1), today, 'this month')
    if re.search(r'\blast month\b|\bprevious month\b', q):
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start, end = _month_bounds(end.year, end.month)
        return Period(start, end, start.strftime('%B %Y'))
    if re.search(r'\byear to date\b|\bytd\b', q):
        return Period(date(today.year, 1, 1), today, 'year to date')
    if re.search(r'\bthis year\b|\bcurrent year\b', q):
        return Period(date(today.year, 1, 1), today, f'{today.year} so far')
    if re.search(r'\blast year\b|\bprevious year\b', q):
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1))
    if re.search(r'\bthis quarter\b|\bcurrent quarter\b', q):
        qn = (today.month - 1) // 3
        start = date(today.year, qn * 3 + 1, 1)
        return Period(start, today, f'Q{qn + 1} {today.year} so far')
    if re.search(r'\blast quarter\b|\bprevious quarter\b', q):
        qn = (today.month - 1) // 3
        year, qn = (today.year, qn - 1) if qn > 0 else (today.year - 1, 3)
        start = date(year, qn * 3 + 1, 1)
        end = _month_bounds(year, qn * 3 + 3)[1]
        return Period(start, end, f'Q{qn + 1} {year}')
    if re.search(r'\bfortnight\b|\btwo weeks\b', q) and not _ROLLING_RE.search(q):
        return Period(today - timedelta(days=13), today, 'last 14 days')

    m = _ROLLING_RE.search(q)
    if m:
        n = max(1, _to_int(m[1]))
        unit = m[2]
        span = {'day': n, 'week': n * 7, 'month': n * 30, 'year': n * 365}[unit]
        span = min(span, 3650)
        return Period(today - timedelta(days=span - 1), today, f'last {span} days' if unit == 'day' else f'last {n} {unit}s')
    m = _ROLLING_SHORT_RE.search(q)
    if m:
        n = max(1, _to_int(m[1]))
        unit = m[2]
        span = min({'day': n, 'week': n * 7, 'month': n * 30}[unit], 3650)
        return Period(today - timedelta(days=span - 1), today, f'last {span} days')
    if re.search(r'\bpast week\b', q):
        return Period(today - timedelta(days=6), today, 'last 7 days')
    if re.search(r'\bpast month\b', q):
        return Period(today - timedelta(days=29), today, 'last 30 days')

    m = _QUARTER_RE.search(q)
    if m:
        qn = int(m[1])
        year = int(m[2]) if m[2] else (today.year if qn - 1 <= (today.month - 1) // 3 else today.year - 1)
        start = date(year, (qn - 1) * 3 + 1, 1)
        end = _month_bounds(year, qn * 3)[1]
        return Period(start, min(end, today) if end > today else end, f'Q{qn} {year}')

    m = _MONTH_RANGE_RE.search(q)
    if m and not (m[1] == 'may' and not _MAY_CONTEXT_RE.search(q)) and not (m[3] == 'may' and not _MAY_CONTEXT_RE.search(q)):
        m1, m2 = _MONTHS[m[1]], _MONTHS[m[3]]
        y2 = int(m[4]) if m[4] else _recent_month_year(m2, today)
        y1 = int(m[2]) if m[2] else (y2 if m1 <= m2 else y2 - 1)
        start = date(y1, m1, 1)
        end = _month_bounds(y2, m2)[1]
        if end >= start:
            return Period(start, min(end, today) if end > today else end, _label(start, end))

    m = _MONTH_YEAR_RE.search(q)
    if m and not (m[1] == 'may' and not _MAY_CONTEXT_RE.search(q)):
        month, year = _MONTHS[m[1]], int(m[2])
        start, end = _month_bounds(year, month)
        return Period(start, min(end, today) if end > today else end, start.strftime('%B %Y'))

    m = _MONTH_NAME_RE.search(q)
    if m:
        name = m[1]
        if name != 'may' or _MAY_CONTEXT_RE.search(q):
            month = _MONTHS[name]
            year = _recent_month_year(month, today)
            start, end = _month_bounds(year, month)
            return Period(start, min(end, today) if end > today else end, start.strftime('%B %Y'))

    m = _YEAR_RE.search(q)
    if m:
        year = int(m[1])
        if 2000 <= year <= today.year:
            end = date(year, 12, 31)
            return Period(date(year, 1, 1), min(end, today) if end > today else end, str(year))

    return None
