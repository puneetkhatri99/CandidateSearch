# 3. Flows, step by step

Each flow shows the path through the code. Paths are relative to `backend/app/`. Function names are links you can search for.

1. [Sign in, and how every request knows who you are](#1-sign-in)
2. [A candidate fills in the public form](#2-public-candidate-form)
3. [Staff edit a candidate (and the version check)](#3-staff-edit-a-candidate)
4. [Embedding in the background](#4-embedding-in-the-background)
5. [Every paid AI call: `metered_call`](#5-every-paid-ai-call-metered_call)
6. [Search by meaning](#6-search-by-meaning)
7. [Match candidates to a job](#7-match-candidates-to-a-job)
8. [Streaming the steps to the browser (SSE)](#8-streaming-the-steps-to-the-browser-sse)
9. [Browsing the candidate list (no search text)](#9-browsing-the-candidate-list)
10. [Command-line tools](#10-command-line-tools)

---

## 1. Sign in

`POST /api/v1/auth/login` with `{email, password}`.

```
auth/router.py  login
  ├─ failure_slot("login_failure", email + IP)        max 5 failures / 15 min    → 429
  ├─ failure_slot("login_failure_account", email)     max 20 failures / 15 min   → 429
  └─ auth/service.py  authenticate                    one transaction
        ├─ repository.get_user_by_email
        ├─ unknown or inactive user → passwords.burn_verification_time → 401
        │     (spends the same time as a real check, so timing doesn't reveal which emails exist)
        ├─ passwords.verify_password (argon2, in a thread) → 401 if wrong
        ├─ passwords.needs_rehash → re-hash silently if argon2 settings changed
        ├─ token = secrets.token_urlsafe(32)
        ├─ repository.add_session(token_hash = sha256(token))     the raw token is never stored
        ├─ user.last_login_at = now
        └─ record_event("auth.login")
  └─ set_session_cookie   cookie "cs_session": httpOnly, SameSite=Lax, 8 hours, Secure outside local
```

**Why "failure slots"?** Only *failed* logins count. The slot is reserved *before* the password check and released if the login succeeds. Reserving first means 10 parallel wrong guesses can't all slip through before any is counted. See `failure_slot` in [04-backend-core.md](04-backend-core.md#corerate_limitpy).

### Every later request

Routes declare who may call them with a type in the signature:

```python
async def get_candidate(candidate_id: uuid.UUID, session: SessionDep, actor: CurrentUser): ...
```

`CurrentUser` runs this chain (`auth/dependencies.py`):

```
require_fetch_header          non-GET requests must send "X-Requested-With: fetch"   → 403 csrf_failed
                              (the paid semantic-search routes need it on GET too)
get_optional_session_context  read the cookie → service.resolve_session
                                 ├─ repository.get_live_session: session JOIN user, not expired, user active
                                 └─ less than half the 8 h left? extend it and re-send the cookie
get_session_context           no session → 401 not_authenticated
get_auth_context              user must change password → 403 password_change_required
```

| Type | Use for |
|---|---|
| `CurrentUser` | Almost every route. Any signed-in staff member. |
| `AdminUser` | Admin-only routes (`require_role("admin")`). |
| `SessionUser` | Only `/auth/me` and `/auth/change-password`: they must work while a password change is pending. |
| `OptionalSessionUser` | Only `/auth/logout`: it must work even for a dead session. |

The role and the "must change password" flag are read from the database on **every** request, so demoting someone takes effect immediately.

---

## 2. Public candidate form

`POST /api/v1/candidates` (no login).

```
candidates/router.py  submit_candidate
  ├─ rate_limit("candidate_submit")       5 per hour per IP                 → 429
  ├─ BodySizeLimitMiddleware               body over 64 KiB                  → 413
  ├─ Pydantic: CandidateCreate             lengths, email, E.164 phone, URLs, dates  → 422
  └─ service.create_candidate
        ├─ data.website is filled?  → it's the honeypot field bots fill in; return a fake id, save nothing
        ├─ _new_candidate → _apply_profile
        │     ├─ copy fields onto the Candidate model
        │     └─ search_document = build_search_document(profile)   ← redacted text for AI
        └─ transaction: repository.add_candidate
              duplicate email → UNIQUE constraint → 409 candidate_exists
```

Nothing is "queued" for embedding. The new candidate simply has no vector yet, so the background scan finds it within ~2 seconds (flow 4).

---

## 3. Staff edit a candidate

`PUT /api/v1/admin/candidates/{id}` with the full profile **plus the `version` the user loaded**.

```
service.update_candidate     one transaction
  ├─ repository.get_candidate(for_update=True)     SELECT ... FOR UPDATE (locks the row)
  ├─ candidate.version != data.version  → 409 version_conflict
  ├─ changed = _apply_profile(candidate, data)    rebuilds search_document
  ├─ session.flush()   SQLAlchemy runs UPDATE ... WHERE version = <old>, and bumps version
  └─ record_event("candidate.update", changed_fields=[names only, never values])
```

**Why the version?** Two recruiters open the same profile. Both edit. Without a version, the second save silently overwrites the first. With it, the second gets 409 and the UI says "changed by someone else, reload".

If the search document changed, its hash no longer matches the stored embedding, so the background scan re-embeds it. If only the phone number changed, the search document is identical (phones are redacted out of it), so nothing is re-embedded and nothing is paid.

---

## 4. Embedding in the background

There is no queue. The **hash** of the search document is the signal.

```
core/maintenance.py  run_maintenance      loop forever; each task runs when it is due
  └─ every 2 s: embeddings.embed_all_stale(provider)
        for target in (JOBS, CANDIDATES):           jobs first: a recruiter is waiting on a new job
          embed_stale(target)
            ├─ ai_usage.has_budget?  no → do nothing at all
            ├─ transaction:
            │    ids  = repository.find_stale_ids(limit 64)
            │    docs = repository.load_documents(ids)
            ├─ nothing stale → return
            └─ _embed_batch(64 documents)
                  ├─ ai_usage.metered_call(call = provider.embed_documents(texts))   (flow 5)
                  │     └─ OpenAI embeddings.create(model, input=[...], dimensions=1536)
                  ├─ success → transaction: upsert_embeddings + clear_failures
                  ├─ PermanentEmbeddingError and batch > 1 → retry each document alone
                  ├─ PermanentEmbeddingError and batch = 1 → record_failure (not retried for this text)
                  ├─ TransientEmbeddingError → record_failure (retried after a delay)
                  └─ budget refused / no model price → record_failure("budget_exceeded" / "model_price_unknown")
```

### What "stale" means (`find_stale_ids`)

A candidate (or job) is stale when:

- it has **no embedding** for the current model, or
- `sha256(search_document)` (computed in SQL) **differs** from the `content_hash` stored with its embedding,

**and** its dead-letter row (if any) allows a retry:

- no failure row, or
- the text changed since it failed, or
- it failed because of the budget (and the budget has room again, since the scan only runs then), or
- it was a temporary failure, fewer than 5 tries, and the wait has passed: 30 s, 2 min, 8 min, 32 min (`RETRY_BASE_SECONDS * 4^(attempts-1)`).

Permanent errors (OpenAI rejected the input) and unknown model prices are never retried for the same text. Editing the text gives it a fresh try.

### Why retry one-by-one on a permanent error?

64 documents go in one request. If one is bad (say, too long in Chinese characters), OpenAI rejects the whole request. Retrying each alone means only the bad one is dead-lettered, not its 63 neighbours.

### Edge cases that are fine on purpose

- **Edited during the call:** the stored hash is of the text that was sent, so the new text still looks stale and is embedded next round.
- **Two runners at once** (API + a separate `maintenance` process): both may embed the same document. Harmless; one wasted call.

---

## 5. Every paid AI call: `metered_call`

`ai_usage/service.py`. Every OpenAI call goes through it: embedding batches, the search query embedding, and the LLM ranking.

```
metered_call(provider, model, operation, trigger, item_count, call, tokens_of)
  ├─ transaction: _refusal
  │     ├─ _ensure_budget         (creates a $5.00 row if the table is empty)
  │     ├─ no price for the model → UnknownModelPriceError
  │     └─ spent >= limit         → BudgetExceededError
  │   refused → insert a "blocked" event, raise. The call never runs.
  ├─ result = await call()        ← no transaction open while OpenAI works
  ├─ success → insert a "succeeded" event with real tokens and cost
  └─ failure → insert a "failed" event (cost 0, unless OpenAI billed an unusable answer), re-raise
```

- `call` is a function, not a result, so `metered_call` can decide not to run it.
- `tokens_of` tells `metered_call` how to read `(input_tokens, output_tokens)` from the result.
- Prices live in `core/ai_pricing.py`. A model with no price is refused, so the cap can't be bypassed by a typo.

**Known, accepted limit** (marked `shortcut:` in the code): the check and the record are not atomic. Two calls starting at the same moment can both pass and overshoot the limit by one call (cents at most). After that, every call is refused.

---

## 6. Search by meaning

The Candidates page has one search box. Typing text and pressing Search calls:

`GET /api/v1/semantic-search/candidates/stream?q=...&min_years=&skill=&city=&country=&source=`

```
semantic_search/service.py  search_by_meaning
  ├─ looks_personal(q)?        contains @, ://, www., or a phone number (10+ digits) → 422
  │                            (the query goes to OpenAI; emails and phones must not)
  ├─ get_embedding_provider()  no API key → 503
  ├─ STAGE embedding:  _embed_query → metered_call(embed [q])          timeout (10 s) or error → 503, budget used up → 402
  ├─ _find_rank_and_filter
  │    ├─ STAGE retrieval:
  │    │    hybrid_ids(within):
  │    │       nearest  = embeddings.nearest_candidates_to_vector(vector, 20, within)   meaning
  │    │       keywords = candidates.full_text_candidate_ids(q, 20, within)             exact words
  │    │       fuse(nearest, keywords) → best 20                                        RRF merge
  │    │    with filters:   best 20 among people who pass + best 10 of everyone else
  │    │    without:        best 20 overall
  │    │    pool = candidates.get_rankable_candidates(ids)
  │    ├─ STAGE augmentation:  ranking.build_prompt(q, pool)      anonymised JSON, no names
  │    ├─ STAGE ranking:       _rank_with_llm
  │    │      ├─ same query + same profiles in the last 10 min? reuse the cached answer (free)
  │    │      ├─ metered_call(client.parse(... schema=RankingAnswer))     gpt-5.4-mini
  │    │      ├─ any failure (no key, budget, timeout) → None → keep the hybrid order, ranked_by="search"
  │    │      └─ ranking.rank_by_judgements(answer, pool, required_work_mode)
  │    └─ STAGE filtering:  failed_filters(candidate, filters) for each ranked match
  │           passes all → items (perfect matches)
  │           fails any  → filtered_out (with which filters failed)
  └─ record_event("candidate.search", filter NAMES and counts only, never the query)
```

### Why fetch two lists (meaning + keywords)?

- Vectors find "the right kind of person" (a "backend engineer" query finds Django developers), but they are weak on exact facts like a city name or "5 years".
- Full-text search catches exact words. Its index (`search_tsv`) also includes the **city**, which the redacted search document leaves out.
- Merging both (RRF) gives a better shortlist than either alone.

### How the LLM's answer becomes an order

The LLM only **judges**. Our code **orders** (`ranking.to_match` and `rank_by_judgements`). That makes the order reproducible and keeps simple rules out of the model's hands.

For each candidate the LLM returns: `skills_score` (0-100), a `location` verdict, `experience_score`, a `salary` verdict, and short notes. Once per search it also says `search_names_place` and `search_states_pay`.

The sort key, highest first:

1. **skills met** (score ≥ 60 → 1 point) **+ location points** (1 met, 0.5 partial, 0 missed)
2. skills score
3. salary points (only when the search or job states pay)
4. experience score

Code-level guards on the LLM's answers:

- **Work mode is plain logic** (`fits_work_mode`): someone who accepts office work fits office, hybrid and remote roles; hybrid fits hybrid and remote; remote fits remote only.
- If the search names a place, a `not_required` location verdict counts as missed (it once let a remote-working Berlin profile outrank a local one).
- "Willing to relocate" only counts if the profile actually says `open_to_relocation = true`.
- A salary verdict of `within`/`above` for a candidate with no stated salary becomes `unknown`.
- A candidate the LLM forgot to judge is kept at the bottom, not dropped.

### Why filter after ranking?

The recruiter asked to see strong candidates that a filter removed. So filters don't throw people away; they **split** the ranked list. But filtering only after a top-20 fetch could hide real matches, so when filters are set the fetch runs twice: once only among people who pass (`candidates.candidate_ids_passing` as a subquery), once among everyone. Up to 30 profiles go to the LLM in one call.

---

## 7. Match candidates to a job

The job page has a **Find candidates** button. It calls:

`GET /api/v1/semantic-search/jobs/{job_id}/candidates/stream`

```
service.match_job
  ├─ jobs.get_job_brief(job_id)                          404 if missing
  ├─ STAGE embedding: embeddings.load_job_vector         uses the job's STORED vector: no new AI call
  │      None (not embedded yet, or text changed since) → 409 job_not_ready_for_matching
  ├─ keywords = job title + must-have skills + city
  ├─ brief    = job.search_document + pay line ("Pay: 60000-90000 EUR per year.")
  ├─ filters  = job_filters(job)    min years, must-have skills, country; city only if not remote
  ├─ _find_rank_and_filter(...)     same pipeline as search (section 6)
  └─ record_event("job.match")
```

The button stays disabled until the job's embedding is ready. The job page polls `GET /jobs/{id}` every 3 s (up to 40 times) while `embedding_status` is `pending`.

---

## 8. Streaming the steps to the browser (SSE)

A search takes a few seconds. To show progress, the `/stream` endpoints answer `text/event-stream`:

```
event: stage
data: {"stage":"embedding","state":"started","detail":"Turning your search into an embedding"}

event: stage
data: {"stage":"embedding","state":"done","detail":"Search embedded","elapsed_ms":412}

... retrieval, augmentation, ranking, filtering ...

event: result
data: { ...the same JSON as the non-stream endpoint... }
```

How it works:

- The service functions take an optional `Progress` object (`semantic_search/progress.py`) and call `progress.start(...)` / `progress.done(...)`. Without a listener, those calls do nothing, which is why the plain JSON endpoints share the same code.
- `streaming.stream_search` runs the search in its **own asyncio task with its own DB session**. Each stage event is put on an `asyncio.Queue`; the response reads from the queue and yields text.
- Errors after the response has started can't change the HTTP status (already sent), so they are sent as an `event: error` with `status`, `code` and `message`. Validation and auth errors happen before streaming starts and still come back as normal JSON errors.
- If the browser disconnects, the task is **not** cancelled. Cancelling a paid call mid-flight would leave its cost unrecorded. `_running` keeps a reference so the task isn't garbage-collected.

The frontend side is `shared/api/stream.ts` (see [06-frontend.md](06-frontend.md)).

---

## 9. Browsing the candidate list

With an empty search box the page calls `GET /api/v1/admin/candidates?min_years=&skill=&city=&country=&source=&limit=25&cursor=...`, newest first. No AI is involved.

```
candidates/service.py  search_candidates
  ├─ decode_created_at_cursor(cursor)   invalid or tampered cursor → 400 invalid_cursor
  ├─ transaction:
  │    repository.search_candidates → hard_filter_clauses + keyset WHERE + ORDER BY ... LIMIT limit+1
  │    record_event("candidate.search")     filter names only
  └─ next_cursor = encode_cursor({sort, key, id} of the last row)   if there was an extra row
```

**Keyset pagination:** instead of `OFFSET 50`, the next page asks for rows *after* the last row seen: `WHERE (created_at, id) < (:last_created_at, :last_id)`. It stays fast on big tables and doesn't skip or repeat rows when new ones are added. The cursor is just that position as base64 JSON.

The hard filters here use the same SQL (`hard_filter_clauses`) as the search-by-meaning prefilter, so both screens agree on who passes.

---

## 10. Command-line tools

`python -m app.cli <command>` from `backend/` (file `cli.py`):

| Command | Does |
|---|---|
| `create-admin --email ... --name ... [--role recruiter] [--password-stdin]` | Creates a staff account. Asks for the password twice, or reads it from stdin (stripping a Windows BOM and `\r\n`). |
| `embed-backfill` | Embeds everything stale (jobs, then candidates) and exits. Needs no running server. |
| `maintenance [--once]` | Runs the background tasks outside the API. `--once` runs each task once and exits non-zero on failure. |

Next: [04-backend-core.md](04-backend-core.md).
