# 9. Testing and debugging

## Running the tests

```powershell
# Backend (from backend/)
.venv\Scripts\pytest.exe                         # everything
.venv\Scripts\pytest.exe app/features/jobs       # one feature's unit tests
.venv\Scripts\pytest.exe tests/integration -k semantic   # integration tests matching a name
.venv\Scripts\pytest.exe -x --lf                 # stop at first failure, rerun last failures

# Frontend (from frontend/)
npm test                    # vitest
npm run test:e2e            # Playwright: starts its own API (8011) and Vite (5181)
```

Don't run pytest and e2e at the same time: both use the test database, and one's cleanup breaks the other.

## Where tests live

| Kind | Where | Database | Speed |
|---|---|---|---|
| Unit | `backend/app/features/<f>/tests/`, `backend/app/core/tests/`, `backend/app/shared/tests/` | none, or the test DB | fast |
| Integration | `backend/tests/integration/` | real Postgres test DB, migrated with Alembic | slower |
| Frontend unit/component | next to the component, `*.test.tsx` | none (fake API) | fast |
| End-to-end | `frontend/e2e/` | test DB via a real API | slowest |

## How the backend test setup works

`backend/conftest.py` runs **before** any app code is imported. It sets:

| Variable | Value | Why |
|---|---|---|
| `ENVIRONMENT` | `test` | |
| `DATABASE_URL` | `<your dev db name>_test`, or `TEST_DATABASE_URL` if set | Tests never touch your dev data. |
| `OPENAI_API_KEY` | `sk-test-not-a-real-key` | Your real key in `.env` is never loaded. |
| `MAINTENANCE_IN_API` | `false` | Tests call background functions directly instead. |

Fixtures you'll use:

| Fixture | What it gives you |
|---|---|
| `forbid_real_network` (automatic) | Any real HTTP request fails the test. `pytest.fail` raises a `BaseException`, which the OpenAI SDK's retry loop can't swallow. |
| `openai_mock` (automatic) | The **real** embedding provider with its HTTP layer replaced by a mock that returns deterministic vectors. You can inspect what was sent and make it fail. |
| `openai_provider` | Build extra providers on the same mock (another model, retries). |
| `client` | An `httpx.AsyncClient` that calls the app in-process (no server). |
| `clean_database` (automatic, integration) | Migrates once per run, then `TRUNCATE`s every table before each test. |
| `admin_client`, `recruiter_client` | A client already signed in as an admin / recruiter. |
| `db_session` | A session for setting up or checking data directly. |

Helpers in `tests/integration/conftest.py`: `create_staff`, `login`, `signed_in_client` (a second browser), `create_job`.

For the chat LLM, integration tests install a mocked client with `use_llm_client(...)`; the mock reads the candidates out of the prompt and answers per profile, so the real SDK parsing runs.

### A typical integration test

```python
async def test_recruiter_cannot_delete_a_candidate(recruiter_client: AsyncClient) -> None:
    candidate_id = await _create_candidate(...)

    response = await recruiter_client.delete(f"/api/v1/admin/candidates/{candidate_id}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
```

Rules:

- One behaviour per test, named as a sentence.
- Check the error `code`, not just the status.
- Every bug fix gets a test that fails without the fix.
- A known bug you can't fix yet may be recorded as `@pytest.mark.xfail(strict=True)`; `strict` makes the suite fail when it starts passing, so you remember to remove the marker.
- Never delete or loosen a test to make it pass.

## Debugging tips

### "The server is down" / every login is a 500
Check the database is migrated: `alembic current` vs `alembic heads`. The dev server reloads on every save, so new code that reads a new column fails until you run `alembic upgrade head`.

### A request fails with 403 `csrf_failed`
Non-GET requests need the header `X-Requested-With: fetch`. The frontend's `apiRequest` adds it; curl and test clients must add it themselves.

### Search answers 503
No usable `OPENAI_API_KEY` (blank or the `sk-CHANGE_ME` placeholder count as missing). Check `backend/.env` and restart the API.

### Search answers 402
The AI budget is used up. Raise it on the AI spend page (admin).

### "Find candidates" stays disabled
The job's embedding isn't ready. The job page shows its status:

| Status | Meaning |
|---|---|
| pending | Waiting for the next scan (a few seconds), or retrying after a temporary error. |
| failed | OpenAI rejected the text, or 5 temporary failures. Edit the job to retry. |
| budget_blocked | Budget used up. |

No key at all means nothing is ever embedded; the API logs `embedding_disabled` at startup.

### Following one request through the logs
Every log line of a request carries the same `request_id`, also returned in the `X-Request-ID` response header. Search the logs for it.

### What did the AI calls cost?
The AI spend page, or the `ai_usage_events` table: one row per call with tokens, cost and status (`succeeded`, `failed`, `blocked`). Each call also logs `ai_call_recorded`.

### Looking at the database
```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost candidate_search
```
Useful queries:
```sql
-- candidates without an up-to-date embedding
SELECT c.id FROM candidates c
LEFT JOIN candidate_embeddings e ON e.candidate_id = c.id
WHERE e.id IS NULL OR e.content_hash <> encode(sha256(convert_to(c.search_document, 'UTF8')), 'hex');

-- recent embedding failures
SELECT candidate_id, attempts, last_error, updated_at FROM embedding_failures ORDER BY updated_at DESC LIMIT 20;

-- spend so far
SELECT sum(cost_usd) FROM ai_usage_events;
```

### Test-only traps (from LEARNINGS)
- `capsys` and structlog don't mix: structlog caches loggers bound to the captured stdout. Patch the module's `logger` with a recording stub instead.
- Settings in tests: use `Settings(_env_file=None, ...)`, or your `.env` leaks in.
- In PowerShell, `$env:OPENAI_API_KEY = ''` *deletes* the variable, so the `.env` key loads. Use `'sk-CHANGE_ME'` to simulate "no key".
- Playwright matches accessible names as substrings; use `exact: true` when names can overlap.

Back to the [guide index](README.md).
