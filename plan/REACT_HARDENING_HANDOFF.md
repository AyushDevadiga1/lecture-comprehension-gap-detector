# React hardening — handoff for the next session

> **If you were pointed at this file, start with
> `plan/NEXT_SESSION_PROMPT.md` instead** — it is the self-contained entry point
> and carries the current task.
>
> ## ⚠ STOP. Nobody has watched this app work, and the tests cannot tell you.
>
> On 2026-09-29 a person was asked to run the app and reported that **every button
> was dead**: no status updates, no job progress, quizzes, extraction and clips
> all unresponsive. That was real, and it had **two independent causes**, neither
> of them the write-lock deadlock first suspected. See
> `plan/WEDGE_DIAGNOSIS_2026-09-29.md` for the full refutation.
>
> 1. **A foreign-key violation, not a lock.** `clips.concept_id` references
>    `concepts.id` and `PRAGMA foreign_keys=ON`; `extract.py` deleted a lecture's
>    concepts before its clips, so every re-extraction of a lecture that already
>    had clips raised `IntegrityError` — *after* the minutes-long LLM stage,
>    which is why it read as "the button hangs". The Python tests missed it
>    because the shared test engine did not enable foreign keys. Fixed in
>    `425388c`.
> 2. **The job feed never reached the UI at all.** `JobFeed.connect()` assigned
>    `this.sink` and then called `disconnect()`, which nulls it, so
>    `publish()`'s `this.sink?.(next)` was a permanent no-op. The drawer read
>    "Disconnected" forever. The React tests missed it because they all assert
>    through `feed.subscribe()` and connect *without* a sink — a different code
>    path from the one the app uses. Fixed in `de74a02`.
>
> Both are fixed, and `npm run test:e2e` now drives a real browser against a real
> backend to prove the feed reaches the UI.
>
> **Since then: the §10 gate is closed too.** `e2e/video.e2e.spec.ts` plays a real
> video — real bytes, real range request, real proxy, real Chromium — while a real
> `cut_clips` job publishes real progress over the real stream, and asserts the
> `<video>` was never remounted, never paused, and never had its playhead reset.
> That is the one claim the whole rebuild exists for, and it had never been
> asserted. It needed a committed media fixture (`0fc9ccd`) and a clip tree a
> test could safely write to (`8a5f539`).
>
> **What is still missing is a person.** See §4a — appearance and legibility are
> verified by nothing, and note that a wrong *number* slipped through 1,069
> passing tests until someone looked at a screenshot.


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

**Closed 2026-10-01.** All four bullets are now answered by `npm run test:e2e`:
a real browser reads a real proxied stream, `requestAnimationFrame` coalescing
runs under a real page, and a real job drives the UI end to end. The §10 gate
extends it to real playback. **Keep Playwright in front of new work** — the
reason this section had to exist is that three tiers were green over a dead app.

> **Committed on purpose.** `WORKLOG.md` is git-ignored and will not be in a fresh
> clone or a new agent's context. This file is the durable version. Everything
> below was **verified on 2026-09-28** unless a row says otherwise, and where a
> number could go stale the command to re-check it is given rather than the
> number.

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

Updated 2026-10-01, after the session that closed the §10 gate.

| | |
|---|---|
| Branch | `engine2/scaffold` — **all work lands here** |
| `main` | `5e0a434` — **do not touch.** It is the clean stable baseline |
| Branch base | `886b845`, i.e. **3 commits behind `main`**. Unchanged on purpose |
| Working tree | clean (only `output.txt` untracked) |
| Python | **736 passed**, `data/lecgap.db` byte-identical before/after |
| React (mocked) | **317 tests** across 19 files, `npm run verify` green |
| React (live tier) | **12 passed** — `npm run test:live`, real uvicorn + throwaway DB |
| E2E tier | **4 passed** — `npm run test:e2e`, real Chromium through Vite's proxy |
| **§10 gate** | **closed** — a real `<video>` survives real job ticks. See `2617fe6` |
| Gate control | `npm run verify:video-gate` — breaks playback, requires the gate to fail |
| Visual review | `npm run shots` → 6 PNGs, gitignored, **delete after review** |
| **Verified in a real browser?** | **Yes, behaviourally** — 4 E2E specs. **Appearance: no.** See §4a. |
| Wave 0/1/2 | **done** |
| Wave 3 (feature parity) | **unblocked**, pending a human confirming the app — §6 |

Re-check all four tiers:

