import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _looks_like_test_database(name: str) -> bool:
    return bool(name) and 'test' in name.lower()


def require_test_database() -> None:
    db_name = os.getenv('POSTGRES_DB', '')
    if not _looks_like_test_database(db_name):
        pytest.skip(
            f"POSTGRES_DB={db_name!r} does not look like a dedicated test database "
            "(its name must contain 'test'). Point POSTGRES_DB at a disposable test "
            "database before running integration tests, so tests never write "
            "into production data. Example: POSTGRES_DB=pesapilot_test"
        )


def require_groq_key() -> None:
    if not os.getenv('GROQ_API_KEY'):
        pytest.skip("GROQ_API_KEY is not set; skipping tests that call the live Groq API")
