# 4. Backend core and shared: every function

`core/` is infrastructure with no business knowledge. `shared/` holds small helpers that two or more features use. Neither imports from `features/`.

Paths are relative to `backend/app/`.

---

## `main.py`

| Function | What it does | Why |
|---|---|---|
| `lifespan(app)` | Runs at startup and shutdown. Startup: starts the background runner. Shutdown: stops the runner (waits for its current task), closes the OpenAI client, then closes the DB pool. | Order matters: the runner still needs the database while it finishes. |
| `create_app()` | Reads settings, sets up logging, builds the FastAPI app, adds middleware and error handlers, registers routers under `/api/v1`. | Only wiring; no business logic lives here. |

`/docs` and `/openapi.json` are switched off in production.

## `maintenance.py`

| Function | What it does |
|---|---|
| `maintenance_tasks()` | Returns the list of background tasks: prune rate-limit rows (10 min), prune sessions (1 h), and, only if an OpenAI key is set, `embed_all_stale` every `EMBEDDING_POLL_SECONDS` (2 s). Without a key it logs `embedding_disabled` and leaves embedding out, so the API still starts. |

## `cli.py`

| Function | What it does |
|---|---|
| `_read_password(from_stdin)` | Reads the password with `getpass` (asked twice), or one line from stdin. Strips a UTF-8 BOM and `\r\n`, which Windows PowerShell adds and which would silently become part of the password. |
| `_create_user(...)` | Calls `auth.create_user`. Prints a clean error and exits 1 on a known error. |
| `_embed_backfill()` | For each target (jobs, then candidates) calls `embed_stale` in a loop until nothing is left or the budget refuses. Logs totals. |
| `_maintenance(once)` | Runs `run_maintenance` with the task list. |
| `_run_maintenance_command`, `_run_embed_backfill` | Wrap the async functions with `asyncio.run` and map errors to exit codes. |
| `main()` | Parses arguments, sets up logging, calls `register_all_models()` (see `core/db.py`), dispatches. |

---

## `core/config.py`: settings

The **only** place environment variables are read. Everything else calls `get_settings()`.

| Name | What it does |
|---|---|
| `Settings` | A pydantic-settings class. Each field maps to an env var with the same name in capitals (`database_url` ↔ `DATABASE_URL`). It also reads `backend/.env`. |
| `Settings._require_real_secrets_outside_development` | In staging and production, refuses to start unless `RATE_LIMIT_KEY_SECRET` is a real 32+ character secret. |
| `Settings.usable_openai_api_key()` | Returns the key, or `None` if it is missing, blank, or the `sk-CHANGE_ME` placeholder. A blank `OPENAI_API_KEY=` line loads as an empty string, not `None`; without this check every call would fail with 401. |
| `Settings.is_production`, `Settings.session_cookie_secure` | Small flags. Cookies are `Secure` only in staging and production, because local runs on plain http. |
| `get_settings()` | Builds `Settings` once and caches it (`lru_cache`). |
| `OPENAI_BASE_URL` | Passed explicitly to the SDK, so a stray `OPENAI_BASE_URL` env var can't redirect candidate text elsewhere. |

`environment` has **no default** on purpose: a deploy that forgets it fails at startup instead of running with development secrets.

## `core/db.py`: database

| Name | What it does |
|---|---|
| `Base` | The SQLAlchemy base class. Uses a naming convention so constraint names are predictable (Alembic diffs stay stable, and code can refer to `uq_candidates_email`). |
| `TimestampedModel` | Base for every table: `id` (UUID), `created_at`, `updated_at` (set by Postgres). |
| `register_all_models()` | Imports every `features/*/models.py`. A CLI command that only imports one feature would otherwise crash on the first insert with "NoReferencedTableError", because SQLAlchemy didn't know about the other tables yet. |
| `get_engine()` | Creates the async engine once (cached), with a connection pool and `pool_pre_ping`. |
| `get_sessionmaker()` | Creates the session factory once. `expire_on_commit=False` so objects stay readable after commit. |
| `get_session()` | FastAPI dependency: yields one session per request. It does **not** start a transaction. |
| `SessionDep` | Shorthand type: `session: SessionDep` in a route signature. |

