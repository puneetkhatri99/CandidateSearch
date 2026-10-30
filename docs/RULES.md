# Engineering Rules

These rules apply to all code in this repository. If a rule must be broken, explain why in the PR/summary and record it in [LEARNINGS.md](LEARNINGS.md).

## 1. Stack
- **Backend:** Python **3.13** (not 3.14+ until all deps ship wheels), FastAPI, Pydantic v2, SQLAlchemy 2.x (async, `asyncpg`), Alembic, structlog
- **Data:** PostgreSQL (local install, v18) + pgvector
- **Background jobs:** a Postgres-backed job queue: a jobs table written in the same transaction as the change that needs it (outbox), claimed with `FOR UPDATE SKIP LOCKED` by a long-running worker process (`python -m app.cli <worker>`), and periodic work runs on a timer inside that worker. Celery + Redis may return when volume needs it; that is a new decision, recorded in LEARNINGS.
- **Object storage:** S3-compatible (MinIO locally) for raw payloads and resumes
- **LLM:** OpenAI only, through the official `openai` SDK: `text-embedding-3-small` for embeddings and `gpt-5.4-mini` for LLM calls (ranking, extraction). No other LLM provider.
- **Frontend:** React 19 + Vite + TypeScript (strict) + Tailwind v4 (single-page app, talks to the API over HTTP)
- **Tooling:** `venv` + `pip` with `pyproject.toml` and a pinned `requirements.lock`; `ruff` (lint+format), `mypy --strict`, `pytest`; `npm`, `oxlint`, `vitest`, `playwright`
- **Runtime:** Docker for deployment (not yet installed locally; local dev runs services directly)
- **Local ports:** API `8010`, frontend `5180` (8000/5173 are used by another local project)

Do not add a new dependency without stating why an existing one isn't enough.

## 2. Feature-driven structure
Code is organized **by feature (business capability), not by technical layer**. Everything a feature needs lives in its folder.

```
backend/
  app/
    main.py                  # app factory, router registration only
    core/                    # cross-cutting infrastructure (no business logic)
      config.py              # pydantic-settings; the ONLY place env vars are read
      db.py                  # engine, session factory
      logging.py             # structured logging setup
      errors.py              # base exception types + handlers
      security.py            # auth, permissions
      llm.py                 # shared OpenAI chat client (structured outputs, timeouts)
      storage.py             # object storage client
    shared/                  # small, generic utilities used by 2+ features
    features/
      candidates/            # candidate profiles, dedupe, search
      sourcing/              # connectors to external data sources
        connectors/
          base.py            # Connector protocol
          github.py
          hn_hiring.py
          exa.py
          pdl.py
      ingestion/             # pipeline: raw -> parsed -> deduped -> embedded
      jobs/                  # job roles + structured requirements
      ranking/               # retrieval, LLM rerank, scoring, explanations
      feedback/              # recruiter actions used to tune ranking
  migrations/                # Alembic
  tests/
    integration/             # cross-feature + DB + external fakes
    e2e/

frontend/
  src/
    main.tsx                 # entry point only
    app/                     # app shell, routing, providers; thin, composes features
    features/
      <feature>/             # e.g. candidates/, jobs/, ranking/, system-status/
        components/          # React components for this feature
        hooks/               # data + state hooks
        api.ts               # calls to the backend for this feature
        types.ts             # TypeScript types mirroring backend schemas
        index.ts             # public exports; other code imports ONLY from here
    shared/
      api/client.ts          # fetch wrapper that parses the standard error body
      ui/                    # generic UI primitives
```
- Import with the `@/` alias (`@/features/jobs`), never deep relative paths across features.
- A feature never imports another feature's internals, only its `index.ts`.

### Inside a backend feature
```
features/<feature>/
  __init__.py      # public API of the feature (what others may import)
  router.py        # HTTP layer: parse request, call service, map response. No business logic.
  schemas.py       # Pydantic request/response/domain DTOs
  models.py        # SQLAlchemy ORM models
  service.py       # business logic; orchestrates repository/clients
  repository.py    # all DB queries for this feature
  worker.py        # background worker loop (thin: claims jobs, calls service functions)
  prompts/         # versioned LLM prompt files (if the feature uses an LLM)
  exceptions.py    # feature-specific errors
  tests/           # unit tests for this feature
```

### Boundary rules
- Dependency direction: `router → service → repository`. Never skip or reverse layers.
- A feature may import another feature **only through its `__init__.py`** (its public service functions/schemas), never its `models`, `repository`, or internals.
- `core/` and `shared/` never import from `features/`.
- No circular imports between features. If two features need each other, extract the shared piece or communicate via events/tasks.
- Create a new feature folder when a capability has its own data, rules, and API. Don't create one for a single helper.

## 3. Code quality
- Full type hints everywhere; `mypy --strict` and `tsc --strict` must pass. No `Any` without a comment explaining why.
- `ruff` and `oxlint` clean; formatting is automated, never debated.
- Functions do one thing; prefer pure functions in `service.py` that are easy to unit-test.
- Names describe intent (`rank_candidates_for_job`, not `process`). No abbreviations other than well-known ones.
- No dead code, commented-out code, or `print` statements.
- Comments explain *why*, not *what*.
- Use `async` for I/O paths (HTTP, DB). Never block the event loop with sync I/O.

