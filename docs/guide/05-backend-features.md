# 5. Backend features: every function

One section per feature in `backend/app/features/`. Inside each: endpoints, then service, then repository, then helpers. Private helpers start with `_`.

- [auth](#auth): staff login, sessions, staff accounts
- [audit](#audit): the audit log
- [candidates](#candidates): candidate profiles
- [jobs](#jobs): job roles
- [embeddings](#embeddings): vectors for candidates and jobs
- [ai_usage](#ai_usage): AI budget and metering
- [semantic_search](#semantic_search): search by meaning and job matching
- [health](#health): probes

---

## auth

### Endpoints

| Endpoint | Router function | Who |
|---|---|---|
| `POST /api/v1/auth/login` | `router.login` | anyone (CSRF header needed) |
| `POST /api/v1/auth/logout` | `router.logout` | anyone; always 204 |
| `GET /api/v1/auth/me` | `router.me` | `SessionUser` |
| `POST /api/v1/auth/change-password` | `router.change_password` | `SessionUser` |
| `GET /api/v1/admin/users` | `admin_router.list_users` | admin |
| `POST /api/v1/admin/users` | `admin_router.create_user` | admin, rate limited |
| `PATCH /api/v1/admin/users/{id}` | `admin_router.update_user` | admin |
| `POST /api/v1/admin/users/{id}/reset-password` | `admin_router.reset_password` | admin, rate limited |

### `auth/router.py`

| Function | What it does |
|---|---|
| `login` | Wraps `service.authenticate` in two `failure_slot`s (per email+IP, per email), then sets the session cookie. |
| `logout` | Deletes the session (live or dead), clears the cookie. Idempotent: always 204. |
| `me` | Returns the signed-in user. Works while a password change is pending, so the UI can redirect. |
| `change_password` | Wraps `service.change_password` in a `failure_slot` keyed by user id, so a stolen session can't brute-force the current password. |

### `auth/admin_router.py`

| Function | What it does |
|---|---|
| `limit_account_writes` | A dependency: at most 20 account creations/password resets per admin per hour (each runs argon2, which is CPU-heavy). |
| `list_users`, `create_user`, `update_user`, `reset_password` | Each calls the service function of the same name. |

### `auth/dependencies.py`

| Function | What it does |
|---|---|
| `session_ttl(settings)` | `timedelta(hours=8)` by default. |
| `set_session_cookie(response, token, settings)` | Sets `cs_session`: httpOnly (JavaScript can't read it), SameSite=Lax, Secure outside local. |
| `require_fetch_header` | CSRF guard. Non-GET requests must send `X-Requested-With: fetch`. A malicious site can't add custom headers to a cross-site request without passing CORS, so this blocks forged form posts. |
| `require_fetch_header_on_any_method` | The same check on GETs too, for routes that spend money. A link clicked on another site sends the `SameSite=Lax` cookie but can't add this header. Used by the whole `semantic_search` router. |
| `get_optional_session_context` | Reads the cookie, resolves the session, re-sends the cookie if it was extended. Returns `None` if there's no live session. |
| `get_session_context` | Same, but raises 401 if there's no session. |
| `get_auth_context` | Same, plus raises 403 `password_change_required` if the user must change their password. Behind `CurrentUser`, so every route is blocked by default until the password is changed. |
| `require_role(*roles)` | Builds a dependency that raises 403 unless the user has one of the roles. `AdminUser = require_role("admin")`. |

### `auth/service.py`

| Function | What it does |
|---|---|
| `hash_token(token)` | sha256 hex of the cookie token. Only the hash is stored, so a database leak doesn't give working sessions. |
| `_role`, `_context`, `_staff_user`, `_account` | Convert a `User` row into the shapes the API returns (`AuthContext`, `StaffUser`, `UserAccount`). |
| `authenticate(...)` | Checks the email and password, opens a session row, records `auth.login`. Unknown emails take the same time as real ones (`burn_verification_time`). Returns `(raw token, StaffUser)`. |
| `resolve_session(session, token, ip, ttl)` | Finds a live session and its active user. If less than half the lifetime is left, extends it (so active users stay signed in without a DB write on every request). Role and password-change flag come fresh from the user row. |
| `logout(session, token, actor)` | Deletes the session row; records `auth.logout` only if the session was live. |
| `prune_expired_sessions(session)` | Background task: deletes expired sessions 1,000 at a time. |
| `_check_password_length(password)` | 12 to 200 characters, else `WeakPasswordError`. |
| `_insert_user(...)` | Hashes the password, inserts the user, optionally records `user.create`. Duplicate email → `UserAlreadyExistsError` (409). |
| `create_user(...)` | Used by the `create-admin` CLI. |
| `get_full_names(session, ids)` | `{user_id: full_name}` in one query. Other features use it to show job owners without N+1 queries. |
| `change_password(session, actor, token, payload)` | Rejects new == current, hashes the new one **before** opening the transaction (argon2 is slow), locks the user row, verifies the current password, saves, clears the flag, signs out the user's **other** sessions, records the event. |
| `_require_admin(actor)` | 403 unless admin. Every admin service function calls it, not just the router. |
| `list_users(...)` | Newest-first page of accounts with a cursor. |
| `create_user_by_admin(...)` | Creates an account with a temporary password and `must_change_password=True`. |
| `update_user(session, actor, user_id, payload)` | Changes role and/or active flag. You can't change yourself. If the change removes admin rights, it first takes an advisory lock so two admins can't demote each other at the same moment, then refuses if this would leave zero active admins (`LastAdminError`), then re-checks that the actor is still an admin. Deactivating deletes all their sessions in the same transaction. |
| `reset_password(...)` | Sets a new temporary password, flags it for change, signs the user out everywhere. |

### `auth/passwords.py`

| Function | What it does |
|---|---|
| `hash_password(password)` | argon2id hash, run in a thread (`asyncio.to_thread`) so it doesn't block the event loop. |
| `verify_password(hash, password)` | `True`/`False`; never raises on a wrong password. |
| `needs_rehash(hash)` | `True` if argon2 settings changed since this hash was made. |
| `burn_verification_time(password)` | Verifies against a dummy hash so a failed login for an unknown email takes as long as for a real one. |

### `auth/repository.py`

| Function | What it does |
|---|---|
| `get_user_by_email`, `get_user(for_update)` | Load one user; `for_update` adds `SELECT ... FOR UPDATE`. |
| `lock_admin_changes` | `pg_advisory_xact_lock` on a fixed key; released at commit. |
| `count_active_admins(excluding)` | Active admins other than one user. |
| `add_user`, `add_session` | Insert and flush (so DB errors appear here, not at commit). |
| `list_users(after, limit)` | Keyset page, newest first, `limit + 1` rows. |
| `get_full_names(ids)` | One `IN` query. |
| `get_live_session(token_hash, now)` | Session JOIN user, not expired, user active. |
| `delete_session`, `delete_expired_sessions`, `delete_sessions_for_user(except_token_hash)` | Delete sessions. |

### `auth/schemas.py`

- `LoginRequest`, `ChangePasswordRequest`, `CreateUserRequest`, `UpdateUserRequest` (must change at least one field), `ResetPasswordRequest`, `UserListParams`: request shapes. Password models never strip whitespace, or the password an admin reads out would differ from the stored one.
- `StaffUser`, `UserAccount`, `UserAccountPage`: response shapes.
- `AuthContext`: the signed-in user as passed to services (`user_id`, `email`, `full_name`, `role`, `ip`, `must_change_password`, `is_admin`).

---

## audit

| Name | What it does |
|---|---|
| `AuditAction` | The list of allowed action names (`auth.login`, `candidate.view`, `job.match`, ...). A typo is a type error. |
| `record_event(session, action, entity_type, entity_id, actor_user_id, ip, details)` | Adds an `audit_events` row to the **caller's** transaction. It commits or rolls back with the change it describes. `details` must never hold personal values: field names and counts only. |

---

## candidates

### Endpoints

| Endpoint | Function | Who |
|---|---|---|
| `POST /api/v1/candidates` | `router.submit_candidate` | public, 5/hour per IP |
| `GET /api/v1/admin/candidates` | `admin_router.search_candidates` | staff |
| `GET /api/v1/admin/candidates/{id}` | `admin_router.get_candidate` | staff (audited as a view) |
| `POST /api/v1/admin/candidates` | `admin_router.create_candidate` | staff |
| `PUT /api/v1/admin/candidates/{id}` | `admin_router.update_candidate` | staff |
| `DELETE /api/v1/admin/candidates/{id}` | `admin_router.delete_candidate` | admin |
| `GET /api/v1/admin/candidates/bookmarks` | `admin_router.list_bookmarks` | staff (audited like a search). Declared before `/{id}`, which would otherwise read "bookmarks" as an id. |
| `PUT` / `DELETE /api/v1/admin/candidates/{id}/bookmark` | `admin_router.bookmark_candidate` / `unbookmark_candidate` | staff, 204 |

### `candidates/service.py`

| Function | What it does |
|---|---|
| `_experiences(profile)`, `_educations(profile)` | Build child rows from the request, keeping their order in `position`. |
| `_apply_profile(candidate, profile)` | Copies every field in `_PROFILE_FIELDS` onto the model, replaces experiences and educations only if they differ (`_rows` compares them), rebuilds `search_document`. Returns the names of fields that changed, including `experiences` and `educations` (for the audit log). |
| `_new_candidate(profile, consent_version, source, source_ref, consent_recorded_by)` | A new `Candidate` with consent info, then `_apply_profile`. |
| `_is_duplicate_email(exc)` | Whether an `IntegrityError` came from the `uq_candidates_email` constraint. |
| `_audit(...)` | Shorthand for `record_event` with `entity_type="candidate"`. |
| `to_detail(candidate)`, `_to_summary(candidate)` | Model → response schema. The summary shows the first 5 skills. |
| `create_candidate(session, data, consent_version, ...)` | Public form. Honeypot filled → fake success, nothing saved. Duplicate email → 409. The UNIQUE constraint is the real check, so two simultaneous submits can't both win. |
| `search_candidates(session, params, actor)` | The staff list: filters, keyset page, one `candidate.search` audit row (filter names only). |
| `get_candidate(session, id, actor)` | Loads the profile and records `candidate.view`: looking at personal data is itself audited. |
| `create_candidate_by_staff(...)` | Same as public, `source="admin"`, records who captured the consent. |
| `update_candidate(...)` | Row lock, version check, apply, flush, audit `changed_fields`. A `StaleDataError` from SQLAlchemy's version column also becomes 409. |
| `delete_candidate(...)` | Admin only. `DELETE ... RETURNING`; children, embeddings and failures go by `ON DELETE CASCADE`. |
| `bookmark_candidate(session, id, actor)` | Stars the candidate on the **team's shared** list; starring again keeps the first adder. Audits `candidate.bookmark` only when a row was added. Unknown candidate → 404 (the foreign key fails). |
| `unbookmark_candidate(session, id, actor)` | Anyone may remove a star; removing twice is fine. Audits `candidate.unbookmark` only when a row went. |
| `list_bookmarks(session, actor)` | Every bookmark, newest first, with the adder's name (`auth.get_full_names`). Unpaged (a `shortcut:`). |
| `RankableCandidate` | What the ranking may see: summary, the **redacted** profile text, city, country, years, skills, work modes, relocation, salary, `updated_at`. Never name or contact details. |
| `get_rankable_candidates(session, ids)` | `{id: RankableCandidate}`; deleted ids are simply missing. |
| `full_text_candidate_ids(session, query, count, within)` | Best keyword matches first. Used by hybrid search. |
| `rebuild_search_documents(session)` | Rewrites every profile's stored document after its format changes, and returns how many changed. Leaves `version` and `updated_at` alone. The embedding scan then finds them stale. |
| `candidate_ids_passing(min_years, skills, city, country, source)` | A **SQL subquery** (not a list) of ids that pass every hard filter. Other features pass it into their own queries as `WHERE id IN (subquery)`, so the filter rules stay inside this feature. |

### `candidates/repository.py`

| Function | What it does |
|---|---|
| `add_candidate` | Insert and flush. |
| `hard_filter_clauses(min_years, skills, city, country, source)` | The hard filters as SQL `WHERE` clauses. Skills match any spelling (`skills && ARRAY['postgres','postgresql','psql']`); city matches any spelling, case-insensitive. **Keep in sync with `semantic_search.service.failed_filters`.** |
| `ids_passing(...)` | `SELECT id FROM candidates WHERE <hard filters>`. |
| `search_candidates(session, params, after)` | Newest-first list meeting the hard filters: `(created_at, id) < cursor`, `LIMIT limit+1`. |
| `get_candidate(id, for_update)` | Loads the candidate with experiences and educations (eager `selectinload`; lazy loading is forbidden with `lazy="raise"`). |
| `get_candidates_by_ids(ids)` | One `IN` query. |
| `full_text_candidate_ids(query, limit, within)` | Builds a tsquery from the text, turns AND into OR (`&` → `|`) so a profile matching 4 of 6 words still ranks, orders by `ts_rank_cd` (normalised by length so long profiles don't win by size). |
| `delete_candidate(id)` | Returns whether a row was deleted. |
| `add_bookmark(id, added_by)` | `INSERT ... ON CONFLICT (candidate_id) DO NOTHING RETURNING id`; returns whether a row was added. |
| `remove_bookmark(id)`, `list_bookmarks()` | `DELETE ... RETURNING`; bookmarks joined to candidates, newest first. |

### Other candidate files

| File / function | What it does |
|---|---|
| `search_document.build_search_document(profile)` | Builds the text that is embedded and sent to the LLM: headline, years, skills, summary, experience, education, desired roles, work modes. Every user-typed field passes `redact_identifiers`. City is **not** included (it's in the full-text index and passed to the LLM separately). |
| `schemas.CandidateProfile` | All profile rules: lengths, lower-cased email, ISO country, E.164 phone, LinkedIn/GitHub URL hosts, 1-50 skills, summary 50-3000 characters, at most one current role, dates not in the future, salary + currency together. |
| `schemas.CandidateCreate` / `StaffCandidateCreate` / `CandidateUpdate` | Profile + `consent: true` + honeypot `website` / profile + `consent_confirmed: true` / profile + `version`. |
| `schemas.CandidateSearchParams` | Query params of the list endpoint (the hard filters, `cursor`, `limit`); blanks become `None`; `limit` max 100. |
| `models.Candidate` | The table. `search_tsv` is a **generated column** computed by Postgres from `search_document || ' ' || city`. `version` is SQLAlchemy's `version_id_col`, so every UPDATE includes `WHERE version = :old`. CHECK constraints mirror the schema rules. |
| `models.CandidateBookmark` | `candidate_bookmarks`: one row per starred candidate (`candidate_id` UNIQUE), `added_by`. Both foreign keys `ON DELETE CASCADE`, so deleting a candidate removes its star. |

---

## jobs

### Endpoints

| Endpoint | Function |
|---|---|
| `POST /api/v1/jobs` | `create_job` |
| `GET /api/v1/jobs?status&cursor&limit` | `list_jobs` |
| `GET /api/v1/jobs/{id}` | `get_job` |
| `PATCH /api/v1/jobs/{id}` | `update_job` (only the creator or an admin) |

### `jobs/service.py`

| Function | What it does |
|---|---|
| `_audit(...)` | `record_event` with `entity_type="job"`. |
| `_can_edit(job, actor)` | Admin, or the person who created it. |
| `_summary_fields(job, owner_name)` | Shared dict for `JobSummary` and `JobDetail`. |
| `_to_detail(session, job, actor)` | Adds owner name, `can_edit` and `embedding_status` (from the embeddings feature). |
| `_apply(job, fields)` | Copies `EDITABLE_FIELDS`; returns which changed. |
| `_stored_fields(job)` | The job's current values as a dict. |
| `create_job(session, data, actor)` | New job, redacted search document (the recruiter's name is redacted too), insert, audit. A DB CHECK failing → 422. |
| `list_jobs(session, params)` | Newest-first page; owner names fetched in **one** query for the whole page. |
| `get_job(session, id, actor)` | Detail or 404. |
| `JobBrief`, `get_job_brief(session, id)` | What matching needs from a job (redacted search document, work mode, location, min years, must-have skills, pay). |
| `_constraint_error(exc)`, `_validation_error(exc)` | Turn DB or Pydantic errors into a 422 `JobValidationError`. Only the error class is logged (driver messages can echo values). |
| `update_job(session, id, patch, actor)` | Lock, permission check, version check, merge the patch onto stored values and **re-validate the whole job** (a patch alone can't check rules like max ≥ min), read everything needed *before* changing attributes (see [08-decisions.md](08-decisions.md#autoflush)), rebuild the document, audit only if something changed. |

### Other job files

| Name | What it does |
|---|---|
| `search_document.build_job_search_document(job, redact_names)` | Title, department, employment type, work mode, location, experience range, must-have and nice-to-have skills, description; redacted. **Status is left out**, so closing a job doesn't trigger a new (paid) embedding. |
| `schemas.JobFields` | Rules: city required for hybrid/onsite, country required with a city, max years ≥ min, no skill in both lists, salary max ≥ min, currency with salary, description 100-10,000 characters. |
| `schemas.JobPatch` | Every field optional, plus required `version`. |
| `repository.add_job`, `get_job(for_update)`, `list_jobs(status, after, limit)` | SQL. |

---

## embeddings

How it all fits together is in [03-flows.md](03-flows.md#4-embedding-in-the-background). This feature has no HTTP endpoints.

### `embeddings/targets.py`

| Name | What it does |
|---|---|
| `EmbeddingTarget` | Describes one kind of embedded thing: its source table (`candidates` or `jobs`, only `id` and `search_document`), its embeddings table, its failures table, the id column name, constraint names, and the `ai_usage` operation name. The code is written once against this, so candidates and jobs share every function. |
| `CANDIDATES`, `JOBS` | The two targets. |
| `TARGETS = (JOBS, CANDIDATES)` | Processing order. Jobs first: a recruiter is waiting for a new job to be ready. |

### `embeddings/service.py`

| Function | What it does |
|---|---|
| `EmbedOutcome` | Counters: `embedded`, `failed`, `blocked`. |
| `hash_document(text)` | sha256 hex of the UTF-8 text. Must equal the SQL hash in `repository._document_hash`. |
| `_record_failures(...)` | Writes a dead-letter row for each document in a batch. |
| `_embed_batch(session, provider, target, batch, outcome, trigger)` | One metered OpenAI call for the batch. Success → store vectors and clear failures. Budget/price refusal → record and stop. Permanent error → retry one by one (stop if the budget refuses mid-way). Transient error → record for a later retry. Never raises provider errors. |
| `embed_stale(session, provider, target, trigger)` | If there's budget: find up to 64 stale ids, load their documents, `_embed_batch`, log a summary. |
| `embed_all_stale(session, provider)` | `embed_stale` for jobs, then candidates. This is the background task. |
| `nearest_candidates_to_vector(session, vector, model, count, within)` | Candidate ids closest to a vector, with cosine similarity, optionally only among `within`. |
| `load_job_vector(session, job_id, model)` | The job's stored vector, or `None` if missing or made from older text. |
| `get_job_embedding_status(session, job_id, model)` | `ready`, `failed` (permanent or gave up after 5 tries), `budget_blocked`, or `pending`. Shown on the job page. |

### `embeddings/repository.py`

| Function | What it does |
|---|---|
| `is_permanent_failure(last_error)` | Whether a dead letter can't be fixed by retrying the same text. |
| `_document_hash(target)` | SQL: `encode(sha256(convert_to(search_document, 'UTF8')), 'hex')`. |
| `load_documents(ids, target)` | `{id: search_document}`. |
| `upsert_embeddings(model, rows, target)` | `INSERT ... ON CONFLICT (entity, model) DO UPDATE`: one row per entity per model. |
| `clear_failures(model, ids, target)` | Deletes dead letters after success. |
| `record_failure(...)` | Upserts a dead letter. `attempts` counts up only while the failing text is the same; new text resets it to 1. |
| `_failure_allows_retry(target)` | The SQL condition for "this failure may be retried now" (see flow 4). |
| `find_stale_ids(model, limit, target)` | The scan: no embedding, or hash differs, and the failure (if any) allows a retry. |
| `load_embedding_hash`, `load_current_hash`, `load_failure` | Small reads for the job status. |
| `load_current_vector(entity_id, model, target)` | Reads the vector as text and parses it with `json.loads` (pgvector's text form `[0.1,0.2]` is valid JSON), but only if its hash matches the current document. |
| `similarity_statement(vector, model, limit, within)` | `SELECT candidate_id, 1 - (embedding <=> :vector) ... ORDER BY embedding <=> :vector LIMIT n`. Kept alone on the embeddings table so Postgres uses the HNSW index (a join here made it sort instead). |
| `nearest_neighbours(...)` | Runs it. With `within`, first sets `hnsw.iterative_scan = relaxed_order` so the index keeps searching until enough rows pass the filter, then re-sorts (relaxed order can be slightly out of order). |

### `embeddings/models.py`

`CandidateEmbedding`, `JobEmbedding` (vector(1536), `content_hash`, `model`, HNSW cosine index) and `EmbeddingFailure`, `JobEmbeddingFailure` (`content_hash`, `attempts`, `last_error`). All have foreign keys with `ON DELETE CASCADE`.

---

## ai_usage

### Endpoints

| Endpoint | Function | Who |
|---|---|---|
| `GET /api/v1/ai-usage/summary` | `get_summary` | staff |
| `GET /api/v1/ai-usage/events` | `list_events` | staff |
| `PUT /api/v1/ai-usage/budget` | `update_budget` | admin |

### `ai_usage/service.py`

| Function | What it does |
|---|---|
| `_billed(exc, attribute)` | Reads billed tokens off an exception; anything negative or missing is 0 (a negative would act like a refund). |
| `_ensure_budget(session)` | The budget row, created at $5.00 if missing (tests truncate tables). |
| `_refusal(session, model)` | Why a call can't run: unknown price, or spent ≥ limit. `None` if it can. |
| `metered_call(...)` | Check → call → record. See [03-flows.md](03-flows.md#5-every-paid-ai-call-metered_call). |
| `budget_used_up(session)` | spent ≥ limit, in the caller's transaction. |
| `has_budget(session)` | The opposite, in its own transaction. A quick pre-check; `metered_call` still decides. |
| `get_summary(session)` | Limit, spent, remaining, percent, `limit_reached`, totals per model and per operation. |
| `list_events(session, params)` | Filterable, newest-first page of events. |
| `update_budget(session, data, actor)` | Admin only. Changes the limit only if it differs (so an unchanged save doesn't bump `updated_at`), audits old/new values. |

### `ai_usage/repository.py`

| Function | What it does |
|---|---|
| `get_budget`, `add_budget` | The single budget row. |
| `get_spent` | `SUM(cost_usd)` over all events (blocked and most failed events cost 0). |
| `add_event` | Insert one event. |
| `totals_by(column)` | Per-model or per-operation totals, billed events only. |
| `list_events(...)` | Filters plus keyset paging. |

`exceptions.BudgetExceededError` is a 402.

---

## semantic_search

The full pipeline is explained in [03-flows.md](03-flows.md#6-search-by-meaning). Here is each function.

### Endpoints (`router.py`)

| Endpoint | Function |
|---|---|
| `GET /api/v1/semantic-search/candidates?q=...` | `search_candidates_by_meaning`: JSON |
| `GET /api/v1/semantic-search/candidates/stream?q=...` | `stream_search_candidates`: SSE |
| `GET /api/v1/semantic-search/jobs/{id}/candidates` | `match_candidates_to_job`: JSON |
| `GET /api/v1/semantic-search/jobs/{id}/candidates/stream` | `stream_match_candidates_to_job`: SSE |
| `GET /api/v1/semantic-search/history?cursor=` | `list_saved_searches`: your own searches, newest first (free) |
| `GET /api/v1/semantic-search/history/{id}` | `get_saved_search`: one search with its result as ranked (free, no AI call) |
| `PUT /api/v1/semantic-search/history/{id}/star` | `star_saved_search`: `{"starred": bool}` |
| `DELETE /api/v1/semantic-search/history/{id}` | `delete_saved_search` |

Another person's saved search answers 404, like a missing one.

It has its own prefix because `/admin/candidates/semantic` would be captured by the `/admin/candidates/{candidate_id}` route.

### `semantic_search/service.py`

| Function | What it does |
|---|---|
| `looks_personal(query)` | `True` for `@`, `://`, `www.`, or a phone number (`shared.redaction.contains_phone_number`: 10+ digits, the same rule redaction uses). Such queries are refused, because the query is sent to OpenAI. "10 years in 2024" and "budget 2500000 INR" are fine. |
| `failed_filters(candidate, params)` | Which hard filters a candidate fails, in Python. **Same rules as `candidates.repository.hard_filter_clauses`.** |
| `_active_filters(params)` | Names of filters that are set. |
| `_with_understood(filters, understood)` | The recruiter's filters, plus the facts read from the search text where the recruiter set nothing (used to fetch those people first). |
| `_with_budget(filters, understood)` | Adds the budget read from the search text as a hard filter, unless one was passed. |
| `_budget(filters)` | The filters' budget as a `ranking.Budget`, or `None`. |
| `_rank_with_llm(session, query, pool, required, progress, budget, home_country)` | Builds the prompt, uses the 10-minute cache if possible, otherwise one metered `gpt-5.4-mini` call; returns ranked matches, or `None` if the AI is unavailable. Empty pool → no call. |
| `_profiles(count)` | "1 profile" / "5 profiles" for progress messages. |
| `_embed_query(session, provider, query)` | One metered embedding of the query with a 10 s timeout. Failure → 503. |
| `find_matches(session, params, progress)` | The search itself: refuse personal-looking queries, embed, `understand_query`, `_find_rank_and_filter`. Returns the result and the understood facts. No audit, no saved search; the evaluation calls it directly. |
| `search_by_meaning(session, params, actor, progress)` | The API entry point: `find_matches`, then the `candidate.search` audit row and the searcher's saved copy. |
| `_hybrid_ids(session, vector, model, keyword_text, within)` | One hybrid fetch: nearest vectors + full text, fused (reciprocal rank fusion), `POOL_SIZE` ids. |
| `label_pool(session, query, count)` | The best `count` hybrid matches **without** the AI ranking, for a person to grade (one query embedding, about $0.000001). |
| `_JOB_WORK_MODES` | Maps job `onsite` to the ranking's `office`. |
| `job_filters(job)` | The job's own requirements as hard filters, budget (`salary_max`) included. City only binds hybrid/onsite jobs. |
| `match_job(session, job_id, actor, progress)` | The job-matching entry point: uses the stored job vector (no embedding call), keywords from title + skills + city, the job's document (never its pay) as the brief. 409 if the embedding isn't ready. |
| `_counts(result)` | Counts for logs and audit. |
| `_find_rank_and_filter(...)` | The shared pipeline: hybrid fetch (twice when filters are set, once more when facts were read from the text), load rankable profiles, rank, split by filters. |

### `semantic_search/evaluation.py`

Scores search against the hand-graded golden set in `backend/evals/` (how to grade and run it: [backend/evals/README.md](../../backend/evals/README.md)).

| Function | What it does |
|---|---|
| `GoldenSet` / `GoldenCase` / `GoldenCandidate` | The `golden_set.json` format. A case counts as `graded` only when every candidate has a grade 0-3. |
| `ndcg_at(ranked, grades, k=10)` | NDCG with gain `2^grade - 1`; ungraded results count as 0; `None` when nobody in the case is graded above 0. |
| `precision_at(ranked, grades, k=5)` | Share of the top k graded 2 or more (divides by k even with fewer results). |
| `experience_band(years)` | 0-3, 3-8, 8-15, 15+ years: the stand-in for age, which isn't collected. |
| `group_rates(outcomes, dimension)` | Of the people graded 2+, the share of each group (country or experience band) found in the top 10. Flags a group of 5+ found at under 80% of the best group's rate (four-fifths rule). |
| `run_eval(session, golden)` | Runs every graded case through `find_matches` (real, metered calls) and builds the `EvalReport`. |
| `new_case(session, id, query, count, rng)` | A case to grade from `label_pool`: synthetic profiles only (the file is committed), shuffled. |
| `report_markdown(report)` | The run as a readable page. |

### `semantic_search/history.py`, `repository.py`, `models.py`

| Name | What it does |
|---|---|
| `SavedSearch`, `SavedSearchMatch` | One row per search (owner, query, URL filters, counts, models, `starred`) and one per card shown (section, position, fit, criteria, failed filters). Both cascade: deleting the user, the search or the candidate deletes the rows. |
| `HISTORY_LIMIT` | 50: un-starred searches kept per person. |
| `save_search(session, user_id, params, result)` | Inserts both, then `prune_history`. Runs in the caller's transaction (with the audit row). |
| `list_history(session, actor, cursor)` | Own searches, newest first, `PAGE_SIZE` 50 per page, with result counts. |
| `get_saved_search(session, actor, id)` | The saved result rebuilt with current summaries from `candidates.get_rankable_candidates`; `SavedSearchNotFoundError` (404) if missing or someone else's. |
| `star_saved_search`, `delete_saved_search` | Owner only, otherwise 404. |
| `repository.prune_history(session, user_id, keep)` | Deletes un-starred searches beyond the newest `keep`. |

### `semantic_search/understanding.py`

| Name | What it does |
|---|---|
| `PROMPT_VERSION`, `INSTRUCTIONS` | The prompt file `prompts/understand_v3.md`, loaded once. |
| `QueryFacts` | The JSON the LLM must return: `city`, `country_code`, `min_years`, `max_salary` (yearly, whole units) and `salary_currency`, each null unless the text states it. A budget without its currency is dropped. |
| `understand_query(session, query)` | One metered `gpt-5.4-mini` call with a 10 s timeout, about $0.0004. The answer is checked through `HardFilters`, then cached for 10 minutes. Any failure logs the class name and returns `None`, and the search carries on. |
| `clear_understanding_cache()` | Empties the cache (tests). |

### `semantic_search/ranking.py`

| Name | What it does |
|---|---|
| `PROMPT_VERSION`, `INSTRUCTIONS` | The prompt file `prompts/rank_v7.md`, loaded once. A prompt change gets a new file name. |
| `RANK_MODEL` | `gpt-5.4-mini`. |
| `required_work_mode(query)` | Finds "hybrid", "office/onsite/wfo" or "remote/wfh" in the search text. Hybrid wins if several appear. |
| `fits_work_mode(candidate_modes, required)` | Office (2) ≥ hybrid (1) ≥ remote (0): a candidate fits if they accept at least as much office time as the role needs. |
| `fuse(*lists, count)` | Reciprocal rank fusion: each list gives `1 / (60 + position)` to each id; sum and sort. Being near the top of either list, or in both, ranks high. Ties are broken by id so the order is stable. |
| `CandidateJudgement`, `RankingAnswer` | The exact JSON shape the LLM must return. |
| `build_prompt(query, pool)` | "Search: ..." plus a numbered JSON list of anonymised profiles (redacted text, city, country, years, work modes, relocation). No pay. Candidates are numbers, not ids or names. |
| `judge_location(judgement, candidate, required, place_named, home_country)` | Location points and note, with code guards (work-mode rule, place named, relocation must be stated). For a remote role it uses the stored country: 1 in `home_country`, 0.5 outside it. |
| `Budget`, `salary_criterion(candidate, budget)` | The budget, and the salary line a recruiter reads (met / missed / "No expected salary stated" / "Expects in USD, can't compare"). Over budget is filtered by `failed_filters`, not here. |
| `to_match(...)` | One judgement → a sort key `(skills + location unless remote, skills band, experience band, remote country, years)` and the `SemanticMatch` with readable criteria. Fit: strong (every must met), partial (one), weak. |
| `rank_by_judgements(answer, pool, required, budget, home_country)` | Sorts the pool by those keys; ties keep the hybrid order; unjudged candidates go last instead of disappearing. |
| `cache_key`, `cached_answer`, `remember_answer`, `clear_ranking_cache` | An in-memory cache (128 entries, 10 minutes) keyed by model, prompt version, query, and each profile's id + `updated_at`. Repeating a search over unchanged profiles costs nothing. Editing a profile changes `updated_at`, so the cache misses. |

### `semantic_search/progress.py`

| Name | What it does |
|---|---|
| `Progress(listener)` | `start(stage, detail)` and `done(stage, detail)` send `StageEvent`s to the listener with elapsed milliseconds. Without a listener they do nothing. |

### `semantic_search/streaming.py`

| Name | What it does |
|---|---|
| `_event(name, data)` | Formats one SSE message: `event: <name>\ndata: <json>\n\n`. |
| `_events(search)` | Starts the search as its own task with its own session; stage events, then `result` or `error`, go through a queue; yields them as text. Unexpected errors are logged by class name and sent as a generic `internal_error`. |
| `stream_search(search)` | Wraps `_events` in a `StreamingResponse` with `Cache-Control: no-cache` and `X-Accel-Buffering: no` (so a proxy doesn't hold the events back). |

### `semantic_search/schemas.py`

`HardFilters` (min years, comma-separated skills up to 1,100 characters, city, country, source), `SemanticSearchParams` (+ `q` 2-500 characters, `limit` ≤ 20), `Criterion`, `SemanticMatch` (+ `failed_filters`), `Stage`, `StageEvent`, `SemanticSearchResult` (`items`, `filtered_out`, `ranked_by: "ai" | "search"`, and the models and prompt version used).

### `semantic_search/exceptions.py`

| Error | Status | When |
|---|---|---|
| `QueryLooksPersonalError` | 422 | The query looks like an email, phone or link. |
| `SemanticSearchUnavailableError` | 503 | No API key, or the query embedding failed or timed out. |
| `JobNotReadyForMatchingError` | 409 | The job has no embedding of its current text yet. |

---

## health

| Endpoint | Function | What it does |
|---|---|---|
| `GET /health` | `liveness` | Always `{"status": "ok"}`: the process is up. |
| `GET /ready` | `readiness` → `service.check_readiness` | Checks the database (`SELECT 1`, `ping_database`) and that pgvector is installed (`pgvector_installed`). 503 if either fails. |

They live at the root, not under `/api/v1`, so load balancers don't depend on API versions.

| Endpoint | Function | What it does |
|---|---|---|
| `GET /api/v1/admin/system` | `system_details` → `service.get_system_details` | For the staff System page, any signed-in staff. Returns the embedding and ranking models and both prompt versions; for candidates and for jobs, how many exist, how many have a vector made from today's document, and how many have a failure recorded for it (`embeddings.get_embedding_counts`); and AI spend against the limit (`ai_usage.get_summary`). Counts, names and money only, never candidate data. |

`health` is the one feature that reads three others (`embeddings`, `ai_usage`, `semantic_search`), always through their `__init__.py`. Nothing imports `health`, so this makes no cycle.

---

## resumes

Reads uploaded resumes with **ResumeAI** (the user's own service, `RESUMEAI_BASE_URL`, key `RESUMEAI_API_KEY`) and shows ResumeAI's formatted resume PDF. ResumeAI keeps the extracted data under a pair we choose, `(resume_ref, "resume")`, and `candidates.resume_ref` stores that UUID. We keep one file: a copy of the formatted PDF in object storage, whose key is `candidates.resume_pdf_key`.

| Endpoint | Function | Who |
|---|---|---|
| `POST /api/v1/resumes` | `router.read_resume` → `service.read_new_resume` | public; needs `X-Requested-With: fetch`; `RESUME_UPLOAD_LIMIT` per IP per hour (default 10). For a profile not saved yet: makes a fresh `resume_ref`, reads the file, returns `{resume_ref, profile}` (suggestions). |
| `PUT /api/v1/admin/candidates/{id}/resume` | `router.attach_resume` → `service.attach_resume` | staff, 204. Reads the file for a saved candidate and links it; the profile fields and `version` don't change. A replacement reuses the candidate's ref, so ResumeAI overwrites its data. |
| `GET /api/v1/admin/candidates/{id}/resume` | `router.formatted_resume` → `service.formatted_resume_pdf` | staff. The PDF, `inline; filename="resume.pdf"`, `no-store`: the stored copy, or rendered by ResumeAI and then stored. 404 without a resume (ResumeAI isn't asked). Audited as `candidate.resume_view`. |

- **The file is the raw request body**, not multipart: FastAPI's form parsing needs `python-multipart`, a new dependency for one field. `BodySizeLimitMiddleware` gives the two upload paths (`resumes.UPLOAD_PATHS`) `MAX_RESUME_BYTES` (4 MB: Vercel refuses bodies over 4.5 MB); every other route keeps 64 KB.
- `client.ResumeAIClient` uses `httpx2` (already installed for OpenAI), with `RESUMEAI_TIMEOUT_SECONDS` (120) and **no retries**: a person pressed the button and can press it again, and a failed read still counts against ResumeAI's 30-an-hour limit. Errors become plain messages: 401 and 402 → 503, 413/415/429 pass through (429 keeps `Retry-After`), 422 shows ResumeAI's sentence only when it is one, other failures → 502, timeouts and connection errors → 503. Only the status code is logged, never ResumeAI's body.
- `mapping.to_profile` turns ResumeAI's data into form suggestions: dates written like "Jan 2021" or "Present" become `YYYY-MM` and `is_current`, "Pune, India" becomes city + country code, links are sorted into LinkedIn / GitHub / portfolio, skills become tags, years of experience is first start to last end. Anything unreadable stays empty; nothing is guessed. Lengths are cut to the form's limits.
- **Stored copy** (`service.formatted_resume_pdf`, `_keep_pdf`): with a store configured (`core.storage.get_storage()`), the first view fetches from ResumeAI, uploads to `resumes/<candidate id>/<uuid4>.pdf` and records the key with `candidates.record_resume_pdf`. That write is a plain UPDATE (no `version` bump) and only succeeds if the resume ref, the profile `version` and the previous key are unchanged since the view started; otherwise the copy is already stale and its file is deleted. Later views read the file and skip ResumeAI. A stored key whose file has gone missing is fetched again and replaced. A storage error never fails the view: the PDF just comes from ResumeAI.
- **Invalidation** (user decision: any change): a profile edit that changes a field (`candidates.update_candidate`), a new or replaced resume (`candidates.attach_resume`) and a delete clear `resume_pdf_key` in the same transaction, then `core.storage.discard` deletes the file after the commit (a failed delete only leaves an orphan, logged). A save with nothing changed keeps the copy.
- `candidates.get_resume_ref`, `open_resume`, `record_resume_pdf` and `attach_resume` are the only ways `resumes` touches candidate data. A ref that's never saved with a profile leaves unused data at ResumeAI.

Next: [06-frontend.md](06-frontend.md).
