# candidateSearch

Source candidates for job roles via APIs and AI search, then rank them per role.

- `backend/`: FastAPI + PostgreSQL (Python 3.13)
- `frontend/`: React + Vite + TypeScript + Tailwind
- `docs/`: [developer guide](docs/guide/README.md) (start here), [RULES.md](docs/RULES.md), [LEARNINGS.md](docs/LEARNINGS.md)

## First-time setup

### Database
Create the app database and the test database (enter your Postgres password when asked):
```powershell
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres -h localhost candidate_search
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres -h localhost candidate_search_test
```
Tests always use `<your db name>_test` (derived from `backend/.env`), or `TEST_DATABASE_URL` if set. They never touch the dev database.

### Backend
```powershell
cd backend
py -V:3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env   # then set the real password in DATABASE_URL
.venv\Scripts\alembic.exe upgrade head
```

### Frontend
```powershell
cd frontend
npm install
```

## Run (two terminals)
```powershell
# Terminal 1: API on http://localhost:8010  (docs at /docs)
cd backend; .venv\Scripts\uvicorn.exe app.main:app --reload --port 8010

# Terminal 2: UI on http://localhost:5180
cd frontend; npm run dev
```
The header shows **API online** when the API and database are both reachable.

| Page | URL |
|---|---|
| Candidate form | http://localhost:5180/apply |
| Staff sign in | http://localhost:5180/login |
| Candidate management (search / add / edit / delete) | http://localhost:5180/admin/candidates |
| Job roles (list / add / edit / close) | http://localhost:5180/jobs |
| Staff accounts (admins only) | http://localhost:5180/admin/users |
| Change your password | http://localhost:5180/account/password |
| Privacy notice (placeholder) | http://localhost:5180/privacy |
| API docs | http://localhost:8010/docs |

## Staff accounts
Create the first admin (asks for the password twice; minimum 12 characters):
```powershell
cd backend
.venv\Scripts\python.exe -m app.cli create-admin --email you@company.com --name "Your Name"
# add --role recruiter for a recruiter account (can search/add/edit, cannot delete)
```
Admins manage the other accounts at /admin/users: add a recruiter (or another admin) with a temporary password, reset a password, deactivate or reactivate. A temporary password must be changed at first sign-in: until then the API refuses everything except GET /auth/me, sign-out and change-password, and the app sends the person to /account/password. Deactivating or resetting signs the person out everywhere at once. Anyone can change their own password from the user menu (**Change password**); that signs out their other sessions.

## Embeddings (Phase 2)
Every saved candidate gets a vector embedding of their redacted search document (pgvector, `text-embedding-3-small`).
Set `OPENAI_API_KEY` in `backend/.env`. Without a real key, saving a candidate still works but nothing is embedded until a key is set and the API restarts. OpenAI is the only provider (tests mock its HTTP layer).

pgvector must be installed in Postgres; the migration runs `CREATE EXTENSION IF NOT EXISTS vector`.

**How it works.** There is no queue. Saving a candidate **or a job role** changes its redacted `search_document`, so the document's hash no longer matches the hash stored with its embedding. Every 2 seconds the API runs a **stale scan**: it finds up to 64 jobs, then up to 64 candidates, whose hash differs or that have no embedding yet, embeds them in one OpenAI request each, and stores the vectors. An identical re-save or a change to an unembedded field (phone, email) changes nothing, so it costs nothing. Job roles use the same model and dimensions as candidates; calls are metered as `candidate_embedding` or `job_embedding` on the AI spending page.

Failures go to `embedding_failures` / `job_embedding_failures`. A temporary OpenAI error is retried after 30 s, 2 min, 8 min and 32 min, then left until the text changes; a rejected input (400) is not retried until the text changes. While the AI budget is used up, the scan does not run at all.

```powershell
cd backend
.venv\Scripts\python.exe -m app.cli embed-backfill   # embed everything stale now and exit (no server needed); logs tokens + cost
```
`/ready` reports `database` and `pgvector`.

## Background tasks
The API runs one background runner (`MAINTENANCE_IN_API=true`): the stale scan above every 2 s (only when an OpenAI key is set), pruning expired rate-limit hits every 10 minutes, and deleting expired login sessions every hour. A failing task (for example the database restarting) is logged and retried after 60 s. On shutdown the API waits up to 45 s for an in-flight OpenAI call. Set `MAINTENANCE_IN_API=false` to run it as its own process instead:
```powershell
cd backend
.venv\Scripts\python.exe -m app.cli maintenance          # runs until Ctrl+C
.venv\Scripts\python.exe -m app.cli maintenance --once   # every task once, then exit (non-zero if one failed; for cron)
```
Rate limits (sign-in and change-password failures, admin account writes, the public form) are stored in Postgres (`rate_limit_hits`), so they're exact and shared by every API process. Keys are an HMAC of the email/IP/user id under `RATE_LIMIT_KEY_SECRET`; local and test use a built-in development value, staging and production require a real one (32+ random characters, the same in every process).

## Dev data
```powershell
cd backend
.venv\Scripts\python.exe -m scripts.seed_candidates --count 1000   # synthetic candidates; safe to re-run; refuses in production
.venv\Scripts\python.exe -m scripts.generate_countries_ts          # regenerate the frontend country list
```

## Checks
```powershell
# backend
cd backend
.venv\Scripts\pytest.exe
.venv\Scripts\ruff.exe check . ; .venv\Scripts\ruff.exe format --check .
.venv\Scripts\mypy.exe app migrations scripts tests conftest.py

# frontend
cd frontend
npm test ; npm run lint ; npm run build
npm run test:e2e   # Playwright; starts its own API on 8011 + UI on 5181 against the test DB
```

## Migrations
```powershell
cd backend
.venv\Scripts\alembic.exe revision --autogenerate -m "add candidates table"
.venv\Scripts\alembic.exe upgrade head
```
Models in any `app/features/<name>/models.py` are picked up automatically.