## `core/errors.py`: error format

| Name | What it does |
|---|---|
| `AppError` | Base class for every expected error. Has `status_code`, `code`, `message`, `details`, `headers`. Features subclass it, for example `class CandidateAlreadyExistsError(ConflictError): code = "candidate_exists"`. |
| `NotFoundError` (404), `NotAuthenticatedError` (401), `ForbiddenError` (403), `ConflictError` (409), `RateLimitedError` (429) | Ready-made subclasses. |
| `describe_error(exc)` | Returns "ClassName status=N", never the message. Safe to store, because messages can contain user input. The embedding dead-letter logic depends on this exact format. |
| `_error_response(...)` | Builds `{"error": {"code", "message", "details"}}`. |
| `_handle_app_error`, `_handle_validation_error`, `_handle_http_error` | Turn exceptions into that body. The validation handler keeps only `loc`, `msg`, `type`, so the submitted input is never echoed back. |
| `UnhandledErrorMiddleware` | Catches any unexpected exception and answers a clean 500. It sits *inside* CORS and request-context middleware, so even a 500 has CORS headers and an `X-Request-ID`. |
| `register_exception_handlers(app)` | Registers the three handlers. |

## `core/middleware.py`

| Name | What it does |
|---|---|
| `RequestContextMiddleware` | Takes `X-Request-ID` from the request (or makes one), binds it to every log line of this request, adds it to the response, and logs `request_completed` with method, **path only** (no query string, which may hold a name), status and duration. |

## `core/body_limit.py`

| Name | What it does |
|---|---|
| `BodySizeLimitMiddleware` | Rejects bodies over 64 KiB with 413. Checks `Content-Length` first; for chunked uploads it counts bytes as they arrive. It must be middleware: a FastAPI dependency only runs after the whole body is already read into memory. |

## `core/logging.py`

| Name | What it does |
|---|---|
| `configure_logging(settings)` | Sets up structlog: readable console output locally, JSON elsewhere. Quiets the `openai`/`httpx` loggers (their debug logs contain request bodies). |
| `StripQueryStringFilter` | Cuts `?q=...` off uvicorn's own access log lines, which would otherwise print search text. |

## `core/pagination.py`: cursors

| Name | What it does |
|---|---|
| `encode_cursor(payload)` | A dict → compact JSON → base64url string. |
| `decode_cursor(cursor)` | The reverse. Any garbage → `InvalidCursorError` (400), never a 500. |
| `parse_cursor_position(created_at, row_id)` | Turns the decoded strings into a timezone-aware `datetime` (year 2000-3000) and a `UUID`. Values from a cursor skip Pydantic, so they need their own checks before reaching Postgres. |
| `decode_created_at_cursor(cursor)` | For newest-first lists: returns `(created_at, id)` or `None` for page one. |
| `next_created_at_cursor(rows, limit)` | Repositories fetch `limit + 1` rows. This splits them into the page and a cursor for the next page (only if the extra row existed). |

## `core/rate_limit.py`: rate limiting in Postgres

Each counted attempt is a row in `rate_limit_hits`. Storing them in Postgres (not memory) means every API process shares the same counts.

