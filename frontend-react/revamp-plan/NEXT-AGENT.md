# LecGap frontend revamp — handoff for the next agent

> **Read this first, then `revamp-plan/README.md`.** This file says *where the
> work stands* and *what to do next*. The plan folder says *why* things are the
> way they are.
>
> **Status: P0–P5 complete and committed. P6 (review, a11y, copy pass) is the
> remaining phase — landmark audit, keyboard walk, `npm run shots`.**
> Branch `engine2/scaffold`. `main` is the untouched Streamlit baseline.

## Branch and where the commits are

```
cd C:\Users\hp\Desktop\lecture-comprehension-gap-detector
git branch --show-current     # engine2/scaffold
git log --oneline -12
git status --short            # expect: clean except frontend-react/references/ (untracked, on purpose)
```

Revamp commits, newest first — each one is a green checkpoint you can revert to
independently:

| Commit | What it did |
|---|---|
| `bf06823` | `feat(jobs)`: P5 — registry summary strip, elapsed column, orphan note |
| `833e7ac` | `feat(a11y)`: P6 — route focus, `document.title`, divergence sequences |
| `8f9b1d1` | `feat(faculty)`: P4 — CoverageView mounts `CoverageTimeline`; `TelemetryStrip` extracted |
| `d487094` | `feat(remediation)`: P3 — `GET /students/{id}/remediation` wired |
| `9e2627e` | `feat(lectures)`: P2.3 — lecture detail is real (timeline + live progress) |
| `12cb258` | `feat(map)`: P2.1 — min-confidence slider on the DAG; below-floor links are hidden (not faded), counts/caption in step, layout stable while sliding |
| `d6a95a4` | `feat(coverage)`: P2.2 second half — the renderer: `components/common/CoverageTimeline.tsx` + its render test (measured geometry, escaping, em-dash rows) |
| `26843c9` | `feat(coverage)`: P2.2 first half — the pure model: `lib/coverageTimeline.ts` + Python-measured golden tests (`buildTimelineModel`, `mergeSpans`, `supportSentence`, `pyFixed`) |
| `7ece81f` | `feat(lectures)`: upload moved into `UploadDialog`; the lecture table is the hero |
| `0abcaa6` | `feat(overview)`: in-flight card, quota card, next-actions; `usageRows` shared with SystemView |
| `ae65f63` | `feat(shell)`: sidebar mounted, both dashboards split into 13 routed views, monoliths deleted |
| `4eaa281` | `feat(layout)`: `Sidebar` + `api/usage.ts` + `lib/usageLine.ts` |
| `c958e79` | `refactor(layout)`: `CoursePicker` extracted from `Navbar` |
| `57967f3` | `feat(theme)`: Newsreader + Plus Jakarta Sans, themed `MuiSlider` |
| `1ffcd8e` | `fix(layout)`: course delete invalidates through the one rule |
| `86cdbf8` | `docs(plan)`: the revamp plan this work follows |

Before `ae65f63` the branch also holds the earlier stream of work: the colour
guard, error boundaries, the 401 Retry fix, the honest feed status, the job-feed
course-key fix, the DAG brick, the stack slimming, and the agent rebuild
(`cac5fda`, warm-dark theme + QuizPanel + ClipBrowser).

## Running it (both engines, real data)

```bash
# backend (real data at data/lecgap.db — this is NOT a test database)
D:/Anaconda3/envs/lecgap/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# React frontend, in another shell, from frontend-react/
C:/nvm4w/nodejs/npm.cmd run dev -- --port 5173 --strictPort --host 127.0.0.1
```

Then: `http://127.0.0.1:5173/student/overview`. Thirteen routes:

```
/student/overview  /student/lectures  /student/map  /student/lecture
/student/quiz  /student/remediation  /student/clips
/faculty/analytics  /faculty/heatmap  /faculty/divergence  /faculty/coverage
/jobs  /system
```

`/student` and `/faculty` redirect to their index views — kept on purpose, old
bookmarks and the e2e specs rely on it.

**Streamlit still runs too** (the baseline), but the two engines share a
database, so do not have both mutating the same course while testing.

**Use the pinned interpreter.** `python` on PATH is 3.13 without pytest —
that is a known trap in this repo. `npx vitest` may also resolve a *different*
vitest (a 5.x ghost) than the pinned 3.2.7; call the local binary directly when
in doubt:

```bash
cd frontend-react
npm run verify                      # type-check + lint + unit, the usual gate
.\node_modules\.bin\vitest.cmd run src/...      # single file, pinned version
npx playwright test                # browser tier (spawns its own backend + vite)
```

## Where things stand per route

