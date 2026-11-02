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
    system-status/      the "API online" line on public pages, and the System page (/admin/system)
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
| `/admin/bookmarks` | Bookmarks: the team's starred candidates, with who added each | signed in |
| `/jobs`, `/jobs/new`, `/jobs/:id` | Jobs | signed in |
| `/admin/ai-usage` | AI spend | signed in |
| `/admin/users` | Staff accounts | admin |
| `/admin/system` | System | signed in |
| `/settings` | Settings: links to Saved searches, Change password, Users (admins only) and System | signed in |
| `/settings/searches` | Saved searches: your own past searches, starred first, with Open / Star / Delete | signed in |

The sidebar lists Candidates, Add candidate, Bookmarks, Jobs, Add job, AI spending and Settings. Settings stays highlighted on the pages it opens. The bottom of the sidebar holds only the signed-in name, role and Sign out; Change password moved to Settings (`app/SettingsPage.tsx`).

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
| `useSearchFilters()` | Keeps the search text and filters **in the URL** (`?q=...&city=...`), so a search survives refresh and can be shared as a link. Also `savedId` (the `search=` param) and `startSearch(q)`, which sets the text and drops `search=` in one URL update. |
| `useSavedSearch(id)`, `useRememberSavedSearch()` | A saved search reopened (`staleTime: Infinity`, free). A finished search is put straight into that cache, so pointing the URL at it makes no request. |
| `useSearchHistory()`, `useStarSearch()`, `useDeleteSavedSearch()` | The Saved searches page. Keys sit under `['saved-searches']`, which is free to refetch, so candidate deletes invalidate it. |
| `useCandidateSearch(filters)` | The browse list (no search text). `useInfiniteQuery` with cursor paging ("Load more"). |
| `useMeaningSearch(filters)` | Search by meaning. Calls `searchByMeaning` (SSE) and collects the stage events in `stages` for the progress panel. `staleTime` 5 minutes and no refetch on focus, because each run is a paid AI call. |
| `useJobMatches(jobId, jobContentKey, { enabled })` | Job matching. Runs only after the user clicks **Find candidates** (`enabled`). The key includes the job's matching fields, so editing those fields never reuses old results, and never starts a paid run by itself. |
| `useRunLog()` | A tiny state holder: `begin()` clears the stages and returns the stream callback that fills them. |
| `useCandidate(id)` | One profile. |
| `useCreateStaffCandidate`, `useUpdateCandidate`, `useDeleteCandidate` | Mutations. On success they update the cached detail and invalidate cached search lists. |
| `useBookmarks()`, `useToggleBookmark()` | The shared bookmark list (key `['candidates', 'bookmarks']`, outside the search keys, so a star never starts an AI search) and the star toggle. The toggle is optimistic: the star flips at once and flips back if the call fails. `BookmarkButton` (☆/★, `aria-pressed`) sits on the browse table, every `MatchCard` and the profile header. |

Query keys are built in one `keys` object per file. Job matches deliberately sit under a different key prefix than searches, so invalidating searches can't trigger a paid ranking.

## The search page

`CandidateSearchPage.tsx`:

