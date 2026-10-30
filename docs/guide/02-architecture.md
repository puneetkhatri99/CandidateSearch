# 2. Architecture

## Organised by feature, not by layer

Most tutorials put all routers in one folder, all models in another, and so on. This project does the opposite: **each business capability gets one folder with everything it needs.**

```
backend/app/features/
  auth/             staff login, sessions, staff accounts
  candidates/       candidate profiles: create, edit, list, delete
  jobs/             job roles
  embeddings/       turning search documents into vectors, finding nearest vectors
  ai_usage/         AI budget, metering, spend history
  semantic_search/  search by meaning and job matching (hybrid fetch + LLM ranking)
  audit/            the audit log (who did what)
  health/           /health and /ready probes
```

Why: when you work on jobs, everything about jobs is in one place. You don't jump across five folders.

## Inside a feature

Each feature uses the same file names. Not every feature needs every file.

| File | Job | May contain |
|---|---|---|
| `__init__.py` | The **public API** of the feature. Other features import only what is listed here. | Re-exports |
| `router.py` | HTTP layer. Reads the request, calls one service function, returns the result. | No business rules |
| `schemas.py` | Pydantic models for request bodies, query params and responses. | Validation rules |
| `models.py` | SQLAlchemy ORM classes (database tables). | Columns, indexes, CHECK constraints |
| `service.py` | **Business logic.** Opens transactions, applies rules, calls the repository, writes audit events. | The interesting code |
| `repository.py` | **All SQL** for this feature. | Queries only, no rules |
| `exceptions.py` | Errors this feature raises, each with an HTTP status and code. | `AppError` subclasses |
| `prompts/` | LLM prompt files, versioned by name (`rank_v3.md`). | Text |
| `tests/` | Unit tests for this feature. | Tests |

### The three layers

```
router  →  service  →  repository  →  database
```

- A router never runs SQL and never decides rules.
- A service never builds HTTP responses.
- A repository never decides rules and never opens a transaction (the service does).
- Never skip a layer (router → repository) and never go backwards (repository → service).

A tiny real example, deleting a candidate:

```python
# candidates/admin_router.py: HTTP only
@router.delete("/{candidate_id}", status_code=204)
async def delete_candidate(candidate_id: uuid.UUID, session: SessionDep, actor: AdminUser) -> None:
    await service.delete_candidate(session, candidate_id, actor)

# candidates/service.py: rules + transaction + audit
async def delete_candidate(session, candidate_id, actor) -> None:
    if not actor.is_admin:
        raise ForbiddenError("Only admins can delete candidates.")
    async with session.begin():
        if not await repository.delete_candidate(session, candidate_id):
            raise NotFoundError("Candidate not found.")
        _audit(session, actor, "candidate.delete", candidate_id)

# candidates/repository.py: SQL only
async def delete_candidate(session, candidate_id) -> bool:
    result = await session.execute(
        delete(Candidate).where(Candidate.id == candidate_id).returning(Candidate.id)
    )
    return result.scalar_one_or_none() is not None
```

Notice the admin check happens twice: the router uses `AdminUser` (a dependency), and the service checks `actor.is_admin` again. The service check is the one that counts, because services can be called from places other than this router.

## Who may import whom

```
            main.py, maintenance.py, cli.py     (wiring only)
                         │
                         ▼
                    features/*
          (each imports others only via __init__.py)
                         │
                         ▼
              core/          shared/
       (never import from features)
```

Rules:

1. A feature imports another feature **only through its `__init__.py`**. Example: `semantic_search/service.py` does `from app.features import candidates` and then calls `candidates.get_rankable_candidates(...)`. It never imports `candidates.models` or `candidates.repository`.
2. `core/` and `shared/` never import from `features/`.
3. No circular imports between features.

### Who calls whom between features

```
semantic_search ──► candidates   (get_rankable_candidates, full_text_candidate_ids, candidate_ids_passing)
       │        ──► embeddings   (nearest_candidates_to_vector, load_job_vector)
       │        ──► jobs         (get_job_brief)
       │        ──► ai_usage     (metered_call)
       │        ──► audit        (record_event)
jobs ─────────► embeddings   (get_job_embedding_status)
     ─────────► auth         (get_full_names)
embeddings ───► ai_usage     (metered_call, has_budget, budget_used_up)
candidates, jobs, auth, ai_usage ──► audit (record_event)
```

### The one exception