## 4. Configuration & secrets
- All config comes from environment variables via `core/config.py` (pydantic-settings). No `os.getenv` elsewhere.
- Never commit secrets. Keep `.env.example` updated with every variable (dummy values).
- Separate settings for `local`, `test`, `staging`, `production`.

## 5. API design
- REST, versioned under `/api/v1`. Plural resource nouns (`/candidates`, `/jobs/{id}/rankings`).
- Validate all input with Pydantic; reject unknown fields on write endpoints.
- Cursor-based pagination for list endpoints; enforce a max page size.
- Consistent error body: `{ "error": { "code": "...", "message": "...", "details": {...} } }`.
- Long-running work (ingestion, ranking) returns `202 Accepted` with a task id; never block a request on it.
- Every endpoint requires auth unless explicitly public; check permissions in the service layer.

## 6. Database
- Every schema change is an Alembic migration; never edit a migration that has been applied in a shared environment.
- Every table has `id` (UUID), `created_at`, `updated_at`. Use soft delete only where the domain needs it.
- Add indexes for every foreign key and every column used in filters/sorts. Use HNSW indexes for pgvector columns.
- Avoid N+1 queries; use explicit eager loading.
- Writes that must succeed together go in one transaction.
- Use `UNIQUE` constraints to enforce dedupe keys (e.g. normalized email, profile URL); don't rely on app checks alone.

## 7. Ingestion & external sources
- Every source implements the `Connector` protocol in `sourcing/connectors/base.py` (`search(query) -> AsyncIterator[RawRecord]`).
- **Store raw payloads first** (object storage) before parsing, so we can reprocess without re-fetching.
- Every step is **idempotent**: re-running the same input must not create duplicates. Use deterministic keys (source + source_id).
- Retry transient errors only, with exponential backoff and jitter; never retry 4xx validation errors.
  - Where a provider's **official SDK** already retries with backoff (e.g. `openai`), configure its `max_retries` / `timeout` explicitly and do not stack another retry layer on top.
  - Use `tenacity` for everything else (raw HTTP connectors).
  - Retries that span longer outages belong to the job queue (backoff via `run_after`), not to in-process loops.
- Respect each provider's rate limits with a per-connector limiter; persist cursors so runs can resume.
- Failed items go to a dead-letter table with the error and payload reference; they are never silently dropped.
- Track field provenance (which source supplied each field and when).
- Only use sources with a clear legal basis and ToS that permit our use. **No LinkedIn scraping.**

## 8. LLM usage
- Use the shared client in `core/llm.py` (timeouts, retries, token + cost logging). Never instantiate the SDK elsewhere.
- Use **structured outputs** (tool/JSON schema) validated by Pydantic; never regex-parse free text.
- Prompts live in `features/<feature>/prompts/` as versioned files (`rerank_v3.md`). Persist `model`, `prompt_version`, and token usage alongside every LLM-produced result.
- Model choice by task: a small fast model for extraction/parsing, a stronger model only for top-N reranking.
- Never send protected attributes (name, gender, age, photo, ethnicity, religion, marital status) into ranking prompts; redact before scoring.
- Every ranking score must carry evidence/explanation that a recruiter can read.
- Prompt or model changes must be run against the evaluation set before merging.

## 9. Ranking quality & fairness
- Maintain a labeled golden set (job ↔ candidate relevance) in `backend/evals/`.
- Track NDCG@10 and precision@k; a change that lowers them needs explicit justification.
- Run periodic bias checks on ranking outcomes; log results.

## 10. Security & privacy
- Candidate data is PII: encrypt at rest, TLS in transit, least-privilege DB roles.
- Log IDs, never PII (no emails, phones, resume text in logs).
- Support candidate data deletion and export (GDPR/CCPA); define retention periods.
- Validate and size-limit file uploads; scan resumes before parsing.
- Follow OWASP Top 10; parameterized queries only (the ORM does this, never build SQL with f-strings).

## 11. Observability
- Structured JSON logs with `request_id` / `task_id` correlation.
- Metrics: candidates ingested / failed / deduped per source, LLM tokens and cost per run, ranking latency.
- Health (`/health`) and readiness (`/ready`) endpoints.
- Errors go to an error tracker (e.g. Sentry) with PII scrubbing.

## 12. Testing
- Unit tests live next to the feature (`features/<f>/tests/`); integration/e2e under `backend/tests/`.
- External APIs and LLM calls are **faked** in unit/integration tests (recorded fixtures); no network in CI.
- Integration tests run against a real Postgres (testcontainers or docker-compose), not SQLite.
- Minimum 80% coverage on `service.py` files; every bug fix ships with a regression test.
- Never delete or weaken a test to make it pass.

## 13. Git & delivery
- Small PRs, one concern each. Conventional commits (`feat(ranking): add hybrid retrieval`).
- CI must pass lint, type-check, tests, and migrations check before merge.
- Definition of done: code + tests + migration (if any) + `.env.example` updated + docs/architecture updated + LEARNINGS recorded (if any).