```powershell
cd frontend-react
npm run verify        # 317 mocked
npm run test:live     # 12, real backend
npm run test:e2e      # 4, real browser
npm run verify:video-gate   # the §10 gate, proven able to fail
cd ..\..
& "D:\Anaconda3\envs\lecgap\python.exe" -m pytest tests -q    # 736
```

### What this session changed

Four commits on top of the previous twenty. In order:

| Commit | What |
|---|---|
| `8a5f539` | **`LECGAP_CLIPS_BASE_DIR`.** The gate needs real clip bytes, and there was nowhere safe to put them: `CLIPS_BASE_DIR` pointed at the repo's own `data/processed/clips/`, where 117 real clips live. Same pattern and reason as `database_url()`. |
| `0fc9ccd` | **Real media in the E2E seed.** A committed 58 KiB 12-second H.264/AAC clip. Until now the seeded clip rows pointed at files that did not exist, which is why the specs could only assert a URL was well-formed. Verified 200 + 206 with a correct `content-range`. |
| `2617fe6` | **The §10 gate.** A real `<video>` plays through real job ticks, asserted on the media element itself: same DOM node, playhead never rewound, never paused, no `loadstart`/`emptied`/`seeking`, real frames decoded. Plus a negative control. |
| `b7cd4f3` | The shots spec no longer calls a black clip player "expected". It is now a fault worth seeing. |

`main` is untouched. Nothing was pushed.

## 1a. Where the app actually is

A blunt inventory, because "the React app works" is not a state you can assume
after 20 commits of fixes.

**Working, and covered by tests:** the app shell and routing; the course picker;
two-step upload with real XHR progress; the job feed (auth, reconnect, poll
fallback, coalescing, completion announcement, stall detection, busy-disable); the
quiz (cap, async generation, draft, submit, remediation playback, feedback); the
faculty metric cards, edge table with evidence, divergence table and heatmap bars;
error surfacing and the 401 banner; the clip browser; the generated colour system
and its guards; and **video playback surviving a job tick** (§10, in a real
browser).

**Known-absent, deliberately not yet built (Wave 3):** the DAG *visualisation*
(react-flow is installed and unused — the faculty view is a flat edge table);
the per-lecture timeline and coverage view; the `/usage` quota row (no React call
exists at all); stalled-lecture triage; course and lecture deletes;
duplicate-upload detection; the new-course bootstrap (so `selectedCourseId` is
still hardcoded to `'ml'`); 10 wrapped-but-uncalled API endpoints; light/dark has a
toggle but **has never been rendered by a human**.

**Never run by a person.** No `uvicorn`, no dev server, no human eye on the
rendered result — see §9.

### 1b. Playback survives a job tick — but not structurally

Worth knowing before anyone "tidies" this, because the mechanism is load-bearing
and fragile rather than guaranteed.

`StudentDashboard` calls `useJobList`, so it genuinely re-renders on every job
tick. `ClipBrowser` is a plain, unmemoized child, so the tick walks straight
through to the component that owns the `<video>`. Playback survives only because
`key={playing.id}` lets React reconcile onto the existing DOM node and `src` is
unchanged, so the browser is never asked to reload. Nothing enforces that except
`e2e/video.e2e.spec.ts` — memoising the wrong component, or keying that element
by anything volatile, restarts playback silently and passes every other tier.

## 2. The invariants — do not break these

1. **Progress arrives by push.** A value that changes must never be the reason a
   component re-renders. The feed writes into one React Query key via an
   rAF-coalesced sink; `useJobFeedConnection` *connects and reads nothing*.
   `AppLayout` renders `<Outlet/>` and must never subscribe to job state — there
   is a static test (`src/lib/rerender.test.tsx`) that fails if it does.
   **Note the limit of that test:** it counts renders, and render counts are not
   playback. `e2e/video.e2e.spec.ts` is the behavioural half of this invariant.
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
11. **Review outputs, then delete them.** Anything a tier *generates* for a human
    to look at is scratch, and it goes once it has been looked at. Screenshots
    (`npm run shots` → `frontend-react/screenshots/`), Playwright traces and
    reports (`test-results/`, `playwright-report/`), the throwaway E2E database
    (`.e2e/`) — all gitignored, all regenerated on demand. **Never commit them.**
    A stale PNG in the tree is worse than no PNG, because it looks like evidence
    while showing an interface that may since have changed. If a screenshot is
    worth keeping as documentation, it belongs in a commit message or a plan
    document, referenced by what it showed — not left lying in a folder where the
    next session will read it as current.

