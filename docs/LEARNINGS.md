# Project Learnings

A running log of things learned about this project: decisions, gotchas, provider quirks, and surprises. **Append** a new entry whenever something non-obvious is discovered; don't rewrite history. If a learning turns out to be wrong, add a new entry that corrects it and mark the old one `~~superseded~~`.

## Entry format
```
### YYYY-MM-DD: <short title>
- **Context:** what we were doing
- **Learning:** what we found out
- **Impact / action:** what we changed or must remember
```

---

### 2026-10-27: Project goal and scale
- **Context:** Project kickoff.
- **Learning:** Goal is to source candidates for job roles via APIs + AI search, then rank them per role. Target: ingest at least 1,000 new candidates. Whether that's per day or one-off is not yet confirmed.
- **Impact / action:** 1,000+ is small. Postgres + pgvector is enough; no separate vector DB needed.

### 2026-10-27: Do not scrape LinkedIn
- **Context:** Choosing data sources.
- **Learning:** LinkedIn's ToS forbids scraping and LinkedIn has sued over it. Proxycurl, a popular LinkedIn-data API, shut down in 2025 after LinkedIn took legal action. There is no public LinkedIn people-search API; LinkedIn Recruiter data only flows to approved ATS partners.
- **Impact / action:** Use licensed providers (People Data Labs, Coresignal, Crustdata), public APIs, and inbound sources only.

### 2026-10-27: Data source plan
- **Context:** Choosing data sources.
- **Learning:** Best low-cost starting set: GitHub API, Hacker News "Who wants to be hired?" (via Algolia HN API; people opt in), resume upload, and Exa for AI search. Scale with People Data Labs or Crustdata. Later: ATS integration via Merge.dev.
- **Impact / action:** Each source is a separate connector behind one `Connector` protocol so sources can be added or removed independently.

### 2026-10-27: Ranking architecture
- **Context:** Designing ranking.
- **Learning:** Multi-stage ranking keeps cost low and quality high: hard SQL filters → hybrid retrieval (BM25 + vector) top ~200 → LLM rubric rerank with evidence → weighted final score → recruiter feedback loop.
- **Impact / action:** Use the expensive LLM only in the rerank stage. Store explanations with every score.

### 2026-10-27: AI hiring is regulated
- **Context:** Production-readiness review.
- **Learning:** Automated hiring tools are regulated: NYC Local Law 144 (bias audits), EU AI Act (employment = high-risk), GDPR/CCPA (consent, deletion, retention).
- **Impact / action:** Redact protected attributes before LLM scoring, keep audit trails, support deletion and export, and run bias checks.

### 2026-10-27: Stack changed to React + Vite
- **Context:** Scaffolding the project.
- **Learning:** User chose React via Vite (not Next.js) for the frontend, and FastAPI + PostgreSQL for the backend.
- **Impact / action:** RULES.md updated. Frontend is a SPA; all server logic lives in FastAPI.

### 2026-10-27: Use Python 3.13, not 3.15
- **Context:** Installing backend dependencies.
- **Learning:** The machine's default `python` is 3.15, and packages like pyyaml (and likely asyncpg/pydantic-core) have no Windows wheels for it. Building from source fails because MSVC Build Tools aren't installed. Python 3.13 is also installed and every dependency has wheels for it.
- **Impact / action:** The venv is created with `py -V:3.13 -m venv .venv`; `pyproject.toml` pins `>=3.13,<3.14`.

### 2026-10-27: Local machine setup
- **Context:** Scaffolding the project.
- **Learning:** No Docker, git, uv, or pnpm on this machine. PostgreSQL 18 runs as a Windows service (`postgresql-x64-18`) on 5432 and requires a password. **pgvector is not installed** in it.
- **Impact / action:** Use venv + pip and npm. Install pgvector for PG18 before building embeddings/ranking (prebuilt Windows binaries or build with MSVC).

