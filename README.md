# PesaPilot bug-fix and test patch

This zip contains only the files that changed. The folder structure inside
the zip matches the folder structure of the PesaPilot repo, so you can
extract it straight into the project root and every file will land in the
right place and overwrite the old version.

## How to apply

From your PesaPilot project root:

```
unzip -o pesapilot-fixes.zip -d .
```

`-o` overwrites the existing `src/groq_client.py`, `src/anomaly_detector.py`,
and `src/chart_generator.py` with the fixed versions, and drops the new
`pytest.ini` plus all six files in `tests/` into place in one shot, no
copy-pasting file by file.

If you'd rather review before overwriting, extract to a temp folder first:

```
unzip pesapilot-fixes.zip -d /tmp/pesapilot-fixes
diff -ru src/ /tmp/pesapilot-fixes/src/
diff -ru tests/ /tmp/pesapilot-fixes/tests/
```

## What's inside

```
pytest.ini                       new — registers the "integration" test marker
src/groq_client.py                fixed — API_TIMEOUT was read but never sent to the Groq API call
src/anomaly_detector.py           fixed — crashed if merchant_category was missing from a transaction
src/chart_generator.py            fixed — same crash pattern for merchant_category/recipient/amount/transaction_cost
tests/conftest.py                 new — blocks integration tests from running against a non-test database
tests/test_database.py            fixed — no longer leaves a test row behind in your database
tests/test_analyzer.py            fixed — same database/API safety checks as test_database.py
tests/test_anomaly_detector.py    new — unit tests, no database or API needed
tests/test_budget_monitor.py      new — unit tests, no database or API needed
tests/test_chart_generator.py     new — unit tests, no database or API needed
tests/test_groq_client.py         new — unit tests, no database or API needed
```

## Running the tests after applying

Fast, fully offline run (no database, no API key needed):

```
pip install -r requirements.txt --break-system-packages
pytest -m "not integration"
```

Full run including the live-database and live-Groq-API tests — only do this
against a disposable test database, never production:

```
POSTGRES_DB=pesapilot_test GROQ_API_KEY=your_key pytest -m integration
```

Everything at once — the integration tests will skip themselves automatically
with a clear message if `POSTGRES_DB` doesn't look like a test database:

```
pytest
```
