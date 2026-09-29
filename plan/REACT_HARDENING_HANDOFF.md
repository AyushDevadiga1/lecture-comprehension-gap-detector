# React hardening — handoff for the next session

> **If you were pointed at this file, start with
> `plan/NEXT_SESSION_PROMPT.md` instead** — it is the self-contained entry point
> and carries the current task.
>
> ## ⚠ STOP. The app has NOT been verified working.
>
> On 2026-09-29 a person was asked to run the app and reported that **every button
> was dead**: no status updates, no job progress, quizzes, extraction and clips
> all unresponsive. 297 passing React tests and 710 passing Python tests said the
> opposite. Both were true.
>
> **The cause has since been diagnosed — see
> `plan/WEDGE_DIAGNOSIS_2026-09-29.md`.** It is not the frontend: three `extract`
> jobs wedged on a SQLite write lock, each holding one of the three
> `LECGAP_MAX_PIPELINE_JOBS` permits, and `_PipelineThrottle.__enter__` waits
> with no timeout, so every later pipeline request blocked forever. The frontend
> is untested against a live server, so a green suite is not evidence either way.
>
> The immediate task is three specified-but-unwritten fixes (F1 periodic reaper,
> F2 bounded throttle acquire, F3 per-lecture lock) in the diagnosis document.
> Do not start Wave 3 until they are in.

## 0. The most important structural gap

297 React tests pass and the app was still reported broken. The reason is that
**the entire job-feed path is mocked**. `JobFeed` takes `fetchImpl`, `sleep`,
`setTimer` and `clearTimer` as constructor seams, and `mockFetch` replaces
`globalThis.fetch`. The suite proves the *policy* and proves nothing about:

- Vite's dev proxy actually **streaming** `/jobs/stream` to a browser;
- the real server's SSE framing (`retry: 2000`, `event: jobs`, `: keep-alive`,
  a change-gated **full-array** snapshot) being parsed;
- `requestAnimationFrame` coalescing in a real browser — jsdom has it, a
  throttled or backgrounded tab does not fire it;
- a browser being able to read a streaming `fetch` body through a proxy at all;
- anything being reachable on :8000 from :5173.

**Bring Playwright forward.** Until one E2E test drives a real job against a real
server, the app's central claim — live progress without restarting the page — is
unverified. Do not start Wave 3 features before step 4 of the manual procedure
below passes.

> **Committed on purpose.** `WORKLOG.md` is git-ignored and will not be in a fresh
> clone or a new agent's context. This file is the durable version. Everything
> below was **verified on 2026-09-28**, and where a number could go stale the
> command to re-check it is given rather than the number.

## 0. Read this first, it changes where the spec is

`plan/REACT_ARCHITECTURE.md` — the decision record the whole campaign conforms
to — is **on `main` only**. This branch was deliberately left based on `886b845`
so `main` stays clean, and that doc landed on `main` afterwards.

```bash
git show main:plan/REACT_ARCHITECTURE.md          # the full doc, 416 lines
```

§0–§8 are the rules this work follows. The invariants that actually bind are
restated in §2 below, so you can work from this file alone if you prefer. The
commit messages from `b1094d7` onward each quote the relevant section, and they
are all on this branch.

## 1. Where things stand

| | |
|---|---|
| Branch | `engine2/scaffold` — **all work lands here** |
| `main` | `5e0a434` — **do not touch.** It is the clean stable baseline |
| Branch base | `886b845`, i.e. **3 commits behind `main`**. Unchanged on purpose |
| Commits on branch | 20 (6 pre-existing + 12 from Waves 0/1, 1 handoff, 4 from Wave 2) |
| Working tree | clean |
| React | **297 tests** across 18 files, `npm run verify` green, no warnings |
| Python | **710 passed**, `data/lecgap.db` byte-identical before/after |
| **Runs in a browser?** | **UNVERIFIED — see the box at the top.** Reported broken 2026-09-29; test run was inconclusive. |
| Wave 0 (tooling) | **done** |
| Wave 1 (correctness) | **done** — all 8 defects closed |
| Wave 2 (colour system) | **done** — tokens ported, theme generated, drift gated |
| Wave 3 (feature parity) | **blocked** until the app is proven to run |
| Wave 4 (E2E, cutover) | **needs to come forward** — it is the missing verification |

Re-check: `cd frontend-react && npm run verify` ·
`& "D:\Anaconda3\envs\lecgap\python.exe" -m pytest tests -q`

## 1a. Where the app actually is

A blunt inventory, because "the React app works" is not a state you can assume
after 20 commits of fixes.

