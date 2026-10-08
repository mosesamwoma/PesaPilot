import re

_FORBIDDEN_SQL = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CREATE|ATTACH|MERGE|CALL|COPY|'
    r'SET_CONFIG|DBLINK|PG_[A-Z_]+|LO_[A-Z_]+)\b',
    re.IGNORECASE,
)
_ALLOWED_START = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)


def is_safe_select_sql(sql) -> bool:
    if not sql or not isinstance(sql, str):
        return False
    cleaned = sql.strip().rstrip(';').strip()
    if not cleaned or ';' in cleaned:
        return False
    if '--' in cleaned or '/*' in cleaned:
        return False
    if not _ALLOWED_START.match(cleaned):
        return False
    return not _FORBIDDEN_SQL.search(cleaned)
