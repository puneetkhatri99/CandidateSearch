# 1. The big picture

## What the app does

candidateSearch helps recruiters find the right people for a job.

- **Candidates** come in through a public form (`/apply`) or are typed in by staff.
- **Jobs** (job roles) are created by recruiters.
- **Search** finds candidates that fit a free-text description.
- **Job matching** finds candidates that fit a saved job.
- **Staff accounts** (admins and recruiters) sign in to use all of this.
- **AI spend** is tracked, with a hard limit (default $5).

Expected load: about 1,000 candidates and a few staff users. Many design choices (no queue, no Redis, scans instead of indexes in a few places) are made for that size and marked in the code with a `shortcut:` comment that says when to change them.

## Words you need

| Word | Meaning here |
|---|---|
| **Search document** | A plain-text version of a profile or job. Built by `build_search_document` (candidates) and `build_job_search_document` (jobs). Names, emails, phone numbers and URLs are removed from it, because it is sent to OpenAI. |
| **Embedding** | A list of 1,536 numbers that describes the *meaning* of a text. Texts with similar meaning have similar numbers. OpenAI's `text-embedding-3-small` model makes them. |
| **Vector** | Same thing as an embedding, as stored in the database. |
| **pgvector** | A Postgres extension that stores vectors and finds the nearest ones quickly. |
| **HNSW index** | The kind of index pgvector uses to find nearest vectors fast without comparing against every row. |
| **Cosine similarity** | A score for how close two vectors are. 1.0 means the same direction (same meaning). |
| **Full-text search** | Postgres's built-in keyword search (`tsvector`, `ts_rank_cd`). Good at exact words like "fastapi" or "noida". |
| **Hybrid search** | Running vector search and full-text search together and merging the results. |
| **RRF (reciprocal rank fusion)** | The simple formula used to merge the two result lists. See `fuse` in `semantic_search/ranking.py`. |
| **LLM** | A large language model. We use OpenAI `gpt-5.4-mini` to judge candidates. |
| **Structured output** | Asking the LLM to answer in an exact JSON shape (a Pydantic model), so we never parse free text. |
| **Hard filter** | A strict rule (min years, required skills, city, country, source). A candidate either passes or fails. |
| **Stale** | A candidate or job whose search document changed since its embedding was made, or that has no embedding yet. |
| **Dead letter** | A row that records a failed embedding, so it is not silently lost. Tables `embedding_failures` and `job_embedding_failures`. |
| **Metered call** | A paid AI call wrapped by `ai_usage.metered_call`, which checks the budget first and records the cost after. |
| **SSE (server-sent events)** | A way for the server to send several messages over one HTTP response. Used to show search progress step by step. |
| **Keyset pagination / cursor** | A way to page through a list by remembering the last row seen, instead of `OFFSET`. |

## The stack

| Part | Tool |
|---|---|
| API | Python 3.13, FastAPI, Pydantic v2 |
| Database | PostgreSQL 18 with pgvector, SQLAlchemy 2 (async, `asyncpg` driver), Alembic for migrations |
| AI | OpenAI only, through the official `openai` SDK |
| Logging | structlog (JSON logs, never personal data) |
| Passwords | argon2id |
| Frontend | React 19, Vite, TypeScript (strict), Tailwind v4, TanStack Query, react-hook-form, zod |
| Tests | pytest, vitest, Playwright |

There is **no** Redis, Celery or Docker. Background work runs inside the API process (see [03-flows.md](03-flows.md#4-embedding-in-the-background)).

## How to run it

Full setup is in the root [README](../../README.md). Short version:

```powershell
# Terminal 1: API on http://localhost:8010
cd backend; .venv\Scripts\uvicorn.exe app.main:app --reload --port 8010

# Terminal 2: UI on http://localhost:5180
cd frontend; npm run dev
```

Ports are 8010 and 5180, not the usual 8000 and 5173, because another project on this machine uses those.

`OPENAI_API_KEY` in `backend/.env` must be a real key for embedding and search to work. Without it, saving still works but nothing is embedded and search answers 503.

## Where things are

```
candidateSearch/
  backend/
    app/
      main.py           builds the FastAPI app
      cli.py            command-line tools (create-admin, embed-backfill, maintenance)
      maintenance.py    the list of background tasks
      core/             infrastructure: config, database, errors, logging, OpenAI clients
      shared/           small helpers used by several features
      features/         one folder per business capability
    migrations/         Alembic database migrations
    tests/              integration tests (real Postgres)
  frontend/
    src/
      app/              routing and layout
      features/         one folder per screen area
      shared/           API client, form helpers, UI pieces
  docs/                 rules, learnings, this guide
```

Next: [02-architecture.md](02-architecture.md).
