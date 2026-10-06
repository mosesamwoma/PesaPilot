# Fixes in this revision

**Renames:** `entrypoint.baileys.sh` -> `entrypoint_baileys.sh`, `podman/entrypoint.wwebjs.sh` -> `podman/entrypoint_wwebjs.sh` (Dockerfile + podman/Containerfile updated).

**Bugs fixed**
- Anomaly detection missed big outliers when >half the amounts in a category were identical (MAD = 0 scored everything 0).
- One huge anomaly score overflowed `anomalies.score DECIMAL(6,3)` and silently lost the *whole* batch. Scores are clamped; schema widened to `DECIMAL(10,3)` (idempotent migration in `schema/init_db.sql`).
- Manual SMS failures replied "❌ undefined" (bots read `response.error`, API puts the text in `summary`).
- `/parse-sms` turned its own HTTP 400 into a 200.
- `.env` values `LLM_REASONING_EFFORT`, `API_TIMEOUT`, `WHATSAPP_USE_PAIRING_CODE`, `BAILEYS_LOG_LEVEL` never reached the container (missing from compose).
- Entrypoint DB check broke on passwords containing `'` (credentials now read from env inside Python).
- `reasoning_effort` was sent to every model; now only `gpt-oss*`. `groq>=0.28.0` (first version that supports it).
- wwebjs bot logged "Attempting to reconnect" but never did; it now exits so the container restarts it.
- Disappearing / view-once messages were ignored by the Baileys bot.
- Long chart captions (>1000 chars) now sent as separate text; `**bold**` converted to WhatsApp `*bold*`.
- Logged-out cleanup no longer tries to delete the bind-mounted auth dir itself; `uncaughtException` now exits non-zero.
- Chart titles no longer contain emoji (matplotlib rendered boxes + warnings). "per monthly" wording fixed.
- Postgres compatibility: `EXTRACT(...)::numeric` before `ROUND` (older PG versions).

**Security**
- API port is now published on `127.0.0.1` only (`API_BIND=0.0.0.0` to override). The API has no auth.
- CORS no longer `*` + credentials (`CORS_ORIGINS` to extend).
- The login QR is no longer sent to api.qrserver.com unless `WHATSAPP_QR_LINK=true`.

**Tests:** 123 pass (new: MAD=0, score clamp, reasoning_effort, API 400, CORS, emoji stripping). 5 live-Groq tests need network access.
