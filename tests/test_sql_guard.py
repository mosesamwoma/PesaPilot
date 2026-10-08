import pytest

from src.sql_guard import is_safe_select_sql


@pytest.mark.parametrize('sql', [
    "SELECT * FROM transactions",
    "select * from transactions;",
    "WITH t AS (SELECT amount FROM transactions) SELECT SUM(amount) FROM t",
    "SELECT replace(recipient, 'a', 'b') FROM transactions",
    "SELECT created_at, updated_at FROM budgets",
])
def test_accepts_read_only_queries(sql):
    assert is_safe_select_sql(sql) is True


@pytest.mark.parametrize('sql', [
    "",
    None,
    "DELETE FROM transactions",
    "SELECT 1; DROP TABLE transactions",
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT 1 -- hidden",
    "SELECT /* x */ 1",
    "SELECT set_config('a','b',false)",
    "COPY transactions TO '/tmp/x'",
    "INSERT INTO budgets VALUES (1)",
])
def test_rejects_everything_else(sql):
    assert is_safe_select_sql(sql) is False
