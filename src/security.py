"""Shared secret-handling helpers.

Nothing in this module contains a secret. It only validates values that come
from the environment (.env) and compares tokens in constant time.
"""
import hmac
import os
import re
from typing import Optional

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
    """True for empty values and the obvious 'fill me in' examples."""
    cleaned = (value or '').strip()
    return not cleaned or bool(_PLACEHOLDER_RE.match(cleaned))


def load_api_token() -> str:
    """Return API_TOKEN from the environment or raise if it is missing/weak."""
    token = os.getenv('API_TOKEN', '').strip()
    if is_placeholder(token) or len(token) < MIN_API_TOKEN_LENGTH:
        raise RuntimeError(TOKEN_HELP)
    return token


def token_matches(supplied: Optional[str], expected: str) -> bool:
    """Constant-time token comparison."""
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))


def extract_token(headers) -> Optional[str]:
    """Read the token from 'X-API-Key' or 'Authorization: Bearer <token>'."""
    supplied = headers.get('x-api-key')
    if supplied:
        return supplied.strip()
    scheme, _, credential = (headers.get('authorization') or '').partition(' ')
    if scheme.lower() == 'bearer' and credential.strip():
        return credential.strip()
    return None
