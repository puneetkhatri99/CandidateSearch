# 7. Coding style

The binding rules are in [RULES.md](../RULES.md). This page shows what they look like in real code, so you can write code that fits in.

## Before you write anything

1. Read [LEARNINGS.md](../LEARNINGS.md). Many traps are already written down.
2. Find code that already does something similar and copy its shape. The smallest change that fully solves the task wins.
3. Don't add a dependency for something a few lines or the standard library can do. If you must add one, say why.

## Python

### Types everywhere

`mypy --strict` must pass. Every function has argument and return types.

```python
async def get_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, actor: AuthContext
) -> CandidateDetail:
```

`Any` needs a comment explaining why:

```python
# Any: the sort key is a datetime, str or Decimal depending on the sort.
SortKey = tuple[Any, uuid.UUID]
```

### Async for anything that waits

Database and HTTP calls are `async`. Never block the event loop. CPU-heavy work (argon2) goes to a thread:

```python
async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)
```

### Names say what, not how

`rank_by_judgements`, `find_stale_ids`, `candidate_ids_passing`. Not `process`, `handle`, `do_stuff`. No abbreviations except well-known ones (`id`, `url`, `db`).

A leading `_` means "private to this module". Other modules must not call it.

### Keyword-only arguments for clarity

When a function takes several values of the same type, force names with `*`:

```python
async def record_failure(
    session: AsyncSession, *, entity_id: uuid.UUID, model: str, content_hash: str, error: str, target: EmbeddingTarget
) -> None:
```

### Comments explain why, not what

Good:

```python
# clock_timestamp, not now(): now() is the transaction start, stale after a lock wait.
now = (await session.execute(select(func.clock_timestamp()))).scalar_one()
```

Bad:

```python
# get the current time
```

A deliberate shortcut gets a `shortcut:` comment that names the limit and when to upgrade:

```python
# shortcut: unindexed lower(city) scan, fine for ~1,000 rows; add an index around 100k.
```

### No dead code

No commented-out code, no `print`, no unused options "for later".

## Layers, again

| Do | Don't |
|---|---|
| Router: parse, call one service function, return. | Put `if` business rules in a router. |
| Service: open `async with session.begin():`, apply rules, call repository, audit. | Run raw SQL in a service. |
| Repository: SQL only. | Open transactions or raise business errors in a repository. |
| Import another feature from its package: `from app.features import candidates`. | `from app.features.candidates.models import Candidate` in another feature. |

## Errors

Raise an `AppError` subclass; never return error dicts or build responses by hand.

```python
# features/jobs/exceptions.py
class JobNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("Job not found.")

# features/jobs/service.py
if job is None:
    raise JobNotFoundError
```

When you catch an exception to re-raise a nicer one, chain it with `from exc` so the cause is kept in logs.

## Validation

- Request bodies extend `StrictModel` (rejects unknown fields, strips whitespace, rejects NUL characters).
- Reuse the helpers in `shared/validation.py` (`text(...)`, `tag_list(...)`, `Country`, `Currency`, `YearlySalary`).
- Mirror important rules with a database `CHECK` constraint. The schema gives users a friendly error; the constraint protects the data if a code path skips the schema.
- Use `custom_error(code, message)` for readable messages.

## Database

- Every schema change is an Alembic migration. Generate one with `alembic revision --autogenerate -m "..."`, read it, fix it, run `alembic upgrade head`, then `alembic check` (no drift).
- Never edit a migration that has been applied to the dev database. Add a new one.
- Every table extends `TimestampedModel` (UUID `id`, `created_at`, `updated_at`).
- Add an index for every foreign key and every column used to filter or sort.
- Use `UNIQUE` constraints for dedupe (email); don't rely on "check, then insert".
- No N+1 queries: load related rows in one query (`selectinload`, or `IN (...)` as in `get_full_names`).
- Never build SQL with f-strings. Use SQLAlchemy expressions.

## Privacy (read this twice)

Candidate data is personal data.

- **Never log personal data.** Log ids and counts. Log `type(exc).__name__`, not `str(exc)`: driver messages can echo row values.

  ```python
  logger.error("maintenance_task_failed", task=task.name, error_type=type(exc).__name__)
  ```

- **Never send names, emails, phones or links to OpenAI.** Only `search_document` (redacted) and selected facts go out. Search queries that look like identifiers are refused.
- **Audit staff actions** with `record_event`, in the same transaction. Record field *names*, never values.
- Never put query strings in logs; they can hold a name.

## AI calls

- Use `core/embeddings.py` or `core/llm.py`. Never create an `openai.AsyncOpenAI` anywhere else.
- Wrap every call in `ai_usage.metered_call`.
- Use structured outputs (a Pydantic model as `response_format`). Never parse free text with regex.
- Prompts live in `features/<feature>/prompts/<name>_v<N>.md`. Changing a prompt means a new version file, and the result records `prompt_version`.
- Let the LLM judge; let code decide anything that is a plain rule (ordering, work-mode compatibility).
- Don't add your own retry loop around the SDK; it already retries.

## Tests

- Unit tests next to the feature: `features/<f>/tests/`. Integration tests in `backend/tests/integration/` against a real Postgres test database.
- OpenAI is always mocked at the HTTP layer; a guard fails any test that tries a real network call.
- Every bug fix comes with a test that fails without the fix.
- Never delete or weaken a test to make it pass.

## Frontend

- TypeScript strict; no `any`.
- Import other features only through their `index.ts`, using `@/`.
- Colour tokens only, never raw Tailwind colours.
- Paid actions (searches, matching) only on an explicit user action, never on typing or page load.

## Before you finish

```powershell
cd backend
.venv\Scripts\ruff.exe check .; .venv\Scripts\ruff.exe format --check .
.venv\Scripts\mypy.exe app
.venv\Scripts\pytest.exe
.venv\Scripts\alembic.exe check

cd ..\frontend
npm run lint; npx tsc -b; npm test
```

Then: update this guide if behaviour changed, and add a LEARNINGS entry if you discovered something non-obvious.

## Windows gotchas

- Write files with the editor, not PowerShell `Set-Content`: Windows PowerShell 5.1 adds a BOM and can corrupt non-ASCII characters.
- Python files must be saved without a BOM.
- Piped input in PowerShell gets a BOM and `\r\n`; that's why the CLI strips them.

Next: [08-decisions.md](08-decisions.md).
