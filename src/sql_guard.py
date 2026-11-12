import re

_FORBIDDEN_SQL = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CREATE|ATTACH|MERGE|CALL|COPY|INTO|'
    r'SET_CONFIG|CURRENT_SETTING|DBLINK|PG_[A-Z_]+|LO_[A-Z_]+|INFORMATION_SCHEMA|'
    r'CURRENT_USER|SESSION_USER|CURRENT_DATABASE|CURRENT_SCHEMA|VERSION|'
    r'NEXTVAL|SETVAL|GENERATE_SERIES|REPEAT|LISTEN|NOTIFY|VACUUM|ANALYZE|LOCK|DO)\b',
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_DOLLAR_QUOTE = re.compile(r'\$\w*\$')
_QUOTED_IDENT = re.compile(r'"')
_MAX_SQL_CHARS = 4000


def is_safe_select_sql(sql) -> bool:
    if not sql or not isinstance(sql, str) or len(sql) > _MAX_SQL_CHARS:
        return False
    cleaned = sql.strip().rstrip(';').strip()
    if not cleaned or _DOLLAR_QUOTE.search(cleaned) or _QUOTED_IDENT.search(cleaned):
        return False
    if '\\' in cleaned or '\x00' in cleaned:
        return False
    code = _STRING_LITERAL.sub("''", cleaned)
    if "'" in code.replace("''", ''):
        return False
    if ';' in code or '--' in code or '/*' in code:
        return False
    if not _ALLOWED_START.match(code):
        return False
    return not _FORBIDDEN_SQL.search(code)
