import hmac
import os
import re
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

MIN_API_TOKEN_LENGTH = 24

_PLACEHOLDER_RE = re.compile(
    r'^(?:'
    r'change[-_ ]?me.*'
    r'|.*your[-_ ]?(?:groq[-_ ]?)?(?:api[-_ ]?)?(?:key|token|password|secret)[-_ ]?here.*'
    r'|x{3,}'
    r'|<.*>'
    r'|todo|example|password|secret|test-key|pesapilot'
    r')$',
    re.IGNORECASE,
)

TOKEN_HELP = (
    "API_TOKEN must be set to a random secret of at least "
    f"{MIN_API_TOKEN_LENGTH} characters. Generate one with:\n"
    "  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
    "or run scripts/generate_secrets.sh to create a complete .env."
)


def is_placeholder(value: Optional[str]) -> bool:
    cleaned = (value or '').strip()
    return not cleaned or bool(_PLACEHOLDER_RE.match(cleaned))


def load_api_token() -> str:
    token = os.getenv('API_TOKEN', '').strip()
    if is_placeholder(token) or len(token) < MIN_API_TOKEN_LENGTH:
        raise RuntimeError(TOKEN_HELP)
    return token


def token_matches(supplied: Optional[str], expected: str) -> bool:
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))


def extract_token(headers) -> Optional[str]:
    supplied = headers.get('x-api-key')
    if supplied:
        return supplied.strip()
    scheme, _, credential = (headers.get('authorization') or '').partition(' ')
    if scheme.lower() == 'bearer' and credential.strip():
        return credential.strip()
    return None


_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]+')


def sanitize_for_prompt(value, limit: int = 80) -> str:
    cleaned = _CONTROL_CHARS_RE.sub(' ', str(value if value is not None else ''))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:limit]


class SlidingWindowLimiter:

    def __init__(self, max_events: int, window_seconds: float, max_keys: int = 4096):
        self.max_events = max(1, int(max_events))
        self.window = float(window_seconds)
        self.max_keys = max_keys
        self._events: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        events = self._events.setdefault(key, deque())
        cutoff = now - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def _evict_if_full(self, now: float) -> None:
        if len(self._events) < self.max_keys:
            return
        for stale in [k for k, e in self._events.items() if not e or e[-1] <= now - self.window]:
            del self._events[stale]
        while len(self._events) >= self.max_keys:
            del self._events[next(iter(self._events))]

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._evict_if_full(now)
            events = self._prune(key, now)
            if len(events) >= self.max_events:
                return False
            events.append(now)
            return True

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                return False
            return len(self._prune(key, now)) >= self.max_events

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if not events:
                return 1
            return max(1, int(self.window - (now - events[0])) + 1)


def env_int(name: str, default: int, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        value = int(os.getenv(name, '').strip() or default)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))