**Working, and covered by tests:** the app shell and routing; the course picker;
two-step upload with real XHR progress; the job feed (auth, reconnect, poll
fallback, coalescing, completion announcement, stall detection, busy-disable); the
quiz (cap, async generation, draft, submit, remediation playback, feedback); the
faculty metric cards, edge table with evidence, divergence table and heatmap bars;
error surfacing and the 401 banner; the generated colour system and its guards.

**Known-absent, deliberately not yet built (Wave 3):** the DAG *visualisation*
(react-flow is installed and unused — the faculty view is a flat edge table);
the per-lecture timeline and coverage view; the `/usage` quota row (no React call
exists at all); the clip browser; stalled-lecture triage; course and lecture
deletes; duplicate-upload detection; the new-course bootstrap (so
`selectedCourseId` is still hardcoded to `'ml'`); 10 wrapped-but-uncalled API
endpoints; light/dark has a toggle but **has never been rendered by a human**.

**Never run by a person.** No browser, no `uvicorn`, no real SSE round trip — see
§8.

## 2. The invariants — do not break these

1. **Progress arrives by push.** A value that changes must never be the reason a
   component re-renders. The feed writes into one React Query key via an
   rAF-coalesced sink; `useJobFeedConnection` *connects and reads nothing*.
   `AppLayout` renders `<Outlet/>` and must never subscribe to job state — there
   is a static test (`src/lib/rerender.test.tsx`) that fails if it does.
2. **A finished job is announced once, by the page body.** Not from inside the
   progress surface. "Finished" is a *transition*: the SSE feed re-sends the
   terminal row forever, so `diffCompletions` compares snapshots.
3. **Every queueing endpoint returns its `job_id`**, and the feed is the only
   thing that knows `/jobs/stream` exists.
4. **One colour system.** Panels ask for semantic tokens, never hex. **Enforced in
   two layers since Wave 2:** an ESLint `no-restricted-syntax` rule, and
   `src/theme/scan.test.ts`, which also covers `index.css` and asserts that the
   MUI background, the `var(--lgc-page)` property and the `page` token are one
   value. `tests/test_theme_parity.py` then asserts the TypeScript table and
   `frontend/theme.py` are equal, token for token, and that their *derived*
   colours agree.
5. **No filesystem paths in payloads.** The React client has no path→URL mapper.
   Guarded on both sides: `tests/test_contract.py` and
   `src/api/contract.test.ts`.
6. **One invalidation rule.** `invalidateCourse(queryClient, courseId)`. A panel
   never hand-rolls a list — statically enforced.
7. **One request path.** No component calls `fetch`; `api/` and `lib/` are the
   boundary. Enforced by `no-restricted-globals` in `.eslintrc.cjs`.
8. **`main` is the stable baseline.** React merges there only at parity. Push
   only when explicitly told.

## 3. The commands that actually work

```powershell
cd C:\Users\hp\Desktop\lecture-comprehension-gap-detector
$py = "D:\Anaconda3\envs\lecgap\python.exe"   # the project env

cd frontend-react
npm run verify          # type-check + lint + test  (the gate for every commit)
npm run build

cd ..\..
& $py -m pytest tests -q
```

**To run the app** (see `plan/MANUAL_VERIFICATION_2026-09-29.md` for the full
procedure — this is only the starting state):

```powershell
# terminal 1 — must print "Application startup complete", then leave it alone
& $py -m uvicorn backend.main:app --port 8000

# terminal 2
cd frontend-react
npm run dev
```

Then open **`http://localhost:5173/student`**.

| URL | What it is |
|---|---|
| `http://localhost:5173/student` | **the React app** — this is the one to use |
| `http://localhost:8000` | the FastAPI backend — **no UI, just a 404 and a favicon** |
| `http://localhost:8000/docs` | Swagger, the API surface only |
| `http://localhost:8501` | the legacy Streamlit engine, if started |

**No `.env` is needed in `frontend-react/`.** The root `.env` has `GROQ_API_KEY`
and no `LECGAP_API_KEY`, so the backend runs unguarded and the client needs no
key. `frontend-react/.env.example` documents the optional vars
(`VITE_LECGAP_API_KEY`, `VITE_LECGAP_API_URL`, `VITE_LECGAP_QUIZ_MAX_QUESTIONS`,
`VITE_LECGAP_THEME_BASE`) — copy it to `.env` only to change one.

**Do not kill a process the other person is using.** On 2026-09-29 a uvicorn
instance was started for a manual test, judged not-up after 12s, and then killed
while the user was still trying to run the app. If you start a server, either
leave it running and say so in your summary, or do not start one.

## 4. Traps — each one cost real time

