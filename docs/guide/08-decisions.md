# 8. Decisions and why

Each entry: what we decided, why, and the function or file where you can see it. The full history, with dates, is in [LEARNINGS.md](../LEARNINGS.md).

## Product and data

### No LinkedIn scraping
LinkedIn forbids it and has sued over it. Candidates come from our own form and staff entry. Future sources must have a clear legal basis.

### Personal data never goes to the AI
**Decision:** names, emails, phones and links are removed from every text sent to OpenAI.
**Why:** privacy law (GDPR, AI regulation of hiring) and fairness: ranking must not depend on who someone is.
**Where:** `shared/redaction.redact_identifiers`, `candidates/search_document.build_search_document`, `jobs/search_document.build_job_search_document`, `semantic_search/service.looks_personal`, `ranking.build_prompt` (candidates are numbers, not ids or names).

### No staff lookup by name or email
**Decision:** the old `lookup_text` column (a second copy of names and emails with a trigram index) and the list endpoint's `q`, `work_mode`, `max_years` and `sort` options were removed, because the UI no longer used them. Staff find people by filters or by search by meaning.
**Where:** `candidates/repository.search_candidates`; migration `d2b7e4a1c9f6`. Bringing lookup back is a new decision.

### Salary is yearly, whole units, with one of 8 currencies
**Decision (user):** salary is a yearly amount plus a currency, and the AI judges it.
**Why 8 currencies:** the forms offer 8. Accepting more would store values the edit form can't show or save.
**Where:** `shared/validation.YearlySalary`, `CURRENCY_CODES`, `ranking.judge_salary`.

## Architecture

### Feature folders, three layers
See [02-architecture.md](02-architecture.md). Everything about one capability is in one folder; routers, services and repositories each have one job.

### No queue for embeddings; the hash is the signal
**Decision:** don't queue "please embed this" messages. Every 2 seconds, find documents whose sha256 differs from the hash stored with their embedding.
**Why:** a queue needed an enqueue call on every save, leases, a sweeper for lost messages, and more code. A save that changes the text automatically makes the row stale; one that doesn't (phone edit) costs nothing. For ~1,000 rows the scan takes milliseconds.
**Limit:** marked `shortcut:` in `embeddings/repository.find_stale_ids`. Around 100k rows, add a queue table or an indexed hash column.
**Where:** `embeddings/service.embed_stale`, `repository.find_stale_ids`.

### Retries live in the dead-letter row
**Decision:** a failed embedding writes a row with `attempts` and `last_error`; the scan's SQL decides when it's due again (30 s, 2 min, 8 min, 32 min, then stop until the text changes).
**Why:** no separate scheduler; retries survive restarts.
**Where:** `repository._failure_allows_retry`, `record_failure`.

### One background runner, inside the API
**Decision:** one loop (`core/maintenance.py`) runs every periodic task, inside the API process by default.
**Why:** no Redis or Celery to install; one process to run locally. It can be split out (`python -m app.cli maintenance` + `MAINTENANCE_IN_API=false`) when needed.
**Where:** `core/maintenance.run_maintenance`, `app/maintenance.maintenance_tasks`.

### Rate limits stored in Postgres
**Decision:** each counted attempt is a row; an advisory lock per key makes the check-and-insert atomic.
**Why:** an in-memory counter is per process and resets on restart; Postgres is already there.
**Where:** `core/rate_limit.acquire_slot`, `failure_slot`.

### Only failed logins count, and slots are reserved first
**Why:** a user who mistypes once shouldn't be locked out by later successes. Reserving before checking makes parallel guesses count correctly.
**Where:** `core/rate_limit.failure_slot`, `auth/router.login`. A second limit per email (across IPs) caps guessing from many machines; the accepted cost is that someone who knows a staff email can lock that login for 15 minutes.

### Sessions in the database, cookie holds a random token
**Decision:** a random token in an httpOnly cookie; the database stores only its sha256. Sessions extend when half their 8 hours have passed.
**Why:** can be revoked instantly (deactivate, password reset); a database leak doesn't hand out working sessions.
**Where:** `auth/service.authenticate`, `resolve_session`, `hash_token`.

