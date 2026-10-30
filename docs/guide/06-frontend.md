# 6. Frontend

A single-page React app in `frontend/`. It talks to the API over HTTP and holds no business rules of its own beyond form validation that mirrors the backend.

## Tools

| Tool | Used for |
|---|---|
| React 19 + Vite | UI and dev server (port 5180; it proxies `/api` to the API on 8010) |
| TypeScript, strict | Types everywhere |
| Tailwind v4 | Styling, with colour **tokens** defined in `src/index.css` |
| TanStack Query (react-query) | Fetching, caching and refetching server data |
| react-hook-form + zod | Forms and their validation |
| react-router | Pages |
| vitest + Testing Library | Unit and component tests |
| Playwright | End-to-end tests |
| oxlint | Lint |

Commands (in `frontend/`): `npm run dev`, `npm test`, `npm run lint`, `npm run build`, `npm run test:e2e`.

## Folder layout

```
src/
  main.tsx              entry point only
  index.css             Tailwind + colour tokens (light and dark)
  app/                  router, layouts, providers; composes features
  features/
    auth/               login, change password, route guards, user menu
    candidate-intake/   public /apply form and privacy notice
    candidate-profile/  the profile form fields, shared by intake and staff edit
    candidate-admin/    candidate list, search, detail, create/edit, job matches
    jobs/               job list, create, detail, edit, close
    user-admin/         staff accounts (admins)
    ai-usage/           AI spend page
    system-status/      the "API online" indicator
  shared/
    api/client.ts       fetch wrapper
    api/stream.ts       SSE reader
    forms/              zod helpers (tags, salary, error messages)
    ui/                 buttons, inputs, dialogs, Stamp, Meter, TagInput
    format.ts           number, date and salary formatting
  test/                 test helpers (fakeApi)
```

Each feature folder has the same shape:

| File | Holds |
|---|---|
| `api.ts` | Functions that call the backend. One per endpoint. |
| `types.ts` | TypeScript types that mirror the backend schemas. |
| `hooks.ts` | react-query hooks (`useQuery`, `useMutation`) built on `api.ts`. |
| `components/` | React components. |
| `schema.ts` | zod schemas for forms (mirror the Pydantic rules). |
| `mapping.ts` | Converting between form values and API payloads. |
| `testing.ts` | Test fixtures (fake API responses). |
| `index.ts` | **Public exports.** Other code imports only from here. |

Import rules (same idea as the backend):

- Use the `@/` alias: `import { JobMatches } from '@/features/candidate-admin'`.
- Never import another feature's internals (`@/features/jobs/components/JobForm`); only its `index.ts`.

## Pages (`app/router.tsx`)

| Path | Page | Guard |
|---|---|---|
| `/apply`, `/privacy`, `/login`, `/` | Public pages | none |
| `/account/password` | Change password | signed in |
| `/admin/candidates`, `/admin/candidates/new`, `/admin/candidates/:id` | Candidates | signed in |
| `/jobs`, `/jobs/new`, `/jobs/:id` | Jobs | signed in |
| `/admin/ai-usage` | AI spend | signed in |
| `/admin/users` | Staff accounts | admin |

`RequireAuth` (in `features/auth`) asks `GET /auth/me`. No user → redirect to `/login?next=...`. User must change password → redirect to `/account/password`. `RequireRole` checks the role. These guards are for a good experience only; **the API enforces the real rules**.

## Talking to the API

### `shared/api/client.ts`

| Name | What it does |
|---|---|
| `apiRequest<T>(path, init)` | `fetch` with the session cookie (`credentials: 'same-origin'`), JSON headers and the CSRF header `X-Requested-With: fetch`. Returns the parsed body, or throws `ApiError`. |
| `ApiError` | `status`, `code`, `message`, `details` from the backend's standard error body. Components check `error.code` (for example `version_conflict`). |
| `errorFromBody(response, body)` | Builds an `ApiError` from a failed response. |

### `shared/api/stream.ts`