- **Empty search box** → browse list (`useCandidateSearch`), filtered in SQL, no AI.
- **Text + Search button / Enter** → `useMeaningSearch`. Typing alone never sends anything (each search is paid and sends text to OpenAI). The search uses a snapshot of the filters (`submitted`) taken when Search is pressed; editing a filter afterwards shows "Press Search to apply the changed filters" and costs nothing until then.
- While it runs, `SearchProgress` shows the five steps in recruiter words ("Finding likely people", "Hiding personal details", ...) on one line with a status each. The step under way is shown large. While the AI judges, that is the real count ("Read 40 of 100 profiles") with a `Meter` filled to the true share. Under it: what the finished steps found ("Looking first in Delhi · Found 100 profiles"), and "Usually takes 20 to 30 seconds · 12 s so far" (the range was measured on real searches). There are no animations beyond the spinning marker, and no made-up percentages. Component labels are the wording; the API's stage names stay `embedding`, `retrieval`, and so on.
- When results arrive, the page header says how much work went in: "Checked 100 profiles, best 25 shown", or with filters "Checked 100 profiles, 18 meet every filter". The job page says "Checked N profiles, M meet every requirement".
- `MatchResults` shows two lists of `MatchCard`s: **perfect matches** (pass every filter) and **filtered out** (with "Fails filter: City", etc.). Each card leads with the verdict and the AI's reason for each criterion. Email, source and date added are on the profile and in the browse table, not on the cards.
- The list appears only once the AI has finished, with at most 25 perfect matches and 10 filtered out. Until then only `SearchProgress` shows, and results from the previous search are hidden too.
- **The search stays until Clear or a new search.**
  - A finished search adds `search=<saved id>` to the URL; with it, the page shows the saved copy instead of searching (free).
  - `lastSearch.ts` keeps that URL in `localStorage`, so a bare `/admin/candidates` (the profile's back link, the sidebar, a new tab) redirects to it before the page mounts, with the box filled in.
  - Clear, emptying the box, or pressing Search forgets it.
  - The "Star this search" button keeps it past the 50-search limit.
  - A gone id says "This saved search is no longer available. Press Search to run it again."

The job detail page uses the same pieces through `JobMatches`.

## The System page

`SystemPage` (Settings → System, for all staff) shows three blocks:

- **Status:** API, database and pgvector, and when they were last checked. It comes from `useSystemStatus`, which polls the public `/ready` every 30 s. `fetchReadiness` keeps the 503 body, so the page can say which dependency is down.
- **Search and embeddings:** how many candidates and jobs have up-to-date embeddings, and the AI budget.
- **AI models:** the models and prompt versions in use.

The last two come from `GET /api/v1/admin/system` through `useSystemDetails`, also every 30 s. If that call fails, an alert shows and the status block keeps working. Staff pages have no status dot of their own (user decision); public pages still show "API online" in their footer.

## Forms

- Each form has a zod schema (`schema.ts`) that mirrors the backend rules, so users see errors before submitting.
- The backend is still the source of truth. Server-side 422 errors are mapped back onto the form fields (`serverErrors.ts`).
- Edits send the `version` that was loaded; a 409 `version_conflict` shows "changed by someone else, reload".
- Rules that must match the backend live in `shared/forms/` (tags, salary, currencies). When you change a rule, change `backend/app/shared/validation.py` too.
- **Resumes.** `ResumeUpload` (in `candidate-profile`, used by the public form and Add candidate) sends the file to `POST /api/v1/resumes` and calls `fillFromResume`, which fills **only empty fields** and returns their labels. The upload has three visible states: a drop zone (click or drag a file), `ReadingResume` (spinner, file name and a live seconds counter that warns after 30 s; also used by `ResumeBar`), and a summary of how many fields were filled, with one chip per field and what to do next. After Add candidate, the new profile page shows "Candidate added" (and whether a resume is attached) from router state. Both form schemas carry a `resume_ref` field ('' → null) so the resume is linked when the profile is saved. On the profile page, `ResumeBar` shows **See resume** (a plain link opening the PDF in a new tab, so no blob handling is needed) and **Upload / Replace resume** (`useAttachResume`).

## Styling rules

- Use the colour **tokens** (`bg-surface`, `text-fg-muted`, `text-danger`, `bg-accent` ...), never raw Tailwind colours or hex values. Tokens have light and dark values in `src/index.css`.
- Blue is the only accent; red for errors and destructive actions; green for success; amber only for "near limit" or "degraded".
- Numbers, money, dates and ids use the `num` class (tabular figures).
- Shared UI pieces are in `shared/ui` (`Button`, `Alert`, `Stamp`, `Meter`, `ModalDialog`, `TagInput`, `FormField`).

## Testing the frontend

- Component tests use `stubApi(route(...))` from `src/test/fakeApi.ts` to fake backend responses, including SSE streams with `sseBody(...)`. No real network.
- Playwright e2e tests (`frontend/e2e/`) start their **own** API on port 8011 against the test database and Vite on 5181, so they don't touch your dev data. They use a placeholder OpenAI key, so search answers 503 there; e2e specs find seeded candidates with filters instead.

## Deploying (Vercel, one app)

The frontend and the API deploy together to Vercel: `scripts/deploy-vercel.ps1` builds the frontend, copies `dist/` into `backend/frontend_dist`, and deploys `backend/` (the Vercel project root). FastAPI serves those files with `app.frontend("/", fallback="index.html")` and Vercel moves them to its CDN (`[tool.vercel.fastapi.static] cdn = true`), so the browser talks to one domain and `BASE_URL` stays empty. A deploy from Git (Vercel building the repository) has no copy, because the folder is gitignored, so Vercel's build step `backend/vercel_build.py` (`[tool.vercel.scripts] build`) runs `npm ci && npm run build` in `../frontend` and copies `dist/` in; it skips that when the script already did. Locally `backend/frontend_dist` doesn't exist and Vite serves the frontend as before. Resume uploads are capped at 4 MB (`MAX_RESUME_BYTES` here and in the API) because Vercel refuses request bodies over 4.5 MB.

Next: [07-coding-style.md](07-coding-style.md).