### Forced password change is enforced for every route by default
**Why:** fail closed. A new route can't forget the check, because `CurrentUser` includes it. Only three routes opt out with `SessionUser`/`OptionalSessionUser`.
**Where:** `auth/dependencies.get_auth_context`.

### There is always at least one admin
**Why:** two admins demoting each other at the same moment could leave none.
**Where:** `auth/service.update_user` with `repository.lock_admin_changes` (advisory lock) and `count_active_admins`.

### Optimistic locking with a `version` column
**Why:** two people editing the same record must not silently overwrite each other.
**Where:** `version_id_col` in `candidates/models.Candidate` and `jobs/models.Job`; the 409 in `update_candidate` / `update_job`.

### Keyset (cursor) pagination
**Why:** stays fast on big tables and doesn't skip or repeat rows when new ones arrive (OFFSET does both).
**Where:** `core/pagination.py`, `candidates/repository.search_candidates`.

### The embeddings feature reads `candidates` and `jobs` tables directly
**Why:** hashing every document must happen in SQL, joined with the embeddings table. Only `id` and `search_document` are read, never written.
**Where:** `embeddings/targets.py`.

### Candidates and jobs share embedding code through `EmbeddingTarget`
**Why:** separate tables keep real foreign keys and cascade deletes; one descriptor keeps the code written once.
**Where:** `embeddings/targets.py`.

## AI and spend

### OpenAI only, through the official SDK
**Decision (user):** `text-embedding-3-small` (1536 dims) for embeddings, `gpt-5.4-mini` for ranking. No other provider.
**Why the SDK:** it already retries 429/5xx with backoff and honours `Retry-After`. We set `max_retries` and `timeout` explicitly and never stack a second retry layer.
**Where:** `core/embeddings.py`, `core/llm.py`.

### A hard spending limit, checked before every call
**Decision:** every paid call goes through `metered_call`: refuse if spent ≥ limit (default $5), else call and record the real cost.
**Accepted limit (`shortcut:`):** check and record aren't atomic, so simultaneous calls can overshoot by one call (cents). A call cancelled mid-flight isn't recorded. Fine for one worker plus staff searches.
**Unknown model prices are refused**, so a typo can't bypass the cap.
**Where:** `ai_usage/service.metered_call`, `core/ai_pricing.py`.