| Route | State |
|---|---|
| `/student/overview` | **Done.** Snapshot strip, in-flight card, quota card, next-actions |
| `/student/lectures` | **Done.** Table, busy-guarded actions, stalled triage, upload dialog, remove + bulk delete dialogs |
| `/student/map` | Working (DAG brick + min-confidence filter + evidence groups + search). Min-confidence filter landed in P2.1 |
| `/student/lecture` | **Done.** Picker, coverage timeline, live progress card |
| `/student/quiz` | Working (state machine, not the mock's review tabs) |
| `/student/remediation` | **Done.** In-memory result wins, server plan is the fallback |
| `/student/clips` | Working (`ClipBrowser`, unplayable rows offer Re-cut) |
| `/faculty/analytics` | Working (`TelemetryStrip` + edges table) |
| `/faculty/heatmap` | Working |
| `/faculty/divergence` | Working (displacement table + taught/learned sequences) |
| `/faculty/coverage` | **Done.** Mounts `CoverageTimeline` (second consumer) |
| `/jobs` | Working (summary strip, elapsed column, orphan note, cancel) |
| `/system` | Working |

No stubs remain: every route is marked in the plan's phase list, and the last
four "arrives with P2/P3" copies are gone.

## Next task: P6 — review, a11y, copy pass

Per `revamp-plan/04-phases.md`. P0–P5 are done and committed; what remains is
review, not construction.

- **Landmark audit + keyboard walk** of every view. Focus management and
  `document.title` landed in P6's first chunk (`833e7ac`, `lib/useRouteFocus.ts`).
- **Copy pass** — every empty state names the next action; every error quotes
  the backend `detail`; the three feed modes keep three distinct sentences.
- **Screenshots** — `npm run shots`, dark and light, 1440 and 1280. This is the
  eye check no test does.

### P2.1 · Map polish — DONE (`12cb258`)

`src/components/graph/DagView.tsx` gained the mock's **Min confidence** slider:

- 0–100% in 5% steps, default 0% (shipped behaviour unchanged);
- the floor is INCLUSIVE — an edge at exactly the slider value draws;
- links below the floor are hidden from the canvas (the mock dims them to
  0.1 opacity, but the counts line says "drawn", so a fade would make it lie);
- `Links drawn X / Y` follows the cut, and a caption says how many links the
  floor hides and how to bring them back;
- node positions ignore the confidence cut — the layout does not shuffle
  under the pointer while sliding (only the links come and go).

### P2.2 · `CoverageTimeline` — DONE (`26843c9` + `d6a95a4`)

Ported `frontend/render.py::lecture_html` on `main` to:

- `src/lib/coverageTimeline.ts` — the pure model (`buildTimelineModel`,
  `mergeSpans`, `supportSentence`, `pyFixed`), payload in / model out;
- `src/components/common/CoverageTimeline.tsx` — the React renderer: SVG
  (track, ticks, one green rect per merged run, bands in taught order) plus
  the MUI coverage table;
- `src/lib/coverageTimeline.test.ts` + `src/components/common/
  CoverageTimeline.test.tsx` — goldens measured from the running Python, not
  derived by hand.

Rules that have bitten us in this repo before (for whoever touches the
timeline next):

- **Measure the goldens from the Python.** As with `graphImportance`, run the
  real `render.py` on a fixture and parse its output; do not hand-derive.
  The fixture in these tests exercises: overlapping AND adjacent windows
  (both merge), zero-length spans (merge-away when touching a run, drawn as
  a 1/2 px sliver when standalone), an unparsable window (a stroke `end_s:
  "oops"` — no span, no band, still a row, AND its `start_s` still stretches
  the axis to 62s), deterministic band order vs unsorted input, and label
  escaping (`Br<&>k "x"`).
- The coverage percentage is `merged union / duration`, never a sum of
  concept lengths — the fixture's sum would say 45s, the union says 38s, and
  the tests pin that distinction.
- `pyFixed` mirrors Python's `%.*f` (round-half-to-even on the true binary
  value); `toFixed` rounds exact ties away from zero — `(2.5).toFixed(0)` is
  `"3"` but Python prints `"2"`. Everything printed goes through `pyFixed`.
- The support sentence clips at 160 code **points**; a UTF-16 `slice(0,160)`
  keeps 80 astral glyphs. The astral probe in the test pins it.
- Band fills flow through `theme/tokens.ts` (`nodeFill`/`readableOn`), the
  same teal→coral ramp constants as `theme/nodeColors.ts`. The theme goldens
  already pin tokens to the Python; no hex literals outside `src/theme/`
  (the colour guard rejects them, and note: the renderer's resolved fills
  are fine, only literals in source are the problem).
