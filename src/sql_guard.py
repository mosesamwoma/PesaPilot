import re

_FORBIDDEN_SQL = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CREATE|ATTACH|MERGE|CALL|COPY|INTO|'
    r'SET_CONFIG|CURRENT_SETTING|DBLINK|PG_[A-Z_]+|LO_[A-Z_]+|INFORMATION_SCHEMA|'
    r'CURRENT_USER|SESSION_USER|CURRENT_DATABASE|CURRENT_SCHEMA|VERSION|'
    r'NEXTVAL|SETVAL|GENERATE_SERIES|RECURSIVE|REPEAT|LISTEN|NOTIFY|VACUUM|ANALYZE|LOCK|DO|'
    r'REG[A-Z]+|XMLPARSE|XMLELEMENT|QUERY_TO_XML|TABLE_TO_XML|CURSOR_TO_XML)\b',
    re.IGNORECASE,
)
_LOCKING_CLAUSE = re.compile(r'\bFOR\s+(?:NO\s+KEY\s+UPDATE|KEY\s+SHARE|SHARE|UPDATE)\b', re.IGNORECASE)
_ALLOWED_START = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_DOLLAR_QUOTE = re.compile(r'\$\w*\$')
_QUOTED_IDENT = re.compile(r'"')
_CALL = re.compile(r'\b([a-z_][a-z0-9_]*)\s*\(', re.IGNORECASE)
_MAX_SQL_CHARS = 4000

_ALLOWED_CALLS = frozenset({
    'sum', 'avg', 'count', 'min', 'max', 'stddev', 'stddev_pop', 'stddev_samp', 'variance', 'var_pop',
    'var_samp', 'percentile_cont', 'percentile_disc', 'mode', 'string_agg', 'array_agg', 'bool_and', 'bool_or',
    'corr', 'row_number', 'rank', 'dense_rank', 'percent_rank', 'cume_dist', 'ntile', 'lag', 'lead',
    'first_value', 'last_value', 'nth_value',
    'round', 'ceil', 'ceiling', 'floor', 'trunc', 'abs', 'sign', 'mod', 'power', 'sqrt', 'ln', 'log', 'exp',
    'greatest', 'least', 'coalesce', 'nullif', 'cast',
    'date_trunc', 'date_part', 'extract', 'date', 'now', 'age', 'make_date', 'make_interval', 'timezone',
    'to_char', 'to_date', 'to_timestamp',
    'lower', 'upper', 'length', 'char_length', 'substr', 'substring', 'trim', 'ltrim', 'rtrim', 'btrim',
    'concat', 'concat_ws', 'replace', 'split_part', 'left', 'right', 'position', 'initcap', 'regexp_replace',
    'numeric', 'decimal', 'varchar', 'char', 'timestamp', 'timestamptz', 'time', 'float', 'real',
    'daily_trend_running', 'category_month_trend', 'top_merchants_ranked', 'detect_category_anomalies',
    'budget_pace', 'recipient_gaps',
    'in', 'as', 'over', 'filter', 'values', 'exists', 'any', 'all', 'on', 'and', 'or', 'not', 'select', 'from',
    'where', 'join', 'using', 'with', 'by', 'partition', 'order', 'group', 'having', 'when', 'then', 'else',
    'case', 'end', 'interval', 'union', 'intersect', 'except', 'limit', 'offset', 'between', 'like', 'ilike',
    'is', 'distinct', 'within', 'lateral', 'rows', 'range', 'preceding', 'following', 'unbounded', 'current',
    'row', 'similar', 'to', 'at', 'zone', 'desc', 'asc', 'nulls', 'first', 'last', 'both', 'leading', 'trailing',
    'for',
})


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
    if _FORBIDDEN_SQL.search(code) or _LOCKING_CLAUSE.search(code):
        return False
    for match in _CALL.finditer(code):
        if match.group(1).lower() not in _ALLOWED_CALLS:
            return False
    return True