1. **Use the pinned interpreter**, not the one on `PATH`. `python` on PATH is
   3.13 (no pytest) or 3.11, and **streamlit 1.53 on 3.11 lacks
   `AppTest.file_uploader`**, so `test_two_step_upload_creates_then_streams`
   fails *spuriously*. A whole session was once spent on that phantom.
2. **`WORKLOG.md` is git-ignored.** This file is its durable replacement.
3. **Tests must never touch `data/lecgap.db`.** `tests/conftest.py` hard-sets
   `LECGAP_DATABASE_URL` to a temp dir *before* any backend import, and a
   `pytest_collection_finish` hook **fails the suite** if anything re-binds to
   the live DB. Do not add a module-level `LECGAP_DATABASE_URL` in a new test
   file: it runs at *collection* time, which is after conftest, and it wins.
4. **`QueryCache.subscribe` has no `'error'` event in React Query v5.** The
   notify events are added/removed/updated/observerResultsUpdated/
   observerOptionsUpdated, with the error only a field on the updated query's
   state. Use `new QueryCache({ onError })`. Getting this wrong produces a
   handler that silently never fires.
5. **`app.routes` does not expose the domain routes.** Current FastAPI nests
   `include_router` behind a `_IncludedRouter`, so `isinstance(r, APIRoute)`
   matches only `/health` and `/llm/backends`. Read the OpenAPI schema instead.
6. **`import.meta.glob` keys same-directory files as `./name`,** not
   `../dir/name`. A suffix lookup that assumes the `../` prefix finds nothing and
   the guard passes vacuously.
7. **Never `Set-Content` a file containing non-ASCII** from PowerShell — it
   rewrites UTF-8 as the system codepage and mangles em-dashes into `?`. Use the
   editor for those.
8. **A bare `%` in a mermaid diagram is a comment to the lexer**, and it breaks a
   *later* line, so the reported line number is a red herring.
9. **A raw `|` inside a markdown table cell silently splits the column.** A table
   row here needs exactly four `|`.
10. **`.env` holds a live `GROQ_API_KEY`.** Never commit it.

## 5. Why the design is what it is — the four findings

These are not obvious from the code, and each one invalidated the obvious
implementation.

1. **The SSE stream goes silent exactly when a job stalls.** It emits only when
   the serialized snapshot changes (`routes/jobs.py:57-60`), and a snapshot
   carries `heartbeat_at`, which the worker refreshes on every `update_job`. A
   *healthy* job therefore emits about once a second, but a **dead worker stops
   refreshing it, the snapshot stops differing, and the stream goes quiet.** A
   reactive stall counter could never fire. Hence timestamp-based stall detection
   plus `useNow`, which ticks **only while a job is in flight**.
2. **`EventSource` has no header API.** The API-key middleware exempts
   `/health`, `/docs`, `/openapi.json`, `/redoc` and `/media/*` — **not**
   `/jobs/stream`. A bare `EventSource` gets a 401 and dies silently. Hence the
   hand-rolled `fetch` + `ReadableStream` SSE reader.
3. **A feed-owned query key must never fetch.** `useQuery({ queryKey, queryFn:
   () => empty })` looks right and is not: the `queryFn` resolves and can land
   *after* the first SSE frame, overwriting it. Hence `useSyncExternalStore` over
   the query cache.
4. **The SSE feed sends a full-array snapshot, change-gated.** So twelve jobs
   starting together arrive as **one** event carrying twelve rows, not twelve
   events. This is the measurement that settled OPEN decision #1: the burst the
   decision worried about does not arise from this backend, so a per-frame cap is
   cheap insurance rather than a fix.

## 6. Wave 3 — the next task

**Blocked until the app is proven to load and the feed is proven live.** See
`plan/MANUAL_VERIFICATION_2026-09-29.md` and complete its steps 1–4 first, and
bring at least a Playwright smoke test forward from Wave 4 so this cannot recur.

Goal once unblocked: the React dashboard reaches parity with the Streamlit one, so
`plan/FRONTEND_REACT_ROADMAP.md` §6 can be walked item by item.

**Order matters.** The DAG first, because it is the feature the Engine 2 plan
calls genuinely hard to copy and the reason the rebuild exists; the rest is
breadth.

### W3.1 — the react-flow DAG
`graphImportance` ported to TS. Four fidelity traps, all from Python semantics:

- **no `localeCompare`.** Python's `str(a) < str(b)` is a code-point compare;
  locale order flips `"a"` against `"B"`. Use `(a < b ? -1 : a > b ? 1 : 0)`.
- split on `/\s+/`, not `' '` — Python's `str.split()` splits on any whitespace run.
- Unicode-aware `isalpha` — a name like `"A1 B2"` must not read as ALL-CAPS.
- `[...name].length`, not `.length` — Python counts code points.

Scoring is additive: `degree` per incident edge, **+2.0** for two or more words,
**+1.0** for length ≥ 18, **−2.5** if every letter is uppercase, **−1.0** for
length ≤ 6. The ALL-CAPS penalty is what ranks SQL keyword fragments lowest, and
the multi-word bonus is what counters it.

Then the full control set from `render.py::dag_svg`: zoom 0.5–2.0 (the renderer
clamps at 3.0 — trust the code, the comment is stale), an edge-type multiselect
over `source_method`, a "Concepts shown" significance slider, colour-by
order/identity, the legend, a "links drawn" metric, both notices, the empty-state
placeholder, and a `resize: vertical` container.

The edge tooltip is the payoff: confidence + `source_method` + the **verbatim
evidence**, i.e. the professor's exact sentence. React Flow's `title` prop is why
this is easier than the pyvis path, which had to hand-escape every
attacker-influenced string. Settles **OPEN decision #3**.

### W3.2 — timeline and coverage
`lecture_html` ported. The subtle part is the coverage percentage: it is the
**union of merged spans**, one rect per merged run, so gaps stay visible — a
single rect would overstate coverage. Band label ink is measured per band, never
fixed. `_support_sentence` returns the *shortest* transcript segment mentioning
the concept, whitespace-collapsed, truncated to 160 chars.

### W3.3 — quota row
`/usage` has no React call at all yet. Goes in `AppLayout` (both dashboards),
30 s TTL, and the "this lecture ≈ N requests" line needs the active transcribe
job's `duration_s` from the job list.

### W3.4 — library and ingest
Clip browser by lecture; stalled-row triage (resumable vs abandoned, `rerun`,
bulk delete); course and lecture deletes; duplicate-upload dialog
(`duplicate_lecture` — two-clause OR, `Path.stem` strips only the last
extension); `normalizeCourseId` / `validCourseId` / `isCanonicalKey` and the
new-course bootstrap that replaces the hardcoded `'ml'`.

### W3.5 — wire or delete the dead API surface
10 wrapped endpoints are called by nothing. Each gets a button or goes.

## 7. Two lessons from this campaign worth keeping

1. **A staged deletion bleeds into the next commit.** `git rm` stages
   immediately, so a later `git add <specific paths>` did not undo it, and the
   deletion of `src/theme/theme.ts` landed in the *tokens* commit — which
   therefore imported a file it had deleted, and could not build. Caught by
   checking `git cat-file -e` per commit. Now: after staging a subset, check
   `git diff --cached --name-status` lists exactly what you meant, and verify
   each commit builds in isolation (`git stash push --keep-index`).
2. **`Set-Content -Encoding utf8` corrupts non-ASCII from PowerShell 5.1** — it
   rewrites em-dashes as `?`. It bit twice, once silently inside a source file.
   Use the editor for any file containing an em-dash or a `→`.

## 8. Later waves, briefly

- **W4.1** Playwright. **OPEN #5.**
- **W4.2** §6 parity checklist, then the README (it still overclaims a DAG that
  does not exist yet).

Bundle size is 572 kB (177 kB gzipped) and react-flow will add to it —
`manualChunks` or route lazy-loading should land with the DAG.

## 9. Not yet confirmed by a human

**Nothing has been confirmed by a human.** The 2026-09-29 attempt failed to
establish even that the app loads — see the top of this file. The list below is
what remains, in the order it should be checked:

1. **Does the app load at all**, and is the course list populated from the real
   database? (Manual-verification steps 1–4.)
2. **Does `/jobs/stream` deliver frames** — proven without a browser via
   `curl.exe -N --max-time 5 http://127.0.0.1:8000/jobs/stream`, which
   isolates the backend from the proxy from React.
3. **The live SSE round-trip through Vite's proxy**, and the Navbar dot reaching
   green.
4. **A video survives a running job** — the §10 gate, and the entire point of the
   rebuild. Play a remediation clip, start *Extract Concepts*, keep watching.
5. **The quiz cap applies** — *Start Quiz* must generate at most 15 questions.
   The `ml` course has 153 concepts, and 153 is the signature of the cap not
   being sent.
6. **The 401 banner's appearance** — set `LECGAP_API_KEY` on the server, load
   without `VITE_LECGAP_API_KEY`.
7. **The light theme** — the toggle exists and the tokens are contrast-pinned,
   but `buildTheme('light')` has never been rendered. `color-mix()` (used by
   `tint()`) also needs a browser check, since jsdom does not compute it.