- Testing Library `getByText` matches an element's *direct* text nodes —
  the caption is split around its `<b>`, so query the bold element and read
  `parentElement.textContent` (this cost one round of red tests here).

### P2.3 · Lecture detail becomes real — AFTER P2.1

`src/features/student/views/LectureDetailView.tsx` replaces its "timeline
arrives with P2" copy with the timeline above, plus:

- the **live progress card**: `GET /lectures/{id}/progress` has no caller in
  React yet. Poll it only while `status === 'transcribing'` (see
  `02-backend-map.md` §4b for why it is a poll and not part of the SSE feed).

`/faculty/coverage` then gets the same component for free — that is the point
of extracting it (second consumer proves the extraction was worth it).

Add a browser test that the timeline renders with the seeded lecture.

## P3–P5 — DONE

- **P3** (`d487094`) — `GET /students/{id}/remediation` wired. The in-memory
  quiz result still wins (freshest possible); the server plan is the fallback,
  so the study plan survives a reload. Quiz and Clips reviewed against the mock
  and left as-is (the Quiz state machine is deliberate; `ClipBrowser` already
  beats the mock's unplayable-row notice).
- **P4** (`8f9b1d1`) — `CoverageView` mounts `CoverageTimeline` (the second
  consumer that proves the extraction), and Analytics's four cards are
  `TelemetryStrip` with pure counting in `lib/telemetry.ts`.
- **P5** (`bf06823`) — JobsView gains the registry summary strip, the elapsed
  column, and the orphan note. SystemView already matched the mock.

## Invariants — do not break these

They are guarded by tests, and every one of them cost real debugging time:

1. **`<Outlet/>` must never subscribe to job state.** A 1 Hz SSE tick that
   re-renders the page restarts any playing `<video>`. Guarded by
   `src/lib/rerender.test.tsx`, which reads `AppShell.tsx` as raw text.
2. **The jobs cache key is written by the stream, never fetched by a view.**
   Guarded by the same rule in spirit; `useJobFeed` docstring.
3. **The sink writes under the course the connection was made for.** This was
   the "live feed shows nothing on a first visit" bug — regression test in
   `src/lib/useJobFeed.course.test.tsx`.
4. **A playing video survives a job tick.** The §10 gate:
   `e2e/video.e2e.spec.ts`. It was moved to `/student/clips`; do not weaken it.
5. **No colour literal outside `src/theme/`** — ESLint AST rule +
   `theme/scan.test.ts` raw scan.
6. **Every named token must exist** — `theme/scan.test.ts`.
7. **401 is one banner with a working Retry** — sticky by design; the exit is
   the Retry in `components/common/AuthBanner.tsx`.
8. **Completion notices are announced in the page body**, never inside a
   self-refreshing surface (`useJobStore` → `JobCompletionHost`).

## Tests: where they are and what they cover

- `npm run verify` — type-check, lint, unit (819 tests / 43 files as of P5).
- `npx playwright test` — 13 browser tests: app shell + job feed, DAG, theme
  (color-mix), and the §10 video gate.
- Colour/token/render guards live in `src/theme/*.test.ts` and
  `src/lib/rerender.test.tsx`.
- Per-view tests sit next to the view (`views/OverviewView.test.tsx`, …).

## Things that will waste your time if you do not know them

- **Do not edit files with PowerShell string replacement.** `Set-Content`
  through PowerShell 5.1 has twice corrupted files (NUL padding, mangled
  `·`). Use the editor tools for file edits.
- **`R` is a PowerShell alias** (`Invoke-History`) — a helper function with
  that name silently fails.
- **Two browsers tests now scope `SSE Live` to the drawer**, because the
  sidebar footer also names the feed mode. A bare text query is a strict-mode
  violation.
- **App tests must inject a query client** (`<App client={createTestQueryClient()}/>`);
  the app-wide singleton leaks payloads between test files and will crash a test
  that has nothing to do with the cause.
- **`references/` is untracked on purpose** — the author's mock dashboards and
  the style lab. Do not commit or delete it.
- Two e2e specs `goto` a specific view now; if you rename a route, grep the
  e2e folder for it.
- There are stray files from earlier sessions (`.freebuff/`,
  `lecgap_curl_test.txt`); they are ignored, not part of the app.

## When you finish a chunk

1. `npm run verify` from `frontend-react/` (type-check + lint + unit).
2. `npx playwright test` if you touched a view, a route, or anything that
   moves the shell — the browser tier is the only place layout and the video
   invariant are proven.
3. One commit per component, with the reason in the body (the repo's convention
   — see `git log` for examples). Update this file when a phase lands.