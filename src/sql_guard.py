import re

_FORBIDDEN_SQL = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CREATE|ATTACH|MERGE|CALL|COPY|'
    r'SET_CONFIG|DBLINK|PG_[A-Z_]+|LO_[A-Z_]+)\b',
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_DOLLAR_QUOTE = re.compile(r'\$\w*\$')


def is_safe_select_sql(sql) -> bool:
    if not sql or not isinstance(sql, str):
        return False
    cleaned = sql.strip().rstrip(';').strip()
    if not cleaned or _DOLLAR_QUOTE.search(cleaned):
        return False
    code = _STRING_LITERAL.sub("''", cleaned)
    if "'" in code.replace("''", ''):
        return False
    if ';' in code or '--' in code or '/*' in code:
        return False
    if not _ALLOWED_START.match(code):
        return False
    return not _FORBIDDEN_SQL.search(code)
