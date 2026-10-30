# API flows

> **Outdated (2026-10-30):** this file predates search by meaning, job matching and SSE. The current, maintained version is [guide/03-flows.md](guide/03-flows.md).

How every HTTP endpoint, background job and CLI command moves through the code, from the request down to the database.

- Paths are relative to `backend/app/`. Line numbers are as of 2026-10-29; Phase 3 (jobs, user admin) is built, so they may have drifted. Function names are the stable reference.
- Every backend feature follows `router → service → repository` (see [RULES.md](RULES.md) §2). The router parses input and maps output, the service holds the business rules and opens transactions, and the repository runs the SQL.

## Contents
1. [Every request: middleware, auth, errors](#1-every-request)
2. [Health](#2-health)
3. [Auth: login, logout, me, change password](#3-auth)
4. [Admin: users](#4-admin-users) *(Phase 3)*
5. [Candidates: public intake](#5-public-candidate-intake)
6. [Admin: candidates](#6-admin-candidates)
7. [Jobs](#7-jobs) *(Phase 3)*
8. [AI usage and budget](#8-ai-usage-and-budget)
9. [Background: embedding worker](#9-background-embedding-worker)
10. [AI metering: `metered_call`](#10-ai-metering-metered_call)
11. [CLI commands](#11-cli-commands)
12. [Tables](#12-tables)
13. [Known gaps found while tracing](#13-known-gaps-found-while-tracing)

---

## 1. Every request

```
client
  │
  ▼
RequestContextMiddleware      core/middleware.py   request_id (X-Request-ID), access log (path only, no query)
CORSMiddleware                main.py              origins from settings.cors_origins (localhost:5180)
BodySizeLimitMiddleware       core/body_limit.py   64 KiB cap → 413 payload_too_large
  │
  ▼
router function ── Depends(...) ──► get_session (core/db.py)        one AsyncSession per request
                                └─► auth dependencies (below)      if the route needs a user
  │
  ▼
service function  (opens its own `async with session.begin()`)
  │
  ▼
repository functions (SQL)
```

**App start and stop:** `lifespan` in [main.py](../backend/app/main.py).
- **Startup:** `start_background_maintenance(maintenance_tasks())` ([core/maintenance.py](../backend/app/core/maintenance.py), task list in [app/maintenance.py](../backend/app/maintenance.py)) starts the one background runner as an asyncio task inside the API ([section 9](#9-background-tasks-embedding-and-pruning)). It is skipped when `MAINTENANCE_IN_API=false`. Without a usable API key the embedding task is left out (log `embedding_disabled`) and the API still starts.
- **Shutdown:** `stop_background_maintenance()` waits up to 45 s for the in-flight task, then `close_embedding_provider()`, then `get_engine().dispose()`.

**Database session:** `get_session` / `SessionDep` in [core/db.py](../backend/app/core/db.py).
- It yields one `AsyncSession`. It never begins or commits anything itself.
- Each service function opens `async with session.begin()`. An authenticated request therefore usually runs **two transactions**: the session lookup, then the service work.

**Auth chain:** [auth/dependencies.py](../backend/app/features/auth/dependencies.py).

| Dependency | What it does | Error |
|---|---|---|
| `require_fetch_header` | CSRF guard. Any method other than GET/HEAD/OPTIONS must send `X-Requested-With: fetch`. | 403 `csrf_failed` |
| `get_session_context` (`SessionUser`) | Reads the `cs_session` cookie, then `auth.service.resolve_session` → `repository.get_live_session`: `user_sessions` JOIN `users`, unexpired and active. If less than half the TTL remains, it extends the session and re-sets the cookie. | 401 `not_authenticated` |
| `get_auth_context` (`CurrentUser`) | Same as above, plus it blocks users who must change their password. | 403 `password_change_required` |
| `require_role("admin")` (`AdminUser`) | Admin only. | 403 `forbidden` |

The CSRF check runs inside `get_session_context`, so every authenticated write route gets it, not only login.

**Errors:** [core/errors.py](../backend/app/core/errors.py). Every error has the same shape: `{"error": {"code", "message", "details"}}`.
- `AppError` subclasses use their own status and code: `NotFoundError` 404, `NotAuthenticatedError` 401, `ForbiddenError` 403, `ConflictError` 409, `RateLimitedError` 429 (with `Retry-After`).
- Pydantic validation gives 422 `validation_error`, with `details.errors=[{loc,msg,type}]` and the input not echoed back.
- Anything else gives 500 `internal_error`.

**Rate limiting:** [core/rate_limit.py](../backend/app/core/rate_limit.py). It is an in-memory sliding window, per process.
- The `rate_limit(scope, limit, window)` dependency protects public candidate intake.
- Login and change-password call the limiter by hand and count failures only.

**Validation base:** `StrictModel` in [shared/validation.py](../backend/app/shared/validation.py). It rejects unknown fields (422 `extra_forbidden`), strips whitespace and rejects NUL characters in every field.

**Audit:** `audit.service.record_event` ([audit/service.py](../backend/app/features/audit/service.py)) adds an `audit_events` row inside the caller's transaction. It is only written if that transaction commits.

---

## 2. Health

| | `GET /health` | `GET /ready` |
|---|---|---|
| Auth | none | none |
| Chain | `health.router.liveness` returns `{"status":"ok"}` | `health.router.readiness` → `service.check_readiness` → `_check_database` (`repository.ping_database`: `SELECT 1`) → `_check_pgvector` (`repository.pgvector_installed`: `pg_extension`) |
| Response | `HealthStatus` 200 | `HealthStatus` 200, or 503 `{"status":"unavailable","checks":{database,pgvector}}` |
| Tables | none | `pg_extension` (read) |

---

## 3. Auth

Router: [auth/router.py](../backend/app/features/auth/router.py). Service: [auth/service.py](../backend/app/features/auth/service.py). Repository: [auth/repository.py](../backend/app/features/auth/repository.py).

### `POST /api/v1/auth/login`
- **Guards:** CSRF header. Failure rate limits, giving 429: 5 failures per 15 min per (email, IP), and 20 per 15 min per email across all IPs.
- **Request / response:** `LoginRequest {email, password}` → `StaffUser` (200). Sets the `cs_session` cookie (httpOnly, SameSite=Lax, 8 h, Secure in staging and production).
```
login (router)
  ├─ failure_slot("login_failure", email, ip)              → 429 if over (5 / 15 min)
  ├─ failure_slot("login_failure_account", email)          → 429 if over (20 / 15 min)
  └─ service.authenticate                                  ── one transaction
       ├─ repository.get_user_by_email
       ├─ (unknown/inactive) passwords.burn_verification_time  → 401 invalid_credentials (equal timing)
       ├─ passwords.verify_password  (argon2, in a thread)  → 401 invalid_credentials
       ├─ passwords.needs_rehash → hash_password            (silent upgrade)
       ├─ repository.add_session  (sha256(token) stored, never the token)
       ├─ user.last_login_at = now
       └─ record_event("auth.login")
  ├─ on 401: both slots are kept; on any other outcome both are released
  └─ set_session_cookie
```
- **Tables:** reads `users`; writes `user_sessions`, `users` and `audit_events`.

### `POST /api/v1/auth/logout`
- **Guards:** `SessionUser` (CSRF included). **Response:** 204, and the cookie is cleared.
- **Chain:** `logout` → `service.logout` → `repository.delete_session(hash_token)`, then `record_event("auth.logout")`.

### `GET /api/v1/auth/me`
- **Guards:** `SessionUser`. It works even when a password change is pending, so the UI can send the user to the change page.
- **Chain:** auth dependency → `actor.to_staff_user()`. **Response:** `StaffUser`.

### `POST /api/v1/auth/change-password`
- **Guards:** `SessionUser` + CSRF. Failure rate limit per user.
- **Request:** `ChangePasswordRequest {current_password, new_password (12–200)}` → `StaffUser`.
```
change_password (router) → service.change_password
  ├─ new == current → 422 (type same_password)            no DB access
  ├─ hash_password(new)                                    outside the transaction
  └─ transaction
       ├─ repository.get_user(for_update=True)             SELECT … FOR UPDATE
       ├─ verify_password(current)                         → 400 invalid_current_password
       ├─ password_hash = new; must_change_password = False
       ├─ repository.delete_sessions_for_user(except current)   signs out other devices
       └─ record_event("auth.password_change")
```

---

## 4. Admin: users
*Phase 3.* Router: [auth/admin_router.py](../backend/app/features/auth/admin_router.py). All routes need `AdminUser`, and the service checks again with `_require_admin`.

| Endpoint | Chain | Writes | Audit | Notable errors |
|---|---|---|---|---|
| `GET /api/v1/admin/users?cursor&limit` | `list_users` → `service.list_users` → `_decode_after` (cursor) → `repository.list_users` (keyset on `created_at, id`, newest first) | none | none | 400 `invalid_cursor` |
| `POST /api/v1/admin/users` `{email, full_name, role, temporary_password}` → 201 | `create_user` → `service.create_user_by_admin` → `_insert_user(must_change_password=True)` → `repository.add_user` | `users` | `user.create` | 409 `user_exists`, 429 `rate_limited` (per admin, `limit_account_writes`) |
| `PATCH /api/v1/admin/users/{id}` `{role?, is_active?}` | `update_user` → `service.update_user` → demote or deactivate: `lock_admin_changes` (advisory lock) → `get_user(for_update)` → `count_active_admins` guard → apply changes → on deactivate: `delete_sessions_for_user` | `users`, `user_sessions` | `user.update`, only when something changed | 409 `cannot_modify_self`, 409 `last_admin`, 404 |
| `POST /api/v1/admin/users/{id}/reset-password` `{temporary_password}` | `reset_password` → `service.reset_password` → `get_user(for_update)` → new hash + `must_change_password=True` → `delete_sessions_for_user` | `users`, `user_sessions` | `user.password_reset` | 409 `cannot_modify_self`, 404, 429 `rate_limited` |

A role change applies on the target user's next request, because `resolve_session` reads the role from the database every time.

---

## 5. Public candidate intake

### `POST /api/v1/candidates`
Router: [candidates/router.py](../backend/app/features/candidates/router.py). Service: [candidates/service.py](../backend/app/features/candidates/service.py).
- **Guards:** no login. Rate limit of 5 per hour per IP (429). 64 KiB body cap. Honeypot field `website`.
- **Request:** `CandidateCreate` = `CandidateProfile` + `consent: true` + `website`. **Response:** `CandidateCreated {id, created_at}` (201, no personal data echoed).
- **Validation:** `CandidateProfile` in [candidates/schemas.py](../backend/app/features/candidates/schemas.py).
  - Lengths for every text field. Email is lower-cased. Country is normalised to ISO-2. Phone must be E.164.
  - `years_experience` 0–50. Skills: 1–50 tags. Summary: 50–3000 characters.
  - At most 15 experiences, with only one current. At most 10 educations. Experience dates are YYYY-MM and not in the future.
  - URLs: LinkedIn must be `linkedin.com/in/…`, GitHub must be `github.com/…`. A `\`, whitespace or `@` in the host is rejected.
```
submit_candidate (router)
  └─ service.create_candidate
       ├─ honeypot filled → return fake id, no DB write
       ├─ _new_candidate → _apply_profile
       │     ├─ copy fields, build experiences/educations
       │     ├─ search_document = build_search_document(profile)     search_document.py
       │     │     every field passes redact_identifiers (shared/redaction.py):
       │     │     emails, URLs, phones and the candidate's name are removed → this text is what gets embedded
       │     └─ lookup_text = build_lookup_text(profile)              lookup.py (name/email/skills; PII, never embedded)
       └─ transaction
             └─ repository.add_candidate        INSERT candidates + experiences + educations
```
- **Embedding:** nothing is queued. The new document has no vector, so the next stale scan picks it up ([section 9](#9-background-tasks-embedding-and-pruning)).
- **Errors:** duplicate email → 409 `candidate_exists`; 422 validation; 429; 413.
- **Audit:** none (anonymous submitter).

---

## 6. Admin: candidates
Router: [candidates/admin_router.py](../backend/app/features/candidates/admin_router.py). Every route needs `CurrentUser` (recruiter or admin); delete needs admin.

### `GET /api/v1/admin/candidates`: search and list
- **Query:** `CandidateSearchParams`.
  - Filters: `q`, `country`, `work_mode`, `min_years`, `max_years`, `skill`, `source`.
  - `sort` = `newest` (default), `name` or `experience`.
  - `limit` defaults to 25, maximum 100. `cursor`.
- **Response:** `CandidatePage {items: CandidateSummary[], next_cursor}`.
```
search_candidates (admin_router) → service.search_candidates
  ├─ normalize_tag(skill)
  ├─ _decode_after(cursor)   core/pagination.decode_cursor + repository.parse_sort_key   → 400 invalid_cursor
  └─ transaction → repository.search_candidates
        ├─ _apply_filters: each word of q → lookup_text ILIKE '%word%'   (trigram GIN index)
        │                  country =, work_modes @>, years range, skills @> (GIN), source =
        ├─ keyset: (sort_expr, id) > / < cursor
        └─ ORDER BY sort_expr, id LIMIT limit+1
  └─ encode_cursor(next) ; _to_summary per row
```

### `GET /api/v1/admin/candidates/{id}`
- **Chain:** `get_candidate` → `service.get_candidate` → `repository.get_candidate` (eager-loads experiences and educations) → `record_event("candidate.view")` → `to_detail`.
- **Response:** `CandidateDetail`. **Errors:** 404.

### `POST /api/v1/admin/candidates`: staff create
- **Request:** `StaffCandidateCreate` = profile + `consent_confirmed: true` → `CandidateDetail` (201).
- **Chain:** `service.create_candidate_by_staff` → `_new_candidate(source="admin")`, with the same `_apply_profile` as the public form. In one transaction: `repository.add_candidate` + `record_event("candidate.create")`.
- **Errors:** 409 `candidate_exists`.

### `PUT /api/v1/admin/candidates/{id}`: update
- **Request:** `CandidateUpdate` = the full profile + `version`.
```
service.update_candidate ── transaction
  ├─ repository.get_candidate(for_update=True)        SELECT … FOR UPDATE
  ├─ version mismatch → 409 version_conflict          (also on StaleDataError at flush)
  ├─ _apply_profile → changed field names; rebuild search_document + lookup_text
  ├─ flush                                            UPDATE … WHERE version = old  (version bumped)
  └─ record_event("candidate.update", changed_fields=[names only])
     (a changed search_document no longer matches its stored hash, so the stale scan re-embeds it)
```

### `DELETE /api/v1/admin/candidates/{id}` (admin only, returns 204)
- **Chain:** `service.delete_candidate` → `repository.delete_candidate` (`DELETE … RETURNING id`, 404 if missing) → `record_event("candidate.delete")`.
- **Cascades:** `ON DELETE CASCADE` removes experiences, educations, `candidate_embeddings` and `embedding_failures`.

---

## 7. Jobs
*Phase 3.* Router: [jobs/router.py](../backend/app/features/jobs/router.py). Service: [jobs/service.py](../backend/app/features/jobs/service.py). Every route needs `CurrentUser`. Only the creator or an admin can edit a job (`_can_edit`).

| Endpoint | Chain | Writes | Audit |
|---|---|---|---|
| `POST /api/v1/jobs` `JobCreate` → `JobDetail` 201 | `create_job` → `_apply` → `build_job_search_document` (redacted) → transaction: `repository.add_job` + `record_event` + `_to_detail`; a database CHECK violation becomes a 422 | `jobs`, `audit_events` | `job.create` |
| `GET /api/v1/jobs?status&cursor&limit` → `JobPage` | `list_jobs` → `_decode_after` → `repository.list_jobs` (keyset, newest first) → `auth.get_full_names` (one batched read of owner names) | none | none |
| `GET /api/v1/jobs/{id}` → `JobDetail` | `get_job` → `repository.get_job` → `_to_detail` (owner name + `get_job_embedding_status`: ready / pending / failed / budget_blocked) | none | none |
| `PATCH /api/v1/jobs/{id}` `JobPatch` (+`version`) → `JobDetail` | `update_job` → transaction: `get_job(for_update)` → `_can_edit` (403) → version check (409) → merge + `JobFields.model_validate` (422) → rebuild the search document → flush → `record_event` only if a field changed (a status change counts) → `_to_detail`; a database CHECK violation becomes a 422 `validation_error` | `jobs`, `audit_events` | `job.update` |

**Validation:** `JobFields` in [jobs/schemas.py](../backend/app/features/jobs/schemas.py) mirrors the database CHECK constraints.
- City is required for hybrid or onsite roles.
- Country is required when a city is set.
- `max_years ≥ min_years`.
- 1–20 must-have skills, with no skill in both must-have and nice-to-have.
- Description 100–10,000 characters.

Job vectors are created but not yet used for matching. That's Phase 4.

---

## 8. AI usage and budget
Router: [ai_usage/router.py](../backend/app/features/ai_usage/router.py). Service: [ai_usage/service.py](../backend/app/features/ai_usage/service.py).

| Endpoint | Guards | Chain | Tables |
|---|---|---|---|
| `GET /api/v1/ai-usage/summary` → `BudgetSummary` | `CurrentUser` | `get_summary` → `get_budget` + `get_spent` (sum of every event's cost) + `totals_by(model)` + `totals_by(operation)`. Computes remaining, percent used and `limit_reached` (spent ≥ limit). | reads `ai_budget`, `ai_usage_events` |
| `GET /api/v1/ai-usage/events?model&operation&status&cursor&limit` → `UsageEventPage` | `CurrentUser` | `list_events` → `_decode_after` → `repository.list_events` (filters, keyset newest first) | reads `ai_usage_events` |
| `PUT /api/v1/ai-usage/budget` `{limit_usd: 0–10000}` → `BudgetSummary` | `AdminUser` + CSRF | `update_budget` → transaction: `_ensure_budget` → set the limit if changed → `record_event("ai_budget.update", old/new)` → then `get_summary` | writes `ai_budget`, `audit_events` |

---

## 9. Background tasks: embedding and pruning
One runner ([core/maintenance.py](../backend/app/core/maintenance.py)) runs every periodic task. It runs **inside the API** by default ([section 1](#1-every-request)), or separately with `python -m app.cli maintenance`. The task list is in [app/maintenance.py](../backend/app/maintenance.py):

| Task | Every | What it does |
|---|---|---|
| `embeddings.embed_stale` | 2 s (`EMBEDDING_POLL_SECONDS`) | the stale scan below; only when an OpenAI key is set |
| `core.prune_rate_limit_hits` | 10 min | deletes rate-limit hits whose window has ended |
| `auth.prune_expired_sessions` | 1 h | deletes expired login sessions |

A task that raises (for example the database restarting) is logged as `maintenance_task_failed` and retried after 60 s; it never stops the others.

**The stale scan** turns saved documents into vectors. There is no queue: a save changes the `search_document`, so its hash no longer matches the one stored with its embedding. Code: [embeddings/service.py](../backend/app/features/embeddings/service.py), [embeddings/repository.py](../backend/app/features/embeddings/repository.py), [core/embeddings.py](../backend/app/core/embeddings.py).
```
embed_all_stale(provider)                   for target in (jobs, candidates)
  └─ embed_stale(target)
        ├─ ai_usage.has_budget?             spend ≥ limit → do nothing at all
        ├─ transaction: find_stale_ids (up to 64) + load_documents
        │     stale = no vector, or sha256(search_document) ≠ stored hash
        │     minus dead letters for the same text, except:
        │       temporary failures whose retry delay passed (30 s, 2 min, 8 min, 32 min; 5 tries)
        │       budget refusals (the budget has room again)
        └─ _embed_batch(64 texts)
              ├─ ai_usage.metered_call(call=provider.embed_documents(texts))   (section 10)
              │     └─ AsyncOpenAI.embeddings.create(model, input=[...], dimensions=1536)
              │          (texts cut to 24,000 chars; SDK retries 429/5xx up to 3×)
              │        → _parse: sort by index, check count/dims/finite
              ├─ success: transaction → upsert_embeddings (ON CONFLICT UPDATE) + clear_failures
              ├─ PermanentEmbeddingError, batch > 1 → retry each item alone (recursive)
              ├─ PermanentEmbeddingError, batch = 1 → record_failure (never retried for this text)
              ├─ TransientEmbeddingError → record_failure (attempts + 1; retried after the delay)
              └─ BudgetExceeded / UnknownModelPrice → record_failure(budget_exceeded | model_price_unknown),
                                                       stop sending for the rest of this run
```
- **Edited during the call:** the stored hash is of the text that was sent, so the newer text still looks stale and the next pass embeds it.
- **Two runners at once** (API plus a `maintenance` process) may embed the same document twice. That's harmless, just one wasted call.
- **Similarity:** `nearest_candidates_to_vector` → `nearest_neighbours` → `similarity_statement` (`embedding <=> :vector ORDER BY … LIMIT`, alone on the table so the HNSW index answers it). Used by search by meaning.

---

## 10. AI metering: `metered_call`
[ai_usage/service.py](../backend/app/features/ai_usage/service.py). This wraps **every** paid AI call (embeddings and search ranking), one call per batch. No transaction is open while OpenAI is working.

```
metered_call(provider, model, operation, trigger, item_count, call, tokens_of)
  ├─ transaction: _refusal
  │     ├─ _ensure_budget         default $5.00 if no row
  │     ├─ no price for the model → refuse (UnknownModelPriceError)
  │     ├─ spent ≥ limit          → refuse (BudgetExceededError)
  │     └─ refused → insert a "blocked" row, raise; `call` never runs
  ├─ result = await call()                     no transaction open
  ├─ success → insert one "succeeded" row      (input, output) = tokens_of(result), real cost
  └─ error   → insert one "failed" row, re-raise   cost 0 unless the response was billed
                                                  (exception's billed_tokens)
```
- **Prices:** [core/ai_pricing.py](../backend/app/core/ai_pricing.py). `text-embedding-3-small` is $0.02 per million tokens.
- **The cap can be overshot by one call.** The check and the record aren't atomic, so the last call that starts below the limit may go over it (at most about $0.01 for a 64-input embedding batch). After that, every call is refused. A call cancelled mid-flight isn't recorded.
- **`has_budget` / `budget_used_up`:** quick checks the stale scan and the job status use; `metered_call` does the authoritative check.

---

## 11. CLI commands
`python -m app.cli <command>`, defined in [cli.py](../backend/app/cli.py). Commands close the OpenAI client and the DB engine on exit.

| Command | Chain | Writes | Exit codes |
|---|---|---|---|
| `create-admin --email --name [--role] [--password-stdin]` | `_read_password` (strips BOM and CRLF) → `auth.service.create_user` → `_insert_user` → `repository.add_user` | `users` | 0; 1 weak password, existing user or mismatch; 2 bad arguments |
| `embed-backfill` | For jobs, then candidates: `embed_stale(trigger="cli")` in a loop until nothing is left (failures wait out their retry delay) or the budget refuses | `candidate_embeddings`, `job_embeddings`, `*_failures`, `ai_usage_events` | 0 (also when the budget blocks); 1 on no key or a crash |
| `maintenance [--once]` | `run_maintenance(maintenance_tasks())` ([section 9](#9-background-tasks-embedding-and-pruning)); `--once` runs every task once | as the tasks | 0; 1 if a task failed with `--once` |

---

## 12. Tables

| Table | Written by |
|---|---|
| `users` | login (`last_login_at`), change password, admin users, `create-admin` |
| `user_sessions` | login (insert), logout and password change/reset/deactivate (delete), any request (extend) |
| `audit_events` | every staff write, plus `candidate.view` |
| `candidates`, `candidate_experiences`, `candidate_educations` | public intake, staff create, update, delete |
| `candidate_embeddings` | stale scan, `embed-backfill` (1536-dim `vector`, HNSW cosine index) |
| `embedding_failures` | stale scan on failure (also paces retries); cleared on success |
| `jobs` | job create and update |
| `job_embeddings`, `job_embedding_failures` | same roles as the candidate equivalents, for jobs |
| `ai_budget` | `PUT /ai-usage/budget`, `_ensure_budget` |
| `ai_usage_events` | `metered_call`: one row per call, `succeeded` / `failed` / `blocked` |

---

## 13. Known gaps found while tracing
These came up while reading the code. **All twelve are fixed** (2026-10-30): items 5, 6, 7 and 12 in Phase 3, the rest in Phase 2c (item numbers in brackets; the phase docs were removed 2026-10-30). Items 7, 8, 10, 11 and 12 later became moot: the 2026-10-30 simplification removed the queue, reservations and the reaper (see LEARNINGS).

1. **500 responses** came from the outermost Starlette layer, so they lacked `X-Request-ID` and CORS headers. *Fixed in Phase 2c (item 1): `UnhandledErrorMiddleware` (`core/errors.py`) answers inside the stack.*
2. **The failure rate limits were not atomic** and lived in memory per process. *Fixed in Phase 2c (item 2): `core/rate_limit.py` stores hits in `rate_limit_hits`; `acquire_slot` counts and records under a per-key advisory lock, and `failure_slot` reserves a slot before the password check and releases it on success.*
3. **Logout with an already expired session** returned 401 without clearing the cookie. *Fixed in Phase 2c (item 3): `OptionalSessionUser`; logout is always 204 and clears the cookie (CSRF still required).*
4. **Expired `user_sessions` rows** were never cleaned up. *Fixed in Phase 2c (item 4): `core/maintenance.py` runs `auth.prune_expired_sessions` hourly (tasks composed in `app/maintenance.py`; `python -m app.cli maintenance`).*
5. **No "last admin" guard.** Two admins can demote each other at the same time and leave no admin. *Fixed in Phase 3 (`lock_admin_changes`, 409 `last_admin`).*
6. **Admin user endpoints have no rate limit,** and each call runs argon2. *Fixed in Phase 3 (`limit_account_writes`); Phase 2c item 2 moves it to the shared limiter.*
7. **Every candidate or job update queues an embedding job,** even when the search text didn't change (e.g. an email-only edit). The worker skips it at no AI cost, but the queue does extra work. *Fixed in Phase 3.*
8. **An edit made while a job is being embedded** makes the row due again at once, so a second worker could embed it in parallel. It's harmless, but it wastes one call. *Fixed in Phase 2c (item 5): `leased_until`; an edit keeps a live lease, and `_finish_jobs` → `release_superseded_jobs` makes the new generation due when the worker finishes.*
9. **The search/list endpoint returned names and emails without an audit event.** *Fixed in Phase 2c (item 6): `search_candidates(session, params, actor)` writes one `candidate.search` row per page (filter names, sort, page, limit, result count; never query text, values or ids).*
10. **The spending cap was checked against an estimate** that the real cost could exceed. *Fixed in Phase 2c (item 7): `core/ai_pricing.estimate_tokens_upper_bound` (UTF-8 bytes + 1 per input, capped at 8,192) can't be exceeded; an overrun would log `ai_usage_exceeded_estimate`.*
11. **A reservation could stay `reserved` forever.** *Fixed in Phase 2c (item 8): `ai_usage.reap_abandoned_reservations` (every 5 min) marks reservations older than 15 min `failed`/`abandoned` and keeps the estimate as spent; a late settle logs `ai_settle_skipped` instead of raising.*
12. **The CLI and the worker process targets in different orders.** `embed-backfill` does candidates first; the worker does jobs first. *Fixed in Phase 3 (`TARGET_ORDER`).*