| Name | What it does |
|---|---|
| `streamRequest<TResult, TStage>(path, { signal, onStage })` | Calls an SSE endpoint with `fetch`, reads the body as text chunks (`TextDecoderStream`), splits it on blank lines into events, calls `onStage` for each `stage` event, resolves on `result`, throws `ApiError` on `error`. |
| `parseBlock(block)` | Parses one SSE message into `{ name, data }`. |

Why `fetch` instead of the browser's `EventSource`: `EventSource` can't send custom headers (our CSRF header) or be cancelled with an `AbortSignal`.

## Data with react-query

Example: `features/candidate-admin/hooks.ts`.

| Hook | What it does |
|---|---|
| `useSearchFilters()` | Keeps the search text and filters **in the URL** (`?q=...&city=...`), so a search survives refresh and can be shared as a link. |
| `useCandidateSearch(filters)` | The browse list (no search text). `useInfiniteQuery` with cursor paging ("Load more"). |
| `useMeaningSearch(filters)` | Search by meaning. Calls `searchByMeaning` (SSE) and collects the stage events in `stages` for the progress panel. `staleTime` 5 minutes and no refetch on focus, because each run is a paid AI call. |
| `useJobMatches(jobId, jobContentKey, { enabled })` | Job matching. Runs only after the user clicks **Find candidates** (`enabled`). The key includes the job's matching fields, so editing those fields never reuses old results, and never starts a paid run by itself. |
| `useStageLog()` | A tiny state holder: `begin()` clears the log and returns a function that appends one stage event. |
| `useCandidate(id)` | One profile. |
| `useCreateStaffCandidate`, `useUpdateCandidate`, `useDeleteCandidate` | Mutations. On success they update the cached detail and invalidate cached search lists. |

Query keys are built in one `keys` object per file. Job matches deliberately sit under a different key prefix than searches, so invalidating searches can't trigger a paid ranking.

## The search page

`CandidateSearchPage.tsx`:

- **Empty search box** → browse list (`useCandidateSearch`), filtered in SQL, no AI.
- **Text + Search button / Enter** → `useMeaningSearch`. Typing alone never sends anything (each search is paid and sends text to OpenAI). The search uses a snapshot of the filters (`submitted`) taken when Search is pressed; editing a filter afterwards shows "Press Search to apply the changed filters" and costs nothing until then.
- While it runs, `SearchProgress` shows the five steps (embedding → retrieval → augmentation → ranking → filtering) with a status and time each.
- `MatchResults` shows two tables: **perfect matches** (pass every filter) and **filtered out** (with "Fails filter: City", etc.). Each row shows the AI's criteria notes.

The job detail page uses the same pieces through `JobMatches`.

## Forms

- Each form has a zod schema (`schema.ts`) that mirrors the backend rules, so users see errors before submitting.
- The backend is still the source of truth. Server-side 422 errors are mapped back onto the form fields (`serverErrors.ts`).
- Edits send the `version` that was loaded; a 409 `version_conflict` shows "changed by someone else, reload".
- Rules that must match the backend live in `shared/forms/` (tags, salary, currencies). When you change a rule, change `backend/app/shared/validation.py` too.

## Styling rules

- Use the colour **tokens** (`bg-surface`, `text-fg-muted`, `text-danger`, `bg-accent` ...), never raw Tailwind colours or hex values. Tokens have light and dark values in `src/index.css`.
- Blue is the only accent; red for errors and destructive actions; green for success; amber only for "near limit" or "degraded".
- Numbers, money, dates and ids use the `num` class (tabular figures).
- Shared UI pieces are in `shared/ui` (`Button`, `Alert`, `Stamp`, `Meter`, `ModalDialog`, `TagInput`, `FormField`).

## Testing the frontend

- Component tests use `stubApi(route(...))` from `src/test/fakeApi.ts` to fake backend responses, including SSE streams with `sseBody(...)`. No real network.
- Playwright e2e tests (`frontend/e2e/`) start their **own** API on port 8011 against the test database and Vite on 5181, so they don't touch your dev data. They use a placeholder OpenAI key, so search answers 503 there; e2e specs find seeded candidates with filters instead.

Next: [07-coding-style.md](07-coding-style.md).