`embeddings/repository.py` reads the `candidates` and `jobs` tables directly (only the `id` and `search_document` columns, read-only). It uses a lightweight `sqlalchemy.table()` reference in `embeddings/targets.py`, not the other features' models.

Why: finding stale documents means joining `candidates` with `candidate_embeddings` and hashing every document **in SQL**. Going through the candidates feature would load every document into Python. This exception is written down in LEARNINGS. Never add personal columns (name, email) to that table reference.

## `core/` vs `shared/`

| Folder | Holds | Examples |
|---|---|---|
| `core/` | Infrastructure every app needs, no business knowledge. | Settings, DB engine, error format, logging, middleware, OpenAI clients, rate limiter, background runner, prices |
| `shared/` | Small business-flavoured helpers used by 2+ features. | Validation building blocks, redaction of personal data, skill and city spellings |

Details of every function: [04-backend-core.md](04-backend-core.md).

## What happens on every request

```
browser
   │
   ▼
RequestContextMiddleware   adds X-Request-ID, logs "request_completed" (path only, never the query string)
CORSMiddleware             allows the frontend origin (localhost:5180)
BodySizeLimitMiddleware    rejects bodies over 64 KiB with 413
UnhandledErrorMiddleware   turns any unexpected exception into a clean 500 JSON body
   │
   ▼
router function
   ├─ Depends(get_session)       one database session for this request
   ├─ Depends(auth dependency)   who is calling (if the route needs a user)
   └─ Pydantic validates the body / query → 422 if wrong
   │
   ▼
service function   (opens `async with session.begin():`, commits at the end of the block)
   │
   ▼
repository functions (SQL)
```

Middleware order matters. In `main.py`, the middleware added **first** is the **innermost**. `UnhandledErrorMiddleware` is added first so that even a 500 still passes through CORS and request-context (it gets CORS headers and an `X-Request-ID`).

### Every error has the same shape

```json
{ "error": { "code": "candidate_exists", "message": "A profile with this email already exists.", "details": {} } }
```

Services raise subclasses of `AppError` (in `core/errors.py`); a handler turns them into this body with the right status code. You never build error responses by hand.

## Transactions

- `get_session` gives a session that is **not** in a transaction.
- Each service function opens its own: `async with session.begin(): ...`. Leaving the block commits; an exception rolls back.
- An authenticated request therefore usually runs two short transactions: one to check the session cookie, one for the real work.
- **No transaction is ever held open while waiting for OpenAI.** `metered_call` uses one short transaction before the call and one after.
- Audit events are added inside the same transaction as the change they describe, so either both are saved or neither.

## The database

| Table | What it holds | Written by |
|---|---|---|
| `users` | Staff accounts (email, argon2 hash, role, active flag) | auth |
| `user_sessions` | Login sessions; stores **sha256 of the cookie token**, never the token | auth |
| `audit_events` | Who did what, when; never personal values | audit (called by all features) |
| `candidates` | Profiles, plus `search_document`, `search_tsv` (full-text, computed by Postgres), `version` | candidates |
| `candidate_experiences`, `candidate_educations` | Child rows of a candidate | candidates |
| `jobs` | Job roles, plus `search_document`, `version` | jobs |
| `candidate_embeddings`, `job_embeddings` | One vector per entity per model, plus the hash of the text it was made from | embeddings |
| `embedding_failures`, `job_embedding_failures` | Dead letters: failed embeddings, attempts, last error | embeddings |
| `ai_budget` | The spending limit (one row) | ai_usage |
| `ai_usage_events` | One row per AI call: tokens, cost, status | ai_usage |
| `rate_limit_hits` | One row per counted attempt (login failures, form submits) | core/rate_limit |

Every table has `id` (UUID), `created_at` and `updated_at` (from `TimestampedModel` in `core/db.py`).

Every schema change is an Alembic migration in `backend/migrations/versions/`. Never edit a migration that has already been applied to the dev database; add a new one.

## Background work

There is one background runner (`core/maintenance.py`). It starts inside the API when the app starts and runs these tasks (list in `app/maintenance.py`):

| Task | Every | Does |
|---|---|---|
| `embeddings.embed_stale` | 2 s | Embeds up to 64 stale jobs, then 64 stale candidates |
| `core.prune_rate_limit_hits` | 10 min | Deletes expired rate-limit rows |
| `auth.prune_expired_sessions` | 1 h | Deletes expired sessions |

It can also run alone: `python -m app.cli maintenance`. Set `MAINTENANCE_IN_API=false` to stop the API from running it.

Next: [03-flows.md](03-flows.md).