### 2026-10-27: Port conflict with the resumeAI project
- **Context:** First smoke test.
- **Learning:** Another local project (`Documents\resumeAI`) runs FastAPI on 8000 and Vite on 5173. Our server silently lost the port race and requests hit the other app (recognizable by FastAPI's default `{"detail": ...}` body instead of our `{"error": ...}` body).
- **Impact / action:** This project uses API port 8010 and frontend port 5180 (`strictPort` so Vite fails loudly instead of picking another port).

### 2026-10-27: Delivery plan: manual intake first, then hybrid search
- **Context:** Planning phases with the user.
- **Learning:** User wants a manual candidate form first (other sources later), then pgvector embeddings, a recruiter job form, and hybrid search (semantic + BM25) to match candidates to jobs.
- **Impact / action:** Plan lives in `phases/`. Phases are built only after the user approves them.

### 2026-10-27: Postgres full-text search is not BM25
- **Context:** Designing hybrid search (Phase 4).
- **Learning:** Postgres's built-in `ts_rank` / `ts_rank_cd` has no inverse-document-frequency weighting or term saturation, so it isn't BM25. True BM25 inside Postgres needs an extension such as ParadeDB `pg_search`, and these ship as Linux builds or Docker images, not for native Windows Postgres.
- **Impact / action:** Keyword search sits behind one `keyword_search` function. ~~ParadeDB in Docker is recommended (decision D1); the tsvector approach is the fallback.~~ *~~superseded~~ 2026-10-29: tsvector is the plan; see "Phase 2/4 decisions".*

### 2026-10-27: Vite template uses oxlint and TypeScript 7
- **Context:** Scaffolding the frontend with create-vite 9.
- **Learning:** The `react-ts` template now ships `oxlint` (not ESLint) and TypeScript 7, and doesn't enable `strict` by default.
- **Impact / action:** Enabled `strict` and `noUncheckedIndexedAccess` in `tsconfig.app.json`; standardized on oxlint.

### 2026-10-27: Postgres rejects NUL characters; Pydantic lets them through
- **Context:** Phase 1 QA, probing the candidate intake API.
- **Learning:** A `\u0000` in any string field passes Pydantic validation, then asyncpg/Postgres fails with `invalid byte sequence for encoding "UTF8": 0x00`, so the API returns 500 instead of 422.
- **Impact / action:** Text inputs that reach Postgres need a NUL check (or stripping) at the schema level. A regression test exists as `xfail(strict=True)` in `backend/tests/integration/test_candidates_api_edge_cases.py`.

### 2026-10-27: FastAPI parses the JSON body before dependencies run
- **Context:** Phase 1 QA, testing the 64 KB body limit (a `max_body_size` dependency).
- **Learning:** FastAPI reads and JSON-decodes the whole body before it resolves route dependencies. A large malformed body therefore returns 422 (not 413), and every oversized body is fully read into memory before the limit applies.
- **Impact / action:** Enforce body size limits in ASGI middleware (or at the reverse proxy), not as a route dependency.

### 2026-10-27: urlsplit and browsers disagree on hosts containing a backslash
- **Context:** Phase 1 QA, checking that LinkedIn/GitHub URL rules match between frontend and backend.
- **Learning:** Given `https://evil.example\@linkedin.com/in/x`, Python's `urlsplit().hostname` returns `linkedin.com`. Browsers (WHATWG URL) treat `\` as `/` and go to `evil.example`. The zod schema rejects the URL but the API accepts it.
- **Impact / action:** Validate host allow-lists on the backend with a WHATWG-compatible parser, or reject `\` and `@` in the authority.

### 2026-10-27: E2E runs on its own ports against the test DB
- **Context:** Adding Playwright while the user's dev servers occupy 8010/5180 (and resumeAI holds 8000/5173).
- **Learning:** Reusing the dev servers would write to the dev DB and use up the in-memory 5/hour rate limit for 127.0.0.1 (every request through the Vite proxy shares that IP).
- **Impact / action:** `npm run test:e2e` starts its own API on 8011 (`candidate_search_test`, migrated first, limit raised) and Vite on 5181 (`vite.e2e.config.ts`), then deletes `e2e-%@example.com` rows in global teardown.

### 2026-10-29: Candidate management page pulls login forward
- **Context:** User asked for a page to search, add, edit and delete candidates.
- **Learning:** That page exposes all candidate PII, so it can't ship without authentication, which was planned for Phase 3.
- **Impact / action:** New Phase 1b contains staff login (DB-backed sessions, argon2id), the candidate management page, and an audit log. Phase 3 shrinks to recruiter accounts + job roles. Admin lookup search uses `pg_trgm` (bundled with Windows Postgres), not the Phase 4 BM25/vector stack.

### 2026-10-29: Phase 1b build gotchas
- **Context:** Building staff login and the candidate management page.
- **Learning:**
  - SQLAlchemy's generic `sqlalchemy.ARRAY` has no `.contains()` (array `@>`). Model columns must use `sqlalchemy.dialects.postgresql.ARRAY`; the database column is identical, so no migration is needed.
  - In this PowerShell environment, piping text into a program (`'x' | python ...`) prefixes a UTF-8 BOM and ends with `\r\n`. `create-admin --password-stdin` strips both; before that fix, the account was created with an invisible character in its password.
  - react-hook-form focuses the first invalid field in *registration order*. A parent component that calls `register()` in its own render registers before child sections (e.g. `<ProfileFields />`). So fields that appear after a shared section must live in a child component placed after it.
  - `array_to_string` isn't IMMUTABLE, so skills can't be trigram-indexed via an expression index. A maintained `lookup_text` column is used instead.
- **Impact / action:** Regression tests exist for the CLI stdin handling, and the e2e "focuses the first invalid field" test guards the form order.

### 2026-10-27: Phase 1 QA bugs resolved
- **Context:** Fix round after the Phase 1 tester's FAIL report; re-verified as PASS.
- **Learning:** Resolutions for the three entries above:
  - NUL characters are rejected for every field by a `field_validator("*", mode="before")` on `_StrictModel`. The xfail markers were removed.
  - The body limit is the ASGI `BodySizeLimitMiddleware` (`core/body_limit.py`). It raises a starlette `HTTPException(413)` mid-read, because FastAPI turns any *other* exception raised while reading the body into a 400.
  - URLs containing `\`, whitespace, control characters or any `@` in the authority are rejected on both sides. `urlsplit` can also raise `ValueError` (NFKC-unsafe hosts), whose message echoes the input, so it is caught and replaced.
- **Impact / action:** Also, `search_document` now redacts *every* typed field, not just free text. Pydantic lax mode coerces `true` to `1`, so use `StrictBool`/`StrictInt` for fields the UI always sends typed. And the browser `URL` parser reports `https://@host` as an empty username, so check the raw authority text for `@`.

### 2026-10-29: Phase 1b QA: cursors are the remaining 500 path
- **Context:** Phase 1b QA, tampering with the search cursor on `GET /admin/candidates`.
- **Learning:** The cursor shape is validated, but the *values* are not checked against what Postgres can store. Two crafted cursors give a 500 instead of 400: a `name`-sort cursor whose `key` contains `\u0000` (asyncpg rejects the NUL byte), and an `experience`-sort cursor with `key` like `1e999999` (asyncpg cannot encode the Decimal exponent). `Infinity`, `NaN`, naive datetimes and year-1/9999 datetimes are handled fine. Regression tests are `xfail(strict=True)` in `backend/tests/integration/test_admin_candidates_edge_cases.py`.
- **Impact / action:** Cursor decoding should reject NUL, and bound/`is_finite()` the Decimal, mapping failures to `InvalidCursorError`. Also: httpx `ASGITransport` re-raises unhandled app exceptions, so a 500 shows up in tests as a raised exception rather than a status code.

### 2026-10-29: e2e staff users are created through the real CLI
- **Context:** Adding the Phase 1b Playwright flow.
- **Learning:** `e2e/support/backend.ts` now has `createE2eStaff` (runs `python -m app.cli create-admin --password-stdin` against the test DB). The global teardown deletes `e2e-%@example.com` candidates, the audit rows those users wrote, then the users. Audit rows about *deleted candidates* made by e2e staff are removed too because they are matched by actor.
- **Impact / action:** Use `e2e-...@example.com` emails for any new e2e staff or candidates so cleanup finds them.

### 2026-10-29: Cursor values and accessible names
- **Context:** Fixing the Phase 1b QA findings.
- **Learning:**
  - The two cursor 500s above are fixed in `repository.parse_sort_key`: name keys with NUL or over 500 characters, and experience keys that are non-finite or outside 0 to under 100, raise `ValueError`, which becomes 400 `invalid_cursor`. The xfail markers were removed. Anything decoded from a cursor bypasses the Pydantic schema checks, so it needs its own validation before it reaches Postgres.
  - Adding row actions with `aria-label="Edit <name>"` broke e2e locators like `getByRole('link', { name: fullName })`, because Playwright matches accessible names as case-insensitive substrings by default.
- **Impact / action:** Use `exact: true` when locating by a name that other labels may contain.

### 2026-10-29: Phase 2/4 decisions: OpenAI, Celery + Redis, tsvector, no Docker
- **Context:** User decided D1-D3 while planning Phase 2 (embeddings).
- **Learning:**
  - **D2:** OpenAI `text-embedding-3-small` (1536 dims, ≈ $0.01 per 1,000 candidates) replaces the Voyage / local-model options. ~~superseded~~ (2026-10-29 simplification: now the `openai` SDK) It is called over `httpx` + `tenacity`, not the `openai` SDK (one endpoint, and the SDK's own retries would stack on ours). pgvector's HNSW index caps `vector` at 2,000 dimensions; 1536 fits.
  - ~~superseded~~ (2026-10-29 simplification: Postgres queue) **D3:** Celery + Redis replaces the draft's Postgres `embedding_jobs` queue. Instead of a transactional outbox, candidates are enqueued after commit (fire-and-forget) and a Celery Beat sweeper (every 5 min) re-queues anything missing or stale by `content_hash`, so lost messages self-heal. Failures go to `embedding_failures`.
  - **D1:** No Docker, so ParadeDB / `pg_search` (true BM25) is dropped. pgvector goes into the Windows Postgres 18 service from a prebuilt community binary (no MSVC here), and Phase 4 keyword search uses `tsvector` + GIN + `ts_rank_cd` behind `keyword_search()`. This supersedes the "ParadeDB in Docker is recommended" action in the 2026-10-27 BM25 entry.
  - ~~superseded~~ (no Redis at all now) **Redis install is deferred** (Memurai, Docker or WSL, decided later). Phase 2 is testable without it: eager mode in tests, `embed-backfill --sync` for real embedding.
  - ~~superseded~~ (Celery-specific; the boundary exception at the end still holds) Design consequences worth remembering: Celery's eager mode would run a sync task inside the API's running event loop, where `asyncio.run` raises, so in eager mode `enqueue_candidate_embedding` awaits the service in-process instead. `apply_async` is blocking I/O with default publish retries, so it runs in `asyncio.to_thread` with `retry=False` and a short timeout. The embeddings repository reads `candidates.id` / `search_document` directly for the stale-candidate join, a documented exception to the feature-boundary rule.
- **Impact / action:** `phases/README.md` decisions table and the Phase 2 and Phase 4 docs are updated. When pgvector is installed, add an entry with the binary's source URL and version; when the worker first runs on Windows, confirm `--pool=solo`.

### 2026-10-29: pgvector 0.8.7 installed into Windows Postgres 18.6
- **Context:** Phase 2 prerequisite; no C++ build tools on this machine, so a prebuilt binary was used.
- **Learning:**
  - Source: `https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/0.8.7/vector.v0.8.7-pg18.zip` (unofficial community build). SHA-256 `7C4AE0E2B2CB1E547779209A34A7D3F05B82FD7912818BF3D7042266EDA87E7D`.
  - Checked before install: `vector.control` matches upstream, the SQL scripts contain no grants/roles/`COPY ... PROGRAM`, and the unsigned `vector.dll` imports only `KERNEL32.dll` and `postgres.exe`.
  - Copied `lib\vector.dll`, `share\extension\vector*` and `include\server\extension\vector` into `C:\Program Files\PostgreSQL\18` (needs admin / UAC). A fresh install doesn't need a Postgres restart.
  - Verified in a rolled-back transaction: `CREATE EXTENSION vector` gives 0.8.7, cosine distance works, an HNSW index builds.
  - The app's DB role is a **superuser**, which is why `CREATE EXTENSION` works from migrations. RULES §10 wants least-privilege roles, so staging/production need a non-superuser app role with extensions created by an admin (or a migration role).
- **Impact / action:** Upgrading pgvector means replacing these files with Postgres stopped, then running `ALTER EXTENSION vector UPDATE`. Windows Postgres updates (EDB installer) may not touch these files, but check that `vector` still loads after a major upgrade.


### 2026-10-29: Phase 2 build: pgvector, asyncpg and Celery gotchas
- **Context:** Building embeddings + pgvector (Phase 2) with the async-only SQLAlchemy stack.
- **Learning:**
  - asyncpg has no codec for the `vector` type, so a bound vector parameter fails. `app/core/vector.py` sends the vector as text and wraps it as `CAST(CAST(:p AS TEXT) AS vector(n))` (the inner cast pins the parameter type), so the `pgvector` Python package is not needed. Alembic autogenerate logs "Did not recognize type vector" while reflecting; `alembic check` still reports no drift.
  - The HNSW index is only chosen when `ORDER BY embedding <=> $1 LIMIT k` runs alone on `candidate_embeddings`. Joining `candidates` in the same query (for headlines) produced a Sort plan. The similarity statement therefore keeps the nearest-neighbour query in a subquery and joins headlines on the few rows it returns. On a near-empty table the planner prefers the unique index plus a sort even with `enable_seqscan = off`, so the EXPLAIN test loads 1,500 synthetic vectors (replica role skips the FK) and runs ANALYZE first.
  - (Still true for any standalone process, so `register_all_models()` stays for the CLI/worker; `run_async` is gone.) A Celery worker imports only `app.features.embeddings.tasks`, so `candidates`/`users` tables are missing from `Base.metadata` and the first insert raises `NoReferencedTableError`. `core.db.register_all_models()` imports every `features/*/models.py` by name; `run_async` and the CLI call it.
  - ~~superseded~~ (one loop per process now; the SDK client lives on it and is closed in `finally`) The OpenAI provider is cached process-wide, but Celery tasks each run `asyncio.run`, and an `httpx.AsyncClient` must not outlive its loop. The provider opens a client per request unless one is injected (tests inject `httpx.MockTransport`).
  - Sync tests that call `run_async`/`asyncio.run` must `await get_engine().dispose()` at the end of any async fixture that used the DB, or pooled connections from the fixture's loop crash on the other loop.
  - ~~superseded~~ (Celery removed) `task.apply()` retries eagerly and ignores the countdown, so retry behaviour is testable without Redis. `Retry` raised by `self.retry` is only converted to `MaxRetriesExceededError` once `request.retries` reaches `max_retries`.
  - ~~superseded~~ (Celery removed) mypy: Celery has no stubs; use `ignore_missing_imports` for `celery.*` plus `disallow_untyped_decorators = false` for the tasks module.
- **Impact / action:** `embed_candidates` never raises provider errors; it dead-letters them and returns counts, and the task wrapper decides on retries (`transient_failed_ids`). Failure rows are keyed by `content_hash`, so a retried or edited document escapes the dead letter automatically.

### 2026-10-29: Deliberate boundary exception: embeddings reads `candidates` through a Core table
- **Context:** RULES section 2 says a feature may not touch another feature's models or repository.
- **Learning:** The stale-embedding query must join `candidates` with `candidate_embeddings` and hash `search_document` in SQL (`encode(sha256(convert_to(...)), 'hex')`, equal to Python's SHA-256 of the UTF-8 text; a test covers non-ASCII text). Going through the candidates public API would load every document into Python.
- **Impact / action:** `embeddings/repository.py` reads `candidates.id`, `search_document` and `headline` only (the headline feeds the `similar-candidates` dev command) via a `sqlalchemy.table()` reference, read-only. All writes to candidates stay in the candidates feature. Never add PII columns to that table reference.

### 2026-10-29: Settings, startup and tests for embeddings (~~superseded~~ except the "no key raises at first use, API still boots" part; see "Simplification refactor" below)
- **Context:** Wiring `EMBEDDING_PROVIDER`, `OPENAI_API_KEY` and eager mode.
- **Learning:** `Settings` switches to the fake provider and eager mode when `ENVIRONMENT=test` and the variables are unset, and the root `conftest.py` also forces `EMBEDDING_PROVIDER=fake` and `CELERY_TASK_ALWAYS_EAGER=true`, so a developer's `.env` can never send tests to OpenAI or Redis. A missing `OPENAI_API_KEY` with the `openai` provider raises `EmbeddingConfigurationError` when the provider is first built (worker, CLI, or an eager save), not when the API boots, so the API still starts on machines with no key.
- **Impact / action:** `/ready` shows `redis: false` until Redis is installed; that is expected and does not fail readiness.
### 2026-10-29: Phase 2 QA: blank API key, 2 s save penalty, one slow test
- **Context:** Phase 2 QA of embeddings + pgvector.
- **Learning:**
  - `OPENAI_API_KEY=` (blank, as copied from .env.example) loads as `SecretStr("")`, not `None`, so `build_embedding_provider` builds a provider that sends `Bearer ` and dead-letters every candidate with 401. It also makes `test_factory_requires_api_key_for_openai` fail whenever `backend/.env` has the line, because pydantic still reads `.env` after conftest pops the process variable. Regression test: `xfail(strict=True)` in `app/core/tests/test_embeddings_edge_cases.py`.
  - ~~superseded~~ (no broker now) With Redis down, every save costs about 2.0 s (kombu connect timeout), even for a refused connection on Windows. The event loop is not blocked (max stall about 20 ms).
  - `test_similarity_query_uses_the_hnsw_index` is the only slow test: about 12 s normally (1,500 inserts into the HNSW index), but 173 s once in a full run. Building the index after the insert takes about 1.6 s.
- **Impact / action:** Treat blank keys as unset. Consider creating the index after the bulk insert in that test.


### 2026-10-29: Phase 2 fix round: blank keys, slow publishes, test hygiene
- **Context:** Fixing tester findings on the embeddings pipeline.
- **Learning:**
  - `OPENAI_API_KEY=` in `.env` loads as `SecretStr("")`, not `None`, so an `is None` check treats it as configured and every request goes out as `Bearer ` (401, dead letter). The factory now strips the key and rejects blank and the `sk-CHANGE_ME` placeholder. Tests of settings must use `Settings(_env_file=None, ...)`, or a developer's `.env` leaks in.
  - ~~superseded~~ (background publish and circuit breaker removed) Awaiting the broker publish from the request cost about 2 s per save while Redis was down (kombu connect timeout). Publishing is now a background task with strong references plus a 30 s circuit breaker. `drain_background_publishes()` (also run at app shutdown and by an autouse integration fixture) prevents tasks leaking across tests or loops.
  - Python's JSON parser accepts `NaN` and `Infinity`; a provider response with them would reach Postgres and fail there with no dead-letter row. Responses with non-finite vectors or token counts are now permanent errors, and every non-transport `httpx` error is mapped to transient (decoding) or permanent.
  - `capsys` in one test can break later tests: structlog caches loggers on first use bound to the captured `sys.stdout`, which pytest then closes ("I/O operation on closed file" inside unrelated logging calls). Stub the module logger instead of using `capsys`.
  - A bulk-load test for planner behaviour is fast when the HNSW index is dropped, loaded, analyzed and recreated inside one rolled-back transaction (about 2 s instead of 13 s or more).
  - Phase 1b regression: a mojibake edit of the hostile-Unicode probe in `test_admin_candidates_edge_cases.py` was restored to `\u00df \u0130 \u01c5` (ss, dotted I, titlecase DZ-like digraph) escapes.
- **Impact / action:** None of these change the public API; the Phase 2 doc records the behavioural deviations.
### 2026-10-29: Phase 2b build notes (AI spend metering)
- **Context:** Building `ai_usage` (reserve -> call -> settle, $5 lifetime cap) while Phase 2 was still being tested in the same repo.
- **Learning:**
  - The integration conftest TRUNCATEs every table, including the migration-seeded `ai_budget` row, so the service creates a default $5.00 row on demand (`_ensure_budget`, under the advisory lock) and the summary falls back to 5.00 when none exists. The migration seed itself was checked with a manual downgrade/upgrade on a scratch DB.
  - `pg_advisory_xact_lock` is held only for the reserve transaction, never during the provider call, so slow calls do not serialise other workers. Pending reservations count as spent, so concurrent callers cannot jointly overshoot the limit.
  - Per-model/operation totals count `succeeded` rows only so they add up to "spent"; blocked and failed events carry cost 0 and 0 tokens.
  - Two sessions sharing one test DB break each other (truncate + migrate). Use a separate DB through `TEST_DATABASE_URL`; `backend/.env` points `alembic` at the dev DB, so only override `DATABASE_URL` explicitly when running alembic by hand.
  - `PS 5.1 Set-Content -Encoding utf8` writes a BOM; Python sources should be written BOM-free.
- **Impact / action:** UI is dark-only; colours come from semantic tokens in `frontend/src/index.css` (`@theme`). Do not use raw palette classes in components.

### 2026-10-29: AI budget hook into embeddings
- **Context:** Wiring `ai_usage.metered_call` into `embeddings.service._embed_batch`.
- **Learning:**
  - A refused call (budget or missing price) marks the run blocked: that batch and every later batch are dead-lettered without another reservation, so one run writes one `blocked` event. Budget refusals use `embedding_failures.last_error='budget_exceeded'`; an unknown model price uses `model_price_unknown`, which is *not* re-driven (re-trying cannot help until a price is added).
  - Only `budget_exceeded` rows are re-admitted as stale, and only while `ai_usage.has_budget_headroom` (spent + pending < limit). (Since the 2026-10-29 simplification, the worker's 5-minute stale scan plays the sweeper's role, with the same `has_embedding_budget` gate.) The Celery sweeper and non-sync backfill skip entirely while there is no headroom, so nothing loops. `embed-backfill --sync` still runs at a $0 limit so it records the blocked state.
  - ~~superseded~~ (fake provider and its price removed) `fake-embedding` has a zero price in `core/ai_pricing.py` and is metered like any model (provider recorded as `fake`), so dev runs without a key appear on the spend page at $0.00.
  - The embeddings unit tests (in-memory repository, no DB) stub `ai_usage.metered_call`; metering itself is covered by integration tests in `tests/integration/test_ai_usage_embeddings.py`.
- **Impact / action:** A Celery task never retries budget blocks; raising the limit is what resumes embedding, via the next sweep.

### 2026-10-29: Phase 2b QA: budget cap holds; edge cases found
- **Context:** QA of AI spend tracking (tests in `backend/tests/integration/test_ai_usage_edge_cases.py`).
- **Learning:**
  - Cap holds under 12 concurrent reservations and for truncated text (estimate uses the 24,000-char cut). Overspend is possible but bounded: one call can exceed the reservation by (actual - estimate) tokens (chars/4 under-counts dense or non-English text), then every later call is blocked.
  - `ai_budget.limit_usd` is numeric(10,2): tests cannot set a sub-cent limit. To get tiny headroom, set 0.01 and insert a `succeeded` event for 0.009999.
  - `last_event_blocked` is "latest event is blocked", so the card stays red with "raise the limit" text after an admin raises the limit, until another AI call is logged (xfail strict test).
  - With headroom smaller than one estimate, the sweeper re-queues blocked candidates every 5 min and each task writes one more `blocked` event (one per candidate, not one per sweep).
  - `metered_call` catches `Exception` only; a CancelledError leaves a `reserved` row that counts as pending forever. A 200 response that fails parsing is billed by OpenAI but settles at $0.
- **Impact / action:** Consider a reservation reaper, a sweeper pre-check using the next estimate, and clearing the blocked flag when the limit changes.

### 2026-10-29: First real embedding backfill: actual tokens and cost
- **Context:** Ran `embed-backfill --sync` against the dev DB with OpenAI `text-embedding-3-small`; the user capped spend at $0.50.
- **Learning:**
  - 1,001 candidates: 801,902 characters of `search_document` became **178,785 tokens** (~179 per candidate, ~4.5 characters per token). Cost was **$0.0036**, in 17 batches (64 per batch, the backfill runs in chunks of 500), 58 s, 0 failures. The `chars / 4` reservation estimate in `core/ai_pricing.py` came out slightly high, which is the safe direction.
  - Worst-case bound used before running: a BPE token is at least 1 byte, so tokens ≤ bytes (0.8M), and the cost is ≤ $0.016. Failed requests aren't billed, so retries can't multiply the cost.
  - Sanity check: the 10 nearest neighbours of a "Senior Backend Engineer" (cosine 0.83–0.88) are all backend engineers.
- **Impact / action:** Re-embedding everything (e.g. after a model change) costs about $0.004 per 1,000 candidates; 1M candidates would cost about $3.60.

### 2026-10-29: Phase 2b QA fixes: blocked flag, event spam, cancellation, billed parse failures
- **Context:** Fixing the Phase 2b tester findings.
- **Learning:**
  - `ai_budget.updated_at` (auto-updated by the ORM `onupdate`) is the "last limit change" marker. The summary's `last_event_blocked` and the blocked-event dedupe both compare the newest event's `created_at` with it. `created_at` is `now()`, i.e. transaction start, so a refusal that began before a limit change but ran after it looks older and is recorded again; that is harmless.
  - Dedupe of repeated refusals means the page no longer lists every refused call; the tester's concurrency test now expects one `blocked` row for 10 identical refusals, while the zero-provider-calls and reserved-sum cap assertions are unchanged.
  - `asyncio.CancelledError` is a `BaseException`; `except Exception` misses it. Settle inside `asyncio.shield` so the DB write finishes even though the task is being cancelled.
  - A 200 response that fails parsing is still billed. `PermanentEmbeddingError.billed_tokens` carries `usage.total_tokens`; such `failed` events have a cost, so spent and the per-model/operation totals include `failed` events with `cost_usd > 0` (zero-cost failures remain excluded).
- **Impact / action:** Any new status that can carry cost must be added to `get_spend_amounts` and `totals_by` in `ai_usage/repository.py`.


### 2026-10-29: "Dossier desk" design system (frontend redesign)
- **Context:** User found the navy/indigo, system-font, rounded-card UI too generic and chose the "Dossier desk" direction (recruiter case file / records office).
- **Learning:**
  - Palette (dark-only, warm graphite + brass; tokens in `src/index.css` `@theme`, same token names as before so components kept working): surface `#161512`, raised `#1e1c18`, muted `#27241f`, border `#3a352d`, border-input `#8a8068` (>=3:1), fg `#ede6d8`, fg-muted `#b8ae9c`, fg-subtle `#a39a88`, accent (brass) `#c9a45c`, accent-fg (link text) `#dcb872`, on-accent ink `#1a160e`, focus `#dcb872`. Semantics stay separate from brass: danger brick `#b33a2a` (text `#ee8c7a`), success sage `#6f9b5a` (text `#a8cb94`), warning burnt orange `#dd6b20` (text `#f2a266`).
  - Fonts are self-hosted via `@fontsource` (no third-party requests from a PII tool): Schibsted Grotesk 600 = display (wordmark, page titles, candidate names), IBM Plex Sans 400/500/600 = body/UI, IBM Plex Mono 400/500 = data.
  - Rule: **figures and identifiers are mono.** Years (always one decimal, `06.5` via `formatYears`), costs, tokens, counts, dates/times, emails, URLs, IDs and cursors use the `num` utility (mono + tabular-nums). Uppercase small labels and column headers use the `caps` utility (12px, letter-spaced).
  - Shapes: 2-4px radii, ruled 1px lines instead of cards; card styling only for dialogs and the budget card; shadows only on dialogs. Status/source/work-mode/skills are `Stamp` chips (bordered uppercase mono). Shared primitives: `Stamp`, `Meter`, `PageHeader`, `FieldError`, `linkButtonClass` in `src/shared/ui`.
  - Layout: staff pages use `RootLayout` (fixed sidebar, top bar below `md`); login, intake, privacy and 404 use `PublicLayout` (single column).
  - Gotchas: Tailwind preflight makes inputs inherit letter-spacing, so `inputClass` resets `tracking-normal normal-case`. Grid pages need `grid-cols-[minmax(0,1fr)]` or an `overflow-x-auto` table widens the whole page on phones. Windows PowerShell 5.1 `Get-Content`/`Set-Content` corrupts non-ASCII (en dash became mojibake) and adds a BOM; edit files with the Edit tool. Concurrent e2e/pytest runs share the test DB and its teardown deletes `e2e-%` users, causing spurious login/duplicate-email failures; re-run alone.
- **Impact / action:** New UI must use the tokens and the mono rule; no raw palette classes, no `rounded-lg`/`shadow-` outside dialogs. The search API returns no total, so the header shows "Showing N candidates" rather than "N on file"; a total needs a backend field.
### 2026-10-29: Phase 2b fix-round QA
- **Context:** Re-verifying blocked-flag, blocked-event dedupe, cancellation and billed-failure fixes.
- **Learning:**
  - `settle_success` is not shielded, so cancelling a worker while the success settle waits (DB lock or slow commit) leaves a `reserved` row: a billed call is never recorded and counts as pending forever. Only the failure path is shielded. Strict xfail in `test_ai_usage_edge_cases.py`.
  - A PUT /budget with an unchanged limit still changes `updated_by`, which bumps `ai_budget.updated_at`, so it clears `last_event_blocked` and restarts blocked-event dedupe though nothing changed. Strict xfail.
  - Blocked dedupe only compares the newest event, so alternating models/operations (A,B,A,B) record a row per refusal; bounded only because callers use one model.
  - `created_at`/`updated_at` use `now()` (transaction start), so a reserve that waited on the advisory lock can carry a timestamp older than a limit change it observed.
  - Integration tests that count candidates failed once or twice per full run with `1 == 0`, passing alone: something else (probably a concurrent e2e run) writing candidates to `candidate_search_test` while pytest runs. Do not run e2e and pytest at the same time.
- **Impact / action:** Shield `settle_success` too; compare against the limit value, not `updated_at`, if exactness matters.

### 2026-10-29: Phase 2b final fixes: shielded success settle, no-op limit PUT
- **Context:** Fixing the two strict xfails from the fix-round QA.
- **Learning:**
  - `settle_success` now runs inside `asyncio.shield`, like `settle_failure`. The shielded settle keeps running after the caller's `CancelledError`, so a test that holds a row lock must release that lock *before* closing the settle's session, then poll for the final status. Closing the session first deadlocks: the session waits for the settle, and the settle waits for the lock.
  - `update_budget` only assigns `limit_usd`/`updated_by` when the limit actually changes. An unchanged PUT is still audited but leaves `updated_at` alone, so the blocked flag and the blocked-event dedupe aren't reset.
- **Impact / action:** Both xfails removed; full backend suite 465 passed, 5 xfailed (older, unrelated).

### 2026-10-29: Dossier desk QA
- **Context:** QA of the frontend redesign (vitest 103, oxlint, build, e2e 11 + new `e2e/design-qa.spec.ts`).
- **Learning:**
  - Recomputed contrast: every text token is >= 4.5:1 on every surface it is used on (lowest: fg-subtle on accent-soft-hover 4.66, fg-subtle on surface-muted 5.55). `danger-meter` #d4553d is 3.80:1 on the meter track (surface-muted) and 4.49 on surface, so it passes 3:1. Input border #8a8068 is 4.67 on surface, 4.35 on raised. Only *disabled* states fall below AA (disabled primary button 3.52, disabled danger text 2.77), which WCAG exempts.
  - `document.fonts.check()` returns false for faces not yet used on the page; use `document.fonts.load()` to assert self-hosted fonts really load. Playwright's `getByRole(..., {exact:true})` still hits duplicates if a spec reuses candidate names across tests; use a per-test unique name.
  - PowerShell here-string/double-quoted string edits to .ts files mangle `${...}` template literals; use the Edit tool.
- **Impact / action:** `DESIGN_QA_DIR=<dir> npx playwright test design-qa` also saves screenshots for 16 pages at 1440x900 and 400x860.

### 2026-10-29: Simplification refactor: OpenAI SDK, Postgres job queue, no fake provider
- **Context:** The user found Phase 2 over-built for about 1,000 candidates:
  - raw `httpx` + `tenacity` reimplemented the SDK's retries and `Retry-After` handling;
  - Celery + Redis, the Beat sweeper, the background publish and the circuit breaker existed only to cope with a Redis that was never installed;
  - the fake provider added a second code path.

  The user directed the redesign. It is recorded in `phases/phase-2-embeddings-pgvector.md` (revision 2026-10-29).
- **Learning:**
  - **Queue.** An `embedding_jobs` row is upserted in the same transaction as the candidate save, as an outbox, so no message can be lost and no lost-message sweeper is needed.
    - The worker is `python -m app.cli embed-worker [--once]`. It claims with `FOR UPDATE SKIP LOCKED` and leases by pushing `run_after` out.
    - A `generation` counter stops an edit made mid-embedding from being deleted with the old job.
    - Rows exist only while work is pending, so there are no status or error columns. `embedding_failures` stays the dead letter, which keeps Phase 2b and its tests intact.
  - **Re-drive.** A stale scan still exists for budget re-drive, model changes and crash leftovers. It runs every 5 minutes inside the worker (and in `embed-backfill`), gated by `has_embedding_budget`. Budget-blocked jobs are deleted, never retried with backoff.
  - **Shutdown.** `asyncio.run` cancels *all* remaining tasks on exit, including the inner task protected by `asyncio.shield` in `ai_usage.metered_call`. Relying on cancellation for Ctrl+C would therefore orphan `reserved` events. The worker uses its own SIGINT handler: the first press sets a stop event and the in-flight batch finishes; the second press forces exit.
  - **openai SDK 3.x** (3.41.0 on 2026-10-28) runs on **`httpx2`**, not `httpx`:
    - `AsyncOpenAI(http_client=...)` needs an `httpx2` client, and test doubles use `httpx2.MockTransport`;
    - injecting legacy `httpx` is a deprecated escape hatch;
    - `httpx` stays only as a dev dependency for FastAPI's `ASGITransport`.
  - **SDK behaviour to remember:**
    - It retries 408/409/429/≥500 and connection errors itself (default 2 retries; we set 3 explicitly).
    - It reads `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_LOG` from the environment unless values are passed explicitly. We pass `api_key` and `base_url`, never set `OPENAI_LOG` (debug logs include inputs), and tests pop those variables.
    - Its retry loop catches `Exception`, so a test network guard must raise a `BaseException` (`pytest.fail`) or the SDK turns it into a retried `APIConnectionError`.
  - **Tests.** The fake provider, `EMBEDDING_PROVIDER` and the `fake-embedding` $0 price are gone. Tests run the real provider over a mocked transport with deterministic vectors, a dummy key and a guard that fails any real network call. They meter at the real `text-embedding-3-small` price, which is tiny; the integration conftest truncates `ai_budget` per test, so the $5 cap is never reached by accident.
  - **Dependencies.** `tenacity`'s only use was the embeddings provider, so it is removed until a connector without an official SDK needs it. RULES §1 (background jobs) and §7 (SDK retries are acceptable where the official SDK provides them) are updated.
- **Impact / action:**
  - Without `OPENAI_API_KEY`, saves still work and jobs queue up, but nothing can be embedded locally: there is no offline provider.
  - The per-text fallback on a permanent batch error was kept. The worker claims 64 jobs per batch, and 24,000 characters of CJK text can exceed the 8,191-token limit, so one bad input would otherwise dead-letter 63 neighbours.
  - Re-adding Celery later is a new decision, not a rollback of this one.

### 2026-10-29: Phase 2 simplification refactor: SDK behaviour and test-harness gotchas
- **Context:** Replacing httpx + tenacity with `openai==3.31.0`, Celery + Redis with the Postgres `embedding_jobs` queue, and the fake provider with a mocked HTTP transport.
- **Learning:**
  - openai 3.31.0 runs on `httpx2` 2.16.0 (plus `httpcore2`, `jiter`, `truststore`, `sniffio`); all install from wheels on Windows / Python 3.13. `AsyncOpenAI(http_client=...)` takes an `httpx2.AsyncClient`, and the SDK exception classes match the design (`APIConnectionError` > `APITimeoutError`, `APIStatusError` > `RateLimitError` / `InternalServerError`).
  - A **200 whose body is not JSON** escapes the SDK as a raw `json.JSONDecodeError` (a `ValueError`), not an `OpenAIError`. `embed_documents` catches `ValueError` and raises `PermanentEmbeddingError("malformed provider response")`. Malformed-but-JSON bodies (missing `usage`, `data` as a string) are not validated by the SDK; they fail on attribute access and are caught by the existing parse checks.
  - The SDK honours `retry-after-ms`, so tests that exercise its retry (`max_retries=1`) send that header to keep the backoff at a millisecond.
  - Network guard: `pytest.fail` is a `BaseException`, so the SDK's retry loop (it catches `Exception`) cannot turn it into a connection error. It patches `handle_async_request` / `handle_request` of both `httpx2` and `httpx` transports; `MockTransport` and `ASGITransport` are different classes and unaffected.
  - The CLI embedding commands close the process-wide provider in `finally` (one `asyncio.run`, then the slot is empty). A sync test that runs a second embedding command must install a fresh mocked provider first (`use_embedding_provider(openai_provider())`), otherwise the SDK's real transport is built and the guard fails the test.
  - `run_embedding_worker` does not close the provider; the CLI wrapper does. Tests call the worker several times against the one installed mock.
  - An unchanged `PUT /admin/candidates/{id}` does not bump `version`, so a "stale version" test must change a field in both requests to get a 409.
  - Ctrl+C handling on the Windows Proactor loop (acceptance criterion 9) is implemented per the design and unit-tested through the handler, but not exercised by hand yet.
- **Impact / action:** `tenacity` must come back (RULES §7) with the first connector that has no SDK retry layer. `TransientEmbeddingError` no longer has `retry_after_seconds`; the SDK consumes `Retry-After` itself.

### 2026-10-29: QA of the simplification refactor: real Ctrl+C test and PowerShell env gotcha
- **Context:** Phase 2 revision QA (acceptance criteria 2, 9, 10), tester pass.
- **Learning:**
  - Ctrl+C on the Windows Proactor loop works. `tests/integration/test_embedding_worker_signal.py` runs the real `app.cli` `embed-worker` in a hidden-console child (OpenAI mocked inside the child) and delivers a real CTRL_C_EVENT from a detached helper that does `AttachConsole(pid)` + `SetConsoleCtrlHandler(None, True)` + `GenerateConsoleCtrlEvent(0, 0)`. `CTRL_BREAK_EVENT` would not test this: it raises SIGBREAK, which the worker does not handle. In-flight: log shows `embedding_worker_stopping`, the batch settles as `succeeded`, exit code 0, no `reserved` event, about 3 s.
  - In PowerShell, `$env:OPENAI_API_KEY = ''` deletes the variable instead of blanking it, so the key in `.env` loads. To simulate a blank key use a single space (the provider strips it) or the placeholder `sk-CHANGE_ME`. Never use an empty string when the test DB might hold candidates.
  - `structlog.testing.capture_logs()` is order-dependent here: `configure_logging` uses `cache_logger_on_first_use=True`, so loggers already used by an earlier test ignore the capture. Patch the module's `logger` with a recording stub instead.
- **Impact / action:** Use those patterns for any new worker, CLI or log-content test.
### 2026-10-29: Plain light/dark design system replaces "Dossier desk"
- **Context:** User found the UI "stuffed" and asked for simple black/white with blue, red and green highlights.
- **Learning:**
  - Blue is the only primary/accent colour (buttons, links, active nav, focus ring); red is for errors, destructive and over-budget; green for success/healthy. Amber survives only for "near limit", "reserved" and "degraded" states.
  - Token names in `src/index.css` are unchanged (`accent`, `danger`, ...) so components kept working. Light values live in `@theme`; `@media (prefers-color-scheme: dark) { :root { ... } }` overrides the same variables (unlayered `:root` beats Tailwind's layered theme variables). `color-scheme: light dark`.
  - System font stack only; the @fontsource imports were removed from `main.tsx` (the packages are still in package.json and can be uninstalled). `caps` is now a plain sentence-case label style and `num` is just `tabular-nums`; both names are kept so existing markup works.
  - White text on blue needs `#2563eb` or darker (5.17:1); a lighter blue like `#3b82f6` fails 4.5:1, so the dark theme keeps the same button blue and uses a lighter blue only for link text and the focus ring.
  - Playwright default colour scheme is light; use `page.emulateMedia({ colorScheme: 'dark' })` to test dark overrides.
- **Impact / action:** Never use raw palette classes or hex in components; add new colours as tokens with both light and dark values and check contrast.

### 2026-10-29: The dev servers run whatever is on disk, including another session's half-finished work
- **Context:** The user couldn't sign in while the Phase 3 session was mid-build.
- **Learning:**
  - The user's `uvicorn --reload` API (port 8010) and Vite (5180) reload on every saved file. New auth code that read `users.must_change_password` went live before its migration (`b3d7f1a94c20`) was applied to the dev DB, so every real login returned 500.
  - The login endpoint's CSRF guard returns 403 unless `X-Requested-With: fetch` is sent. Probe it with that header, or you only ever see the 403.
  - Vite listens on `::1` only, so `http://127.0.0.1:5180` fails with "unable to connect" while `http://localhost:5180` works.
- **Impact / action:** When code that depends on a new migration lands, apply that migration to the dev DB (additive ones only, or check with the owner) or the running app breaks. When "the server is down", check `alembic current` against `alembic heads` first.

### 2026-10-29: Search query strings leak through uvicorn's access log; e2e API would use the real OpenAI key
- **Context:** Designing Phase 4a (semantic search over the Candidates search box).
- **Learning:**
  - `RequestContextMiddleware` logs only the path, but uvicorn's own `uvicorn.access` logger (on by default; we run plain `uvicorn app.main:app`) prints the full request line, including `?q=<name or email>`. This already leaks staff search text from Phase 1b.
  - The e2e API process (port 8011) loads `backend/.env`, which holds a real `OPENAI_API_KEY`. Today nothing embeds inside a request there (`EMBEDDING_WORKER_IN_API=false`). Once search embeds queries in-request, e2e searches would call OpenAI for real unless `e2eEnvironment()` overrides the key.
  - The candidate HNSW index is only chosen when the nearest-neighbour `ORDER BY ... LIMIT` runs on `candidate_embeddings` itself (see "Phase 2 build"). So filters for semantic search are passed as `candidate_id IN (<filtered candidates subquery>)`, with `hnsw.iterative_scan = relaxed_order` so that selective filters still return enough rows.
- **Impact / action:** Phase 4a adds a `uvicorn.access` filter that strips query strings, and sets `OPENAI_API_KEY: 'sk-CHANGE_ME'` in `e2eEnvironment()`, so e2e exercises the keyword fallback.


### 2026-10-29: Phase 3 job embeddings: parallel tables, the EmbeddingTarget descriptor, and the widened boundary exception
- **Context:** Embedding job roles with the Phase 2 queue and worker.
- **Learning:**
  - Jobs get their own tables (`job_embeddings`, `job_embedding_failures`, `job_embedding_queue`) with real foreign keys and `ON DELETE CASCADE`, not an `entity_type` column on the candidate tables. A polymorphic id cannot have a foreign key, and every Phase 2/2b query and test would have changed.
  - The code is single-sourced by a frozen `EmbeddingTarget` descriptor (`features/embeddings/targets.py`: tables, entity column, constraint names for `ON CONFLICT`, ai_usage operation). `repository.py` is written against Core `Table` objects and takes `target=`; the worker loops over `TARGETS = (JOBS, CANDIDATES)`, so a new job is never queued behind a candidate backlog for more than one in-flight batch. The candidate-only `similarity_statement`, `nearest_neighbours` and `load_embedding` stay candidate-specific.
  - **Boundary exception, extended:** `embeddings.repository` now reads `jobs.id` and `jobs.search_document` through a Core `table()` reference, read-only, in addition to `candidates.id` / `search_document` / `headline`. It reads no other `jobs` column and never writes to `jobs`. `jobs.service` reaches embeddings only through `features/embeddings/__init__.py`.
  - Closed jobs keep their embeddings: status is not part of `search_document`, so closing or reopening never re-embeds.
  - Worker fix 1: an unchanged re-save after a *permanent* dead letter used to make one more rejected call. `_embed_target` now loads the failure rows and skips an id whose failure hash equals the current hash and whose `last_error` starts with `PermanentEmbeddingError` (`EmbedOutcome.known_failures`). That prefix is `describe_error`'s output, pinned by a unit test. Transient, `budget_exceeded` and `model_price_unknown` rows are still retried.
- **Impact / action:** Adding a third embedded entity (for example resumes) means three more tables plus one `EmbeddingTarget`. Do not change `describe_error`'s format without updating `is_permanent_failure`.

### 2026-10-29: CurrentUser enforces the forced password change; only SessionUser routes are exempt
- **Context:** Admin-created and admin-reset accounts have a temporary password the admin knows.
- **Learning:**
  - `users.must_change_password` is read from the user row on every request (`resolve_session`), so it applies to sessions that already exist. `get_auth_context` (behind `CurrentUser`, `AdminUser` and `require_role`) raises 403 `password_change_required` when it is set, so every route, including routes added later, is guarded by default. Only `SessionUser` (`GET /auth/me`, `POST /auth/logout`, `POST /auth/change-password`) skips the check, and the public routes (`login`, candidate intake) have no auth at all.
  - A test enumerates every `/api/v1` route and expects 403 for a flagged user. FastAPI 0.162 wraps `include_router` results in private `_IncludedRouter` objects, so `app.routes` no longer lists the real routes: the test walks `app.openapi()["paths"]` instead.
  - Deactivating or resetting deletes all of the user's sessions in the same transaction; change-password deletes the *other* sessions. Role changes need no revocation because the role is also rebuilt from the row on each request. Wrong current passwords are rate limited per user id with the login-failure limits, so a stolen session cannot brute-force the password.
  - Passwords are never whitespace-stripped (`str_strip_whitespace=False` on the password models), otherwise the password the admin read out would differ from the stored one.
  - `User` needed `eager_defaults` (server-generated `created_at`), or building the response after an insert raised `MissingGreenlet` under asyncio.
- **Impact / action:** A new route that must work while a change is pending has to opt in with `SessionUser`; that list should stay at three.

### 2026-10-29: jobs.created_by is RESTRICT, so e2e cleanup deletes jobs before users
- **Context:** Adding `jobs` with an owner.
- **Learning:** Users are only ever deactivated, never deleted, so `jobs.created_by` is `ON DELETE RESTRICT`. The e2e teardown (`CLEANUP_SCRIPT` in `e2e/support/backend.ts`) deletes `jobs WHERE created_by IN (e2e users)` before the audit rows and the users; the embedding tables cascade from jobs. A test that deletes a user directly fails with a foreign-key error until its jobs are gone.
- **Impact / action:** Any new table that references `users` needs the same ordering in the cleanup script.

### 2026-10-29: The embedding worker runs inside the API
- **Context:** The user wanted new candidates and jobs embedded without a second terminal.
- **Learning:**
  - `main.py`'s lifespan starts the worker as a task on the API's event loop (`features/embeddings/background.py`) and stops it before the engine is disposed. Stopping sets the stop event and *waits* (up to 45 s) for the in-flight batch: cancelling a metered call is the one way to leave a `reserved` ai_usage event behind. Only after the wait does it cancel, then close the provider. `install_signal_handlers=False` is passed because uvicorn owns SIGINT/SIGTERM.
  - A missing, blank or placeholder key raises `EmbeddingConfigurationError` before the loop starts; the background task catches it and logs `embedding_worker_disabled`, so the API still boots and saves keep queueing.
  - The worker has one failure policy: any failing step in an iteration (scan, or process per target) is logged as `embedding_worker_iteration_failed` (step and exception class only, never the message), the iteration backs off 5 s doubling to 60 s, and the loop continues; a failed scan retries after 60 s while processing carries on. `--once` raises the first error so cron runs exit non-zero.
  - `backend/.env` holds the real OpenAI key and pydantic-settings reads it for any process started in `backend/`. So the e2e API sets `EMBEDDING_WORKER_IN_API=false` explicitly (otherwise e2e data would be embedded for real), and the root `conftest.py` does the same for pytest. The e2e job spec embeds through a child process with OpenAI mocked (`embedQueuedWithMockedOpenAI`).
  - Under `uvicorn --reload` only the reloaded server process runs the lifespan, so there is exactly one worker, and a reload stops it through the normal shutdown path. The user's dev server therefore makes real, metered OpenAI calls for stale candidates and jobs as soon as it reloads.
- **Impact / action:** Do not run `embed-worker` next to an in-API worker unless you mean to (claims use `SKIP LOCKED`, so it is safe, just redundant).

### 2026-10-29: Phase 3 build gotchas
- **Context:** Building jobs, user admin and the password flow.
- **Learning:**
  - Autoflush bit once: in `update_job`, a query (`get_full_names`) ran after the first attribute was set, flushing the edit, and the later explicit flush wrote it a second time, so one edit bumped `version` by 2. Read everything first, then assign. A regression assertion on `version == 2` guards it.
  - Pydantic constraints on `Decimal | None` (`ge`, `le`) are applied to `None` and raise `TypeError`; put the constraints on an inner `Annotated[Decimal, ...]` and make the union outside.
  - `datetime.fromisoformat` in Python 3.13 accepts a trailing NUL, so NUL in a cursor timestamp is harmless; NUL in the UUID part is rejected by `uuid.UUID`.
  - pgvector columns come back from asyncpg as text through the app's `Vector` type, so tests check dimensions with `func.vector_dims(...)` instead of `len(row.embedding)`.
  - Applying a migration to the dev DB is part of shipping: the user's dev API reloads on every save, so `must_change_password` code ran against a database without the column (every login 500) until `b3d7f1a94c20` was applied. That migration is now applied in a shared environment and must not be edited.
  - Playwright `getByLabel` matches `aria-label` too: the TagInput's added-items list is labelled "<label> added", so locate tag inputs with `getByRole('textbox', ...)`. `TagInput` takes no ref, so react-hook-form cannot focus an invalid tag field.
  - Frontend lint: `watch()` from react-hook-form triggers the React Compiler "incompatible library" warning; `useWatch({ control, name })` does not. Constants exported next to a component trip `only-export-components`, so shared schemas live in their own file.
- **Impact / action:** None beyond the guards above.

### 2026-10-29: Review fixes: last-admin lock, enqueue only on changed text, argon2 limits
- **Context:** A trace of the Phase 3 code found six issues; all fixed with regression tests.
- **Learning:**
  - Locking only the target row does not stop two admins demoting or deactivating each other: each sees the other as still admin. `update_user` takes a transaction advisory lock (`lock_admin_changes`) before it counts the remaining active admins, refuses with 409 `last_admin`, and re-checks that the actor is still an active admin after waiting for the lock. Requests that race through FastAPI usually fail earlier at auth (401/403) once the first commit lands, so the concurrency test calls the service with two sessions and stale `AuthContext`s.
  - A save queues an embedding only when the redacted `search_document` actually changed (jobs and candidates), so a status-only edit, an identical re-save or a phone-number edit costs nothing. The fix-1 regression test (unchanged text after a permanent dead letter makes no call) now queues the job directly, because an identical API save no longer queues anything.
  - Audit rows are written only when a field changed (a job status change counts; a no-op user update is a 200 with no row).
  - A database CHECK firing on job create or edit is mapped to a 422 `validation_error` and logs only the exception class (driver messages can echo values).
  - `embed-backfill` iterates `embeddings.TARGET_ORDER` (jobs, then candidates), the same order as the worker.
  - Creating an account and resetting a password run argon2, so they are limited per admin (`ADMIN_ACCOUNT_WRITE_LIMIT` per `ADMIN_ACCOUNT_WRITE_WINDOW_SECONDS`, default 20 per hour) with the in-memory sliding-window limiter.
- **Impact / action:** The in-memory limiter is per process; back it with a shared store before running several API instances.

### 2026-10-29: Phase 2c hardening decisions (design)
- **Context:** Designing fixes for the remaining `docs/flow.md` §13 gaps ([phases/phase-2c-hardening.md](../phases/phase-2c-hardening.md)). The user decided the limiter store, search auditing and the reaper policy.
- **Learning:**
  - **The `Exception` handler lives outside our middleware.** `app.add_exception_handler(Exception, ...)` is installed by Starlette in `ServerErrorMiddleware`, the outermost layer. Its 500 therefore skips `RequestContextMiddleware` and CORS (no `X-Request-ID`, no CORS headers, no `request_completed` log), and it re-raises after sending, which is why `ASGITransport` raises in tests.
    - The fix is a pure-ASGI catch-all added *first* (innermost). It answers with the standard body and does not re-raise.
    - After it lands, tests see a real 500 response. Only exceptions raised after `http.response.start` still raise out of `ASGITransport`.
  - **Leases need their own column.** `run_after > now()` cannot tell a worker's lease from transient backoff, because both push `run_after` out. Leases get a `leased_until` column, and an edit keeps a live lease while still bumping `generation`.
  - **Rate limiting moves to Postgres** (user decision): `rate_limit_hits` in `core`, with check and insert under `pg_advisory_xact_lock(namespace, hashtext(key))`.
    - Use `clock_timestamp()`, not `now()`: `now()` is the transaction start, which is stale after a lock wait.
    - "Count failures only" stays race-free by *reserving a slot before the password check* and deleting it on success (`failure_slot`).
    - Keys are `scope:` + an HMAC with `RATE_LIMIT_KEY_SECRET`, because a plain SHA-256 of an email can be reversed against a staff list.
    - The two-key advisory lock form uses a separate lock space from the single-bigint budget and admin locks.
  - **Periodic maintenance is not the embedding worker's job.** That worker doesn't start without an OpenAI key, and hosting the tasks there would couple embeddings to auth and ai_usage.
    - A generic runner goes in `core/maintenance.py`, with the task list composed in `app/maintenance.py` from each feature's public API.
    - It has its own flag, `MAINTENANCE_IN_API`, and a `app.cli maintenance [--once]` command.
  - **The spend estimate becomes an upper bound.** With byte-level BPE a token is at least one UTF-8 byte, and `text-embedding-3-*` rejects any input over 8,192 tokens unbilled. So `estimate_tokens_upper_bound` = bytes + 1 per input, capped at 8,192, is a hard upper bound.
    - Reservations grow about 4× over `chars/4`: about $0.001 instead of $0.00026 per 64-candidate batch, against about $0.00023 actually billed.
    - `has_embedding_budget`'s minimum becomes 8,192 tokens ($0.000164).
  - **A late settle for a reaped reservation** must log and return. Raising `NotFoundError` after a successful provider call would crash the batch and throw away vectors that were already billed.
- **Impact / action:**
  - Phase 2c is built before 4a.
  - 4a reuses `search_candidates(session, params, actor)` (which writes the `candidate.search` audit row), `estimate_tokens_upper_bound`, and migration `rate_limit_hits` as its `down_revision`.
  - The 2c tests use `TEST_DATABASE_URL` pointing at `candidate_search_test_ca`.

### 2026-10-30: Installing Claude Code plugins and skills without git
- **Context:** Installing the `ponytail` plugin and the `grill-me` skill.
- **Learning:** `/plugin` is unavailable in the VS Code extension, and both a GitHub marketplace source and `npx skills add` shell out to `git` (fails with `spawn git ENOENT`). `grill-me` is only a stub that calls the `grilling` skill.
- **Impact / action:** Download the repo's `archive/refs/heads/main.zip` instead. The ponytail marketplace lives in `~/.claude/local-marketplaces/ponytail`, registered in `~/.claude/settings.json` as a `directory` source; `grill-me` and `grilling` were copied into `.claude/skills/`. Updating either means re-downloading.

### 2026-10-30: Search by meaning ships ahead of the full 4a hybrid
- **Context:** The user asked for the Candidates search box to do vector search directly ("query → embedding → search"), before 2c and the full Phase 4a hybrid were ready.
- **Learning:**
  - `GET /api/v1/semantic-search/candidates?q=&limit=` (feature `semantic_search`) embeds the query through `ai_usage.metered_call` (operation `search_query`, trigger `api`) and returns the HNSW nearest candidates with cosine similarity. It has its own prefix because `/admin/candidates/semantic` would be captured by the `/admin/candidates/{candidate_id}` route and give a UUID 422.
  - Embedding is semantic only: names and emails are redacted out of `search_document`, so a name typed in "by meaning" mode can't find that person. The UI therefore has a "By meaning" (default) / "Exact words" toggle in the URL (`mode=keyword`), and its errors offer "Search by exact words instead". The e2e specs that look up a literal token switch to "Exact words" first.
  - Queries that look like identifiers (`@`, `://`, `www.`, or one run of 6+ digits with phone-style separators) are refused with 422 before any call. A plain digit count was wrong: "10 years in 2024" has 6 digits.
  - The query text is never logged or audited; `candidate.search` rows get `{"mode": "semantic", "filters": ["q"], "limit", "result_count"}`. An in-process LRU (256 entries, keyed by model + case-folded query) means repeated searches aren't billed again. Interactive calls are cut at 10 s with `asyncio.wait_for`; `metered_call` settles the cancelled reservation.
  - ~~superseded~~ (2026-10-30: merged back into `candidates/service.py`) `candidates/summaries.py` holds `get_candidate_summaries`, kept out of `service.py` because another session was editing that file; it reuses `service._to_summary`.
  - `e2eEnvironment()` sets `OPENAI_API_KEY=sk-CHANGE_ME`, so e2e searches by meaning answer 503 instead of calling OpenAI with the real key from `backend/.env`.
- **Impact / action:** Phase 4a's hybrid ranking (keyword + vector fusion, filters on both halves) can replace the toggle later and should reuse `nearest_candidates_to_vector` and the identifier check.

### 2026-10-30: Phase 2c build notes
- **Context:** Building the hardening phase (items 2-6; items 1, 7 and 8 were done by the stopped run, the session-prune and optional-session pieces by the Phase 3 session).
- **Learning:**
  - `RATE_LIMIT_KEY_SECRET` is now validated for staging/production, so *any* subprocess test that sets `ENVIRONMENT=production` must also pass a 32+ character secret, or it stops at settings validation before reaching what it tests (`test_seed_script.py` needed this).
  - `test_the_tests_run_with_the_dummy_key_and_the_test_database_never_the_env_file` asserts the test DB name ends in `_test`, so it always fails on a side database such as `candidate_search_test_ca`. That is expected there; it passes on the shared `candidate_search_test`.
  - CLI and script tests start subprocesses that import `app.main`. Another session saving a half-written module mid-run makes them fail together with unrelated-looking errors; re-run them alone before debugging.
  - `failure_slot` must roll back the shared session before releasing: the body's service call may have left it mid-transaction after an error. Releasing is wrapped so a failed release keeps the hit (fail closed) and the original outcome stands.
  - `RateLimitHit` lives in `core`, so `register_all_models()` and `migrations/env.py` import `app.core.rate_limit` explicitly; `alembic check` reports no drift with it.
  - Three Phase 2b edge-case tests encoded the old contract and were updated, not weakened: a second settle is now a logged no-op instead of `NotFoundError`, and the minimum budget headroom is $0.000164 (8,192-token bound) instead of $0.00012.
- **Impact / action:** e2e has not been run for 2c (the shared test DB was busy); run it before marking 2c done.

### 2026-10-30: Pure vector similarity can't check facts in a query
- **Context:** The user searched "fastapi developer in ghaziabad with 5 years of experince". The only profile that fit scored 57% and the others 50-51%.
- **Learning:**
  - `search_document` leaves out city and country, so the embedding knows nothing about location.
  - Numbers barely move a vector.
  - Cosine scores from `text-embedding-3-small` sit in a narrow band (about 0.3-0.6), so a percentage made from them says little.
- **Impact / action:**
  - Search by meaning now takes the 20 nearest profiles (the user's choice; this is below pgvector's default `ef_search` of 40). It re-ranks them on the query's terms, checked against `search_document` plus city and country, and reads "N years" as a minimum. The score is `(met + closeness) / (requirements + 1)`, so meeting more requirements always wins and meaning only breaks ties. The API returns `matched` and `missing`.
  - The UI sends a search by meaning only when you click Search or press Enter, so typing makes no paid calls. Exact words stays live while you type.
### 2026-10-30: Audit fixes: whole-word term match, account login limit, Exact words default
- **Context:** Fixing the findings of a whole-repo audit.
- **Learning:**
  - Search by meaning matched query terms by prefix, so "java" matched "javascript" and "go" matched "google". The match now ends at a word edge, allowing a plural "s" (`(?![a-z0-9+#])`). Trade-off: "postgres" no longer matches "postgresql", and "python" no longer matches "python3".
  - Login was limited only per (email, IP), so guessing one account from many IPs had no cap. A second `failure_slot` keyed by the email alone (`login_account_failure_limit`, 20 per 15 min) caps it. Someone who knows a staff email can lock that login for 15 minutes; that is the accepted cost. Each failed login now writes two `rate_limit_hits` rows.
  - `ENVIRONMENT` has no default any more: a deploy that forgets it fails at startup instead of running with non-Secure cookies, public `/docs` and the published dev HMAC secret.
  - The Candidates search box defaults to "Exact words" (`mode=meaning` in the URL selects search by meaning). Switching to "By meaning" removes `q` from the URL, so the text already typed is sent to OpenAI only when Search is pressed. Before this, typing a name in the default mode, or switching modes, sent the name to OpenAI.
  - `core/logging.StripQueryStringFilter` cuts query strings from `uvicorn.access` lines. uvicorn calls `access_logger.info('%s - "%s %s HTTP/%s" %d', client, method, path_with_query, version, status)`, and the filter rewrites argument 3. It is added after uvicorn's own `dictConfig`, because uvicorn imports the app after configuring logging.
  - New tests: `core/tests/test_maintenance.py` (runner), `tests/integration/test_maintenance_tasks.py` (reaper, session prune), `core/tests/test_logging.py`. `get_candidate_summaries` (unused) and the three `@fontsource` packages were removed.
- **Impact / action:** e2e specs already pick "Exact words" explicitly, so they are unaffected. Any link that should open search by meaning must carry `mode=meaning`.

### 2026-10-30: Search by meaning = hybrid fetch + gpt-5.4-mini ranking; OpenAI only
- **Context:** The user asked, in a `/grill-me` session, for search by meaning to fetch by hybrid search and rank with an LLM: skills and location first (location only for hybrid or office), then experience. The decisions are recorded in the Phase 4a revision note.
- **Learning:**
  - **Rules.** The user changed the rules to OpenAI only: no Anthropic SDK. `core/llm.py` is the shared chat client. It uses structured outputs via `chat.completions.parse(response_format=<Pydantic model>)`, one attempt with a 20 s timeout, and its own key check (blank or `sk-CHANGE_ME` → `LLMConfigurationError`).
  - **Model.** `gpt-5-mini` is deprecated on OpenAI's model page. `gpt-5.4-mini` costs $0.75 / $4.50 per million input / output tokens, about $0.01 per 20-candidate ranking. GPT-5.4 models accept `reasoning_effort` none/low/medium/high/xhigh, *not* `minimal`, which only the older GPT-5 models take.
  - **Ordering.** The LLM only judges each criterion; code decides the order. That keeps the order reproducible, and the work-mode rule ("office fits hybrid and remote; hybrid fits remote") is plain logic that shouldn't be trusted to a model. Code also ignores a "willing to relocate" verdict unless `open_to_relocation` is true.
  - **Full text.** `search_tsv` indexes `search_document || ' ' || city`, deviating from the 4a design (document only), because the redacted document leaves location out. Words are OR-ed by rewriting `plainto_tsquery(...)::text` from `&` to `|`.
  - **Tests.** The chat endpoint is mocked with an `httpx2.MockTransport` handler that reads the candidates JSON out of the prompt and answers per profile, so the real SDK parsing runs. Tests install it with `use_llm_client`; without that, the network guard fails the test.
- **Impact / action:**
  - ~~superseded~~ (2026-10-30 audit cleanup: hybrid-search order, `ranked_by: "search"`) When the LLM can't run (no key, budget used up after the query embedding, provider error), results still come back in word-check order with `ranked_by: "keywords"`. Only a failed *query embedding* is an error (402 / 503).
  - Migration `a7c3e9d51b28` sits on the other session's `0c5e9a2d7b14` (drop embedding queues).
### 2026-10-30: Simplification 2: no embedding queue, no spend reservations, one background runner
- **Context:** The user found the backend hard to follow; a whole-backend audit showed one flow (save, then embed) made about 20 hops across 9 files, with four overlapping safety nets and an exact-to-the-micro-dollar spend cap. The user asked to fix all of it.
- **Learning:**
  - **No queue.** `embedding_jobs` and `job_embedding_queue` are dropped (migration `0c5e9a2d7b14`). `embeddings.embed_stale` runs `find_stale_ids` (no vector, or `sha256(search_document)` differs from the stored hash), embeds up to 64, and stores them. A save therefore needs no enqueue call at all. For ~1,000 rows the scan takes a few ms; it is marked `shortcut:` to bring a queue (or an indexed hash column) back around 100k rows.
  - **Retries live in the dead-letter row.** A temporary failure is retried after 30 s, 2 min, 8 min and 32 min (`RETRY_BASE_SECONDS * 4^(attempts-1)`, 5 tries) by a SQL condition on `embedding_failures.updated_at`/`attempts`. Permanent errors and `model_price_unknown` are never retried for the same text; `budget_exceeded` rows are retried once the budget has room.
  - **Spend: check, call, record.** `metered_call` refuses when `spent >= limit` (or the model has no price) and records one `blocked` row; otherwise it runs the call and inserts one `succeeded` or `failed` row. Reservations, `pending`, the reaper, both `asyncio.shield`s, the upper-bound estimate, the headroom minimum and the blocked-row dedupe are gone. Accepted trade-offs (a `shortcut:` comment in the code): concurrent callers can overshoot by one call each (about $0.01 for a 64-input batch), and a call cancelled mid-flight is not recorded. `tokens_of` now returns `(input, output)` so chat calls price their output tokens.
  - **A negative `billed_tokens` must be treated as 0**, or the failed row becomes a credit that frees budget (found while rewriting the tests).
  - **One runner.** The embedding worker (`worker.py`, `background.py`, its own backoff and Ctrl+C handling) is replaced by the `embeddings.embed_stale` task (every `EMBEDDING_POLL_SECONDS`, default 2) in the maintenance runner. A failing task is retried after a flat 60 s (not min(interval, 60), or a 2 s task would log every 2 s during a database outage); the runner logs a task only when it did something; shutdown grace is 45 s. `EMBEDDING_WORKER_IN_API` is gone; `MAINTENANCE_IN_API` turns the whole runner off.
  - **CLI:** `embed-worker`, `embed-backfill --sync` (queue mode) and `similar-candidates` are removed; `embed-backfill` now embeds everything stale and exits. The similarity query no longer joins `headline`, so embeddings reads only `id` and `search_document` from candidates/jobs.
  - **The job page still says "Waiting for AI budget":** with the scan skipped while the budget is used up, nothing records a budget failure, so `get_job_embedding_status` asks `ai_usage.budget_used_up` (runs in the caller's transaction) instead.
  - The budget summary drops `pending_usd` and `last_event_blocked` and adds `limit_reached` (spent >= limit); the frontend budget card follows.
- **Impact / action:** About 1,100 lines of app code and a third of the embedding/spend tests went away (whole files for queue leases, worker signals, reservation guarantees). Phase 2/2b/2c docs describe the old design; `docs/flow.md` sections 1, 5-12 and the README describe the current one. Migration `0c5e9a2d7b14` also turns any leftover `reserved` events into `failed`/`abandoned` (cost kept as spent).
### 2026-10-30: Audit cleanup: one key check, one cursor helper, refused answers priced right
- **Context:** Fixing the findings of a ponytail audit (job embeddings kept, Phase 4 uses them).
- **Learning:**
  - A refused chat answer is billed by OpenAI for input *and* output tokens. `LLMError` used to carry their sum as `billed_tokens`, which `metered_call` priced entirely at the input rate (output costs 6x more). It now carries `billed_tokens` (input) and `billed_output_tokens` separately; a regression test checks a refused answer costs $0.002250 for 1,200 + 300 tokens.
  - The OpenAI key check and base URL live once in `core/config.py` (`Settings.usable_openai_api_key()`, `OPENAI_BASE_URL`); `describe_error` lives once in `core/errors.py` (the dead-letter permanence check still depends on its format); `EmbeddingBatch.billed_tokens` is the one `tokens_of` for embeddings.
  - Newest-first lists (users, jobs, AI events) page through `core.pagination.decode_created_at_cursor` / `next_created_at_cursor`; the candidate search keeps its own sort-aware cursor.
  - The cost of an AI call is logged once, exactly, by `metered_call` (`ai_call_recorded`). `estimate_cost_usd`, the provider's `embedding_batch_completed` line and `EmbedOutcome.total_tokens`/`cost_usd` are gone.
  - `embed_stale` embeds one batch per call (the scan never returns more), so its `limit` argument and batch loop were removed. A budget refusal during the one-by-one retry still stops asking for the rest.
  - The query-vector cache was removed (a query embedding costs about $0.000001); the 10-minute ranking cache stays. To test "budget runs out between the query embedding and the ranking", leave exactly $0.000001 of room ($0.01 limit, $0.009999 spent).
- **Impact / action:** `ranked_by` is now `"ai" | "search"`, and `fit` is null when the AI ranking was unavailable.

### 2026-10-30: One search box; hard filters split the ranked list instead of narrowing the fetch
- **Context:** The user removed the "Exact words" / "By meaning" toggle and asked for hard filters (min years, skills, city, country, source) applied *after* the hybrid fetch and LLM ranking, with filtered-out candidates still shown.
- **Learning:**
  - Filtering after a 20-profile fetch means a selective filter (a rare city) can leave few or no perfect matches even when matching people exist further down. That is the requested trade-off: the "Filtered out" list shows what the filter removed, and browsing with no search text (the list endpoint, filtered in SQL) finds everyone who passes.
  - Names and emails can no longer be looked up from the search page: search text goes to OpenAI and the embedded document is redacted. Open a profile from the list or filter by city instead. The e2e specs find their seeded candidate by a unique city for the same reason (e2e has no OpenAI key, so a search answers 503).
  - Filters are not part of the LLM prompt or the ranking-cache key, so changing filters after a search costs one query embedding (~$0.000001) and no new ranking.
  - The `skill` filter used to be compared raw (`skills @> ['FastAPI']` missed the stored `fastapi`); `shared.validation.split_tags` now normalises it on both endpoints.
  - The design-QA keyboard test (`focus ring is visible`) was already failing before this change: the first Tab after the skip link lands on the blue "Add candidate" button, whose ring is near-white, not `rgb(37, 99, 235)`.
- **Impact / action:** Name lookup on the staff page needs a separate decision if staff miss it.

### 2026-10-30: The LLM's location verdict can contradict itself across candidates
- **Context:** "python developer in noida" ranked a Berlin profile above a Ghaziabad one.
- **Learning:** The LLM answered `not_required` ("remote role") for the Berlin candidate, who works remotely, while judging others as `commutable`. It mixed up the candidate's work preference with what the search asks for. Both then counted as location met, and the higher skills score won.
- **Impact / action:** `rank_by_judgements` treats the search as naming a place when any judgement gives a place verdict. A `not_required` in that answer then counts as location missed. Covered by `test_location_not_required_is_ignored_when_the_search_names_a_place`.

### 2026-10-30: Job matching and salaries
- **Context:** The user asked for jobs to be matched to candidates, and for candidates' expected pay and jobs' pay ranges. The user's decisions:
  - salary is yearly plus a currency;
  - the AI judges it (so it is sent to OpenAI);
  - matching runs from a "Find candidates" button;
  - the job's own requirements are the hard filters.
- **Learning:**
  - **Work-mode bug.** Profiles and jobs store `onsite`, but the ranking's work-mode table only knew `office`. A candidate who wanted onsite work therefore never fit an office search. Fixed by mapping both, and the test fixtures now use `onsite`.
  - **Stored job vector.** Read the job's vector as `embedding::text` and parse it with `json.loads`: pgvector's text form is valid JSON, and our `Vector` type has no result processor. The read only returns the vector while its `content_hash` equals the hash of the job's current document, so an edited job never matches with its old vector.
  - **Salary verdicts.** They get the same guards as location. Any non-`not_required` verdict means the search states pay. A `within` or `above` for a candidate who states no salary becomes `unknown`.
  - **Matching cost.** It makes no embedding call (it uses the stored vector) and one LLM call of about $0.01. The frontend keys results by job version and remounts per version, so editing a job never starts a paid run by itself. The job page polls every 3 s while the embedding is `pending`.
  - **Frontend schema limit.** zod can't `.extend()` a refined object, so the candidate form leaves the "salary and currency together" rule to the API. The job form, which isn't extended, checks it client-side too.
  - **Privacy.** The draft privacy notice text now mentions salary and OpenAI, but `PRIVACY_NOTICE_VERSION` was not bumped (the notice is still a draft).
- **Impact / action:**
  - Migration `c4d8e2f6a913` (additive, nullable) is applied to the dev DB.
  - A city filter on a hybrid or onsite job is strict: a candidate in a commutable city goes to "Filtered out" even when the AI rates the location as met.

### 2026-10-30: Breaking the matching, and the fixes
- **Context:** An adversarial pass over job matching and the hard filters found 13 problems; all are fixed with tests.
- **Learning:**
  - **One verdict decided for everyone.** Inferring "the search names a place / states pay" from any single verdict let one wrong AI answer mark down all 20 candidates. Prompt `rank_v3` asks it once, as `search_names_place` and `search_states_pay` on `RankingAnswer`, and only those fields count.
  - **Filtering after a top-20 fetch hid real matches.** The hybrid fetch now runs twice when filters are set:
    - the best 20 among candidates who pass (as `candidates.candidate_ids_passing` subquery, `hnsw.iterative_scan = relaxed_order`);
    - the best 10 of everyone else for "Filtered out".
    One LLM call ranks up to 30 profiles (about $0.02; `MAX_OUTPUT_TOKENS` raised to 10,000). Filter changes now change the pool, so they can trigger a new ranking.
  - **Spellings.** `shared/aliases.py` maps common skill and city spellings (postgres/postgresql, k8s/kubernetes, Bangalore/Bengaluru, Gurgaon/Gurugram, ...). The SQL filter (`hard_filter_clauses`, also used by the list endpoint) and the Python check (`failed_filters`) both use it, so they agree. A nearby commutable city is still not the same city.
  - **The job filter could 500.** A job's must-have skills joined as the `skill` filter can reach about 1,040 characters, over the old 300 limit; `HardFilters.skill` now allows 1,100.
  - **Currencies.** The backend accepts only the 8 currencies the forms offer. Accepting all of ISO 4217 stored values the edit forms couldn't save.
  - **Validation.**
    - Salary currency validators skip the pair rule when the amount itself failed, so one mistake gives one error.
    - `JobPatch` salary fields are strict like `JobFields`.
    - Tags may not contain commas, because filters are comma-separated.
  - **Smaller fixes.**
    - An empty pool makes no LLM call.
    - The job page stops polling after 40 tries (about 2 minutes).
    - Match results are keyed on the job's matching fields, not its version, so closing a job keeps them.
    - Expected pay is on `CandidateSummary` and in the results table.
    - Salary now sorts after the skills score: skills + location, then skills score, then pay, then experience.
- **Impact / action:** None of these needed a migration.

### 2026-10-30: Search and job matching stream their steps (SSE)
- **Context:** The user asked for a loader that shows the steps (embedding → retrieval → augmentation → result) while a search or job match runs.
- **Learning:**
  - **Endpoints and events.** The `.../stream` twins of both endpoints answer `text/event-stream`:
    - one `stage` event per step (`embedding`, `retrieval`, `augmentation`, `ranking`, `filtering`), each `started` then `done`, with a detail and `elapsed_ms`;
    - then a `result` (the same JSON as before) or an `error` (`status`, `code`, `message`).
    The JSON endpoints stay, and the service code is shared. A `Progress` object is a no-op without a listener.
  - **Errors.** Errors raised after the response has started can't change the status code, so they travel as `error` events. Validation and auth fail before streaming and still return the usual JSON error.
  - **Task and session.** The search runs in its own task with its own session, not `SessionDep`, so it doesn't depend on when FastAPI closes `yield` dependencies for streaming responses. A browser that disconnects does **not** cancel the task: cancelling a metered call mid-flight would leave the spend unrecorded. `_running` holds strong references until it finishes.
  - **Frontend.** It reads the stream with `fetch` + `TextDecoderStream` rather than `EventSource`, so the request carries `X-Requested-With`, the session cookie and an abort signal like every other call (`shared/api/stream.ts`). `stubApi` accepts `stream: sseBody(...)` for tests.
  - **Testing.** httpx's `ASGITransport` buffers the whole streamed body, so the integration tests check event order and content, not timing. A manual probe against a real uvicorn server (test DB) confirmed each event arrives as its own chunk, with `X-Request-ID`. Responses send `Cache-Control: no-cache` and `X-Accel-Buffering: no` so a reverse proxy doesn't batch them.
- **Impact / action:** A new step needs a value in `Stage` (backend `schemas.py`) and `STAGES` (frontend `types.ts`), plus a label in `SearchProgress`.

### 2026-10-30: phases/ removed; docs/guide/ is the reference
- **Context:** Every planned phase was built, and the user found the phase docs no longer useful.
- **Learning:**
  - The `phases/` folder is deleted. Earlier entries that link to phase docs (`phases/README.md`, `phase-2-embeddings-pgvector.md`, `phase-2c-hardening.md`) now point at nothing; their decisions are recorded in this file.
  - `docs/guide/` replaces them as the explanation of the current system. It is written for a junior developer: flows, architecture, coding style, decisions, and every backend function.
  - `docs/flow.md` predates search by meaning, job matching and SSE. It is marked outdated; `docs/guide/03-flows.md` is the maintained version.
- **Impact / action:** CLAUDE.md no longer requires an `Approved` phase doc before building. The team workflow (architect → developer → tester) still applies. When behaviour changes, update the matching `docs/guide/` page in the same change.

### 2026-10-30: Search by meaning refused salaries as phone numbers
- **Context:** Audit of search by meaning after salaries were added.
- **Learning:** `looks_personal` refused any run of 6+ digits, so "budget 2500000 INR" got a 422 ("phone numbers can't be searched"), while redaction treats a phone as 10+ digits. It now calls `shared.redaction.contains_phone_number`, the same rule redaction uses.
- **Impact / action:** A 6-9 digit ID ("ID 123456") is no longer refused; that is the accepted trade-off. A salary range written without spaces ("1500000-2500000") still reads as one 14-digit phone number and is refused; "15-25 LPA" or "1500000 to 2500000" work.

### 2026-10-30: Audit fixes: filter snapshot, CSRF on paid GETs, audit of work history, lookup_text removed
- **Context:** Fixing findings 2-6 of a whole-repo audit.
- **Learning:**
  - Filters typed after a search re-ran the paid search on each 300 ms pause. The search now uses a snapshot taken when Search is pressed (or the page opens from a link). Browsing with no search text is free, so it stays debounced and live.
  - `SameSite=Lax` sends the cookie on a top-level cross-site GET, so a link could start a paid search. `require_fetch_header_on_any_method` guards the whole `semantic_search` router. It runs before the login check, so a request without the header gets 403 rather than 401; tests of the 401 must send the header.
  - `_apply_profile` left experiences and educations out of `changed_fields`, so an edit to them was audited as nothing changed. They are now compared, and replaced only when they differ, so an unrelated edit no longer rewrites every child row.
  - The list endpoint lost `q`, `work_mode`, `max_years` and `sort`, and `candidates.lookup_text` and its trigram index are dropped (migration `d2b7e4a1c9f6`, applied to the dev DB; its downgrade rebuilds the column). This settles the open question in "One search box": staff have no name or email lookup. The `pg_trgm` extension stays installed, now unused.
  - The list now uses the shared `decode_created_at_cursor` / `next_created_at_cursor`. Their 2000-3000 year check fixed the two strict xfails for extreme timestamps; the three name and experience cursor xfails went with those sorts. A cursor timestamp with a trailing NUL still gives 200, which is harmless (see "Phase 3 build gotchas").
- **Impact / action:** A new paid GET route belongs on the `semantic_search` router, or needs the same dependency. `test_sql_and_python_filters_agree_on_spellings` guards the two filter implementations.