## 4a. What the automated tiers cannot see

Added 2026-09-29, after a bug proved it.

| Tier | Proves | Blind to |
|---|---|---|
| `npm run verify` (317 vitest) | policy, wiring, guard rails | everything real — the transport is faked |
| `npm run test:live` (12) | real backend, real DB, real components | appearance; the browser is jsdom |
| `npm run test:e2e` (4) | a real browser, a real proxy, a real stream, real playback | appearance; assertions, not eyes |
| `npm run verify:video-gate` | that the §10 gate can actually fail | everything else |
| `pytest` (736) | the backend | the frontend entirely |

**Behaviour is well covered. Appearance is not covered at all**, and one concrete
proof that the gap is real rather than theoretical: `7efdc4c` fixed a bug that
rendered a job created seconds earlier as **330 minutes old**, because
`_iso` relabelled a naive UTC timestamp as local time and the machine is +05:30.
All 734 Python tests, 317 vitest, 12 live and 3 E2E were green while the job
drawer displayed a wrong number. They assert that a value *exists*, never that a
*number* is right, and no number is visible to an assertion.

So: **visual and numeric correctness is a human responsibility.** Use
`npm run shots` to regenerate the screenshots, look at them, and delete them
(trap 11). Do not describe the app as working on the strength of the test counts
— that is the mistake this file was originally written to prevent, and it has now
been made once already.

### A gate nobody has seen fail

Related, and learned the hard way: a test that has never failed is a test whose
failure mode is unknown. Every tier above was green over a dead app more than
once. So the §10 gate ships with a negative control —
`npm run verify:video-gate` injects an unstable `key` on the `<video>` (the
smallest edit that forces a remount and a restart), runs the real spec, restores
the file, and **requires the gate to fail**.

Two details worth copying if you add another gate. It distinguishes "caught it"
from "the harness broke": a `webServer` that never started also exits non-zero,
so it requires Playwright's status to be `failed` *and* the reporter to have
named the spec. And it refuses to run if its anchor line has been refactored,
rather than passing by never testing anything.

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

**Unblocked except for human eyes.** The feed is proven live and the §10 gate is
closed, so the two preconditions this section used to carry are met. What remains
is a person running the app and looking at it — see §9.

Goal: the React dashboard reaches parity with the Streamlit one, so
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

**Nothing has been confirmed by a human, ever.** The 2026-09-29 attempt failed to
establish even that the app loads — see the top of this file.

What has changed since: items 1–4 below are now answered by the automated tiers
against real data and a real browser, including a real playing video surviving a
real job (`2617fe6`). That is a genuine improvement on "unverified", and it is
**not** the same as "a person has looked at it" — these tiers run against a
58 KiB synthetic clip and three seeded lectures, not the real dataset.

Remaining, in the order it should be checked:

1. **Does the app load, with the developer's real data?** Not the seed. Steps 1–4
   of `plan/MANUAL_VERIFICATION_2026-09-29.md`, against `data/lecgap.db`.
2. **Does `/jobs/stream` deliver frames** — proven without a browser via
   `curl.exe -N --max-time 5 http://127.0.0.1:8000/jobs/stream`, which
   isolates the backend from the proxy from React.
3. **The live SSE round-trip through Vite's proxy**, and the Navbar dot reaching
   green.
4. ~~**A video survives a running job**~~ — **done, `2617fe6`.** Worth re-running
   by eye once against a real clip, since the automated gate uses a synthetic one
   and a 12-second clip cannot show a stall or a seek the way a 60-second lecture
   cut would.
5. **The quiz cap applies** — *Start Quiz* must generate at most 15 questions.
   The `ml` course has 153 concepts, and 153 is the signature of the cap not
   being sent. Still unverified by anything, automated or otherwise.
6. **The 401 banner's appearance** — set `LECGAP_API_KEY` on the server, load
   without `VITE_LECGAP_API_KEY`.
7. **The light theme** — the toggle exists and the tokens are contrast-pinned,
   but `buildTheme('light')` has never been rendered. `color-mix()` (used by
   `tint()`) also needs a browser check, since jsdom does not compute it.
8. **Legibility and layout at real volumes** — three seeded lectures and a 58 KiB
   clip hide everything about how 153 concepts, 51 clips or a 400-character
   concept name actually render. `npm run shots` and look; the DAG will be worse.