### Hybrid search: meaning + keywords
**Why:** embeddings find "the right kind of profile" but are weak on exact words, numbers and places (the city isn't even in the embedded text). Full-text search catches those. Merging with RRF gets both.
**Where:** `semantic_search/service._find_rank_and_filter`, `ranking.fuse`, `candidates/repository.full_text_candidate_ids`.

### Full-text search uses Postgres `tsvector`, not BM25
**Why:** true BM25 needs an extension (ParadeDB) that only ships for Linux/Docker; this machine runs native Windows Postgres. `ts_rank_cd` with length normalisation is good enough here.
**Where:** `candidates/models.SEARCH_TSV_EXPRESSION` (includes the city), `repository.full_text_candidate_ids` (words OR-ed so partial matches still rank).

### The LLM judges, code orders
**Decision (user):** skills and location first, then skills score, then pay, then experience.
**Why:** the same judgements always give the same order, and plain rules (work-mode compatibility, "relocation must be stated") aren't left to the model.
**Where:** `ranking.to_match`, `rank_by_judgements`, `judge_location`, `judge_salary`, `fits_work_mode`.

### "Does the search name a place / state pay?" is asked once per search
**Why:** inferring it from any one candidate's verdict let one odd answer change the scoring for all 20.
**Where:** `RankingAnswer.search_names_place`, `search_states_pay`; prompt `rank_v3.md`.

### 20 profiles go to the LLM
**Decision (user):** the shortlist is 20 (plus up to 10 filtered-out when filters are set). About $0.01-0.02 per search.
**Where:** `POOL_SIZE`, `FILTERED_OUT_SIZE` in `semantic_search/service.py`.

### Hard filters split the ranked list instead of removing people
**Decision (user):** show perfect matches and, separately, strong candidates a filter removed.
**Why fetch twice:** filtering only after a top-20 fetch could leave few perfect matches when matching people exist lower down. So with filters, fetch the best 20 among people who pass, plus the best 10 of everyone else.
**Where:** `_find_rank_and_filter`, `candidates.candidate_ids_passing`, `failed_filters`.

### The SQL filter and the Python filter must agree
**Why:** the SQL version narrows the fetch; the Python version labels each ranked result. If they disagree, someone is fetched as "passing" and then shown as "filtered out".
**Where:** `candidates/repository.hard_filter_clauses` and `semantic_search/service.failed_filters`, both using `shared/aliases.py`.

### If the AI ranking fails, still return results
**Why:** no key, budget used up after the query embedding, or a timeout shouldn't leave the recruiter with nothing. Results come back in hybrid-search order with `ranked_by: "search"`. Only a failed *query embedding* is an error (402/503).
**Where:** `_rank_with_llm` returns `None`; `_find_rank_and_filter` falls back.

### Ranking answers are cached for 10 minutes
**Why:** repeating a search, or changing only the filters, shouldn't pay again. The key includes each profile's `updated_at`, so an edit invalidates it.
**Where:** `ranking.cache_key`, `cached_answer`, `remember_answer`.

### Job matching uses the job's stored embedding
**Why:** no new embedding call; the job was embedded when saved. If the stored vector is older than the job's text, matching refuses (409) instead of using stale meaning.
**Where:** `semantic_search/service.match_job`, `embeddings/repository.load_current_vector`.

### Job status isn't part of the job's search document
**Why:** closing or reopening a job would otherwise trigger a paid re-embedding.
**Where:** `jobs/search_document.build_job_search_document`.

### Paid actions only on an explicit click
**Why:** each search costs money and sends text to OpenAI. Typing never triggers it, in the search box or the filters; "Find candidates" is a button. On the server, the `semantic_search` routes require the CSRF header even on GET, so a link clicked on another site can't start a paid search.
**Where:** frontend `CandidateSearchPage` (`submitted`), `JobMatches`, `useJobMatches(enabled)`; backend `auth.require_fetch_header_on_any_method`.

### Progress is streamed with SSE; a disconnect doesn't cancel the search
**Why SSE:** shows each step (embedding → retrieval → augmentation → ranking → filtering) as it happens, over a normal HTTP response.
**Why not cancel:** cancelling a metered call mid-flight would leave its cost unrecorded.
**Where:** `semantic_search/streaming.py`, `progress.py`; frontend `shared/api/stream.ts`.

## Smaller decisions worth knowing

### <a id="autoflush"></a>Read before you write in a transaction
SQLAlchemy **autoflushes** pending changes before every query. In `update_job`, a query ran after the first attribute was set, so the edit was flushed early and then again, bumping `version` twice. Rule: do all reads first, then assign attributes.

### Body size limit is middleware, not a dependency
FastAPI reads and parses the whole body before dependencies run. A dependency can't protect memory.
**Where:** `core/body_limit.BodySizeLimitMiddleware`.

### The 500 handler sits inside the middleware stack
Starlette's own handler runs outside CORS and request-id middleware, so its 500s lacked those headers.
**Where:** `core/errors.UnhandledErrorMiddleware`.

### No `pgvector` Python package
asyncpg has no codec for `vector`; sending it as text with a double cast works and saves a dependency.
**Where:** `core/vector.Vector`.

### Only the error class is logged
Database driver messages can contain the values being written (personal data).
**Where:** everywhere: `error_type=type(exc).__name__`; `core/errors.describe_error`.

### `ENVIRONMENT` has no default
A deploy that forgets it fails at startup instead of running with development cookies and secrets.
**Where:** `core/config.Settings.environment`.

Next: [09-testing-and-debugging.md](09-testing-and-debugging.md).