| Name | What it does |
|---|---|
| `RateLimitHit` | The table: `key`, `created_at`, `expires_at`. |
| `rate_limit_key(scope, *identity)` | Builds `"<scope>:<HMAC-SHA256 of the identity>"`. Emails and IPs are never stored in clear. A plain hash could be reversed by hashing a list of staff emails; the HMAC secret prevents that. |
| `acquire_slot(session, key, limit, window_seconds, message)` | In one short transaction: take an advisory lock for this key (so concurrent callers queue up), count hits in the window, raise `RateLimitedError` with `Retry-After` if full, else insert a hit. Uses `clock_timestamp()` because `now()` is the transaction start and is stale after waiting for the lock. |
| `release_slot(session, hit_id)` | Deletes a hit (the attempt didn't count). |
| `_release_quietly(...)` | Releases, but if that fails, keeps the hit and logs a warning (fail closed: counting too much is safer than too little). |
| `failure_slot(...)` | An `async with` block: reserve a slot, run the body, **keep** the slot only if the body raised one of `counts_as_failure` (e.g. wrong password), otherwise release it. Used by login and change-password. |
| `prune_rate_limit_hits(session)` | Background task: deletes expired hits 1,000 at a time. |
| `client_ip(request)` | The caller's IP. Behind a proxy, run uvicorn with `--proxy-headers`. |
| `rate_limit(scope, limit, window_seconds)` | Builds a FastAPI dependency that counts **every** request per IP (used by the public candidate form). Limits are functions so they're read at request time (tests can change settings). |

## `core/maintenance.py`: the background runner

| Name | What it does |
|---|---|
| `MaintenanceTask` | `name`, `interval_seconds`, and `run(session) -> int` (how many rows it touched). |
| `_run_task(task)` | Opens a session, runs the task, logs only if it did something (the embed task runs every 2 s; logging every idle run would flood the log). |
| `run_maintenance(tasks, stop, once)` | The loop: run each task when due; a failing task is logged and retried after 60 s (never stops the others); sleep until the next is due or `stop` is set. With `once`, run each once and raise the first error. |
| `start_background_maintenance(tasks)` | Starts the loop as an asyncio task on the API's event loop, unless `MAINTENANCE_IN_API=false`. |
| `stop_background_maintenance(grace_seconds=45)` | Sets `stop`, waits up to 45 s for the in-flight task (an embedding call can take 30 s and must be recorded), then cancels. |

## `core/embeddings.py`: the OpenAI embedding client

| Name | What it does |
|---|---|
| `EmbeddingError` | Base for provider failures. |
| `TransientEmbeddingError` | Worth retrying later: rate limit (429), 5xx, timeout, network. |
| `PermanentEmbeddingError` | Retrying the same text can't help: bad input (400), bad key, malformed answer. `billed_tokens` is set when OpenAI answered 200 (and billed) but the answer was unusable. |
| `EmbeddingConfigurationError` | No usable API key. |
| `EmbeddingBatch` | The result: `vectors` and `total_tokens`. `billed_tokens()` returns `(input, output)` in the shape `metered_call` expects. |
| `truncate_text(text)` | Cuts input to 24,000 characters, below the model's 8,191-token limit for normal text. |
| `_map_sdk_error(exc)` | Turns an SDK error into transient or permanent. Drops the message (it can hold response text). |
| `OpenAIEmbeddingProvider.__init__` | Builds `AsyncOpenAI` with explicit key, base URL, timeout (30 s) and `max_retries` (3). The SDK retries 429/5xx itself, so we never add a second retry loop. |
| `OpenAIEmbeddingProvider.embed_documents(texts)` | Calls `embeddings.create`, maps errors, then `_parse`. |
| `OpenAIEmbeddingProvider._parse(response, expected)` | Sorts by index, checks the count, the dimensions (1536) and that every number is finite (Python's JSON accepts `NaN`, Postgres doesn't). Any problem → `PermanentEmbeddingError`. |
| `build_embedding_provider(settings)` | Builds a provider, or raises `EmbeddingConfigurationError` if there's no usable key. |
| `get_embedding_provider()` | Returns the one shared provider, building it on first use. |
| `use_embedding_provider(provider)` | Tests install a provider with a mocked HTTP transport here. |
| `close_embedding_provider()` | Closes the HTTP client and empties the slot. |

## `core/llm.py`: the OpenAI chat client

| Name | What it does |
|---|---|
| `LLMError` | Any chat failure. Carries `billed_tokens` and `billed_output_tokens` separately (output costs 6x more). |
| `LLMConfigurationError` | No usable key. |
| `LLMResult[T]` | `parsed` (your Pydantic model), `input_tokens`, `output_tokens`. |
| `OpenAIChatClient.parse(model, instructions, content, schema, max_output_tokens)` | Calls `chat.completions.parse(response_format=schema)`: OpenAI must answer in exactly that JSON shape and the SDK parses it into the model. One attempt, 20 s timeout, `reasoning_effort="low"`. A refusal (no parsed answer) raises `LLMError` with the billed tokens. |
| `get_llm_client()` / `use_llm_client(client)` | Shared instance, and the test hook. |

## `core/ai_pricing.py`

| Name | What it does |
|---|---|
| `ModelPrice` | USD per million input and output tokens. |
| `MODEL_PRICES` | The price list. Add a model here before using it, or every call to it is refused. |
| `get_model_price(model)` | Price or `UnknownModelPriceError`. |
| `compute_cost_usd(model, input_tokens, output_tokens)` | Exact `Decimal` math, rounded **up** to 6 decimals so spend is never undercounted. |

## `core/vector.py`

| Name | What it does |
|---|---|
| `Vector(dimensions)` | A SQLAlchemy column type for pgvector's `vector(n)`. Sends the list as text `"[0.1,0.2,...]"` wrapped in `CAST(CAST(:p AS TEXT) AS vector(n))`, because the `asyncpg` driver has no codec for `vector`. Saves adding the `pgvector` Python package. |

---

## `shared/validation.py`

Building blocks for Pydantic schemas. The frontend has matching zod helpers; change both together.

| Name | What it does |
|---|---|
| `custom_error(code, message)` | A Pydantic error with a clean, user-readable message (no "Value error, ..." prefix). |
| `BlankToNone` | Turns `""` or `"   "` into `None` before validation, for optional fields. |
| `normalize_tag(value)` | Collapses spaces and lower-cases: `" Fast  API "` → `"fast api"`. Skills are stored this way. |
| `split_tags(value)` | `"Python, FastAPI"` → `["python", "fastapi"]`. Used for the comma-separated skill filter. |
| `tag_list(min_items, max_items, max_length)` | Validator for tag lists: normalise, de-duplicate, reject commas inside a tag (filters are comma-separated), enforce counts. |
| `normalize_country(value)` | `" in "` → `"IN"`, rejects non ISO-3166 codes. |
| `text(min_length, max_length)` | Shorthand string constraint with whitespace stripping. |
| `reject_bool(value)` | Pydantic would accept `true` as `1` for an int field; this rejects it. |
| `StrictModel` | Base for request bodies: rejects unknown fields (`extra="forbid"`), strips whitespace, rejects the NUL character `\x00` in any field (Postgres can't store it; without this the insert fails with a 500). |
| `Country`, `Currency`, `YearlySalary` | Ready-made annotated types. Currencies are limited to the 8 the forms offer. Salary is a whole yearly amount from 1 to 1,000,000,000. |
| `normalize_currency(value)` | Upper-cases and checks the currency is one of the 8. |
| `salary_needs_currency(has_amount, currency)` | An amount and a currency must come together or not at all. |

## `shared/redaction.py`

| Name | What it does |
|---|---|
| `redact_identifiers(text, names)` | Removes emails, URLs, phone numbers (10+ digits, but not year ranges like "2015-2019") and every part of the given names, then collapses spaces. Used on **every** field that goes into a search document. Name removal is aggressive on purpose: a name that is also a word ("Will") is removed everywhere. Losing a word is cheaper than leaking who someone is. |
| `_name_variants(full_name)` | "Mary-Jane O'Neil" → the full name, "Mary-Jane", "Mary", "Jane", "O'Neil", "Neil"... longest first, so the whole name is removed before its parts. |
| `_redact_phones(text)` | Finds digit runs that look like phones and removes those with 10+ digits. |
| `contains_phone_number(text)` | Whether `_redact_phones` would remove something. Search by meaning uses it to refuse phone numbers, so both places share one rule. |

## `shared/aliases.py`

| Name | What it does |
|---|---|
| `skill_spellings(skill)` | All accepted spellings of a skill: `"postgres"` → `{"postgres", "postgresql", "psql"}`. Unknown skills return just themselves. |
| `city_spellings(city)` | Same for cities: `"bangalore"` → `{"bangalore", "bengaluru"}`. |

Both the SQL filter (`candidates.repository.hard_filter_clauses`) and the Python check (`semantic_search.service.failed_filters`) use these, so they always agree. The list is hand-kept (marked `shortcut:`); replace it with a real taxonomy when recruiters report misses.

Next: [05-backend-features.md](05-backend-features.md).
