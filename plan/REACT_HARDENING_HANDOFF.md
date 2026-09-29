# React hardening — handoff for the next session

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
| Commits on branch | 17 (6 pre-existing + 12 from Waves 0 and 1) |
| Working tree | clean |
| React | **204 tests** across 16 files, `npm run verify` green, no warnings |
| Python | **701 passed**, `data/lecgap.db` byte-identical before/after |
| Wave 0 (tooling) | **done** |
| Wave 1 (correctness) | **done** — all 8 defects closed |
| Wave 2 (colour system) | **next** |
| Waves 3–4 (parity, E2E, cutover) | not started |

Re-check: `cd frontend-react && npm run verify` ·
`& "D:\Anaconda3\envs\lecgap\python.exe" -m pytest tests -q`

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
4. **One colour system.** Panels ask for semantic tokens, never hex. *This is
   Wave 2 — the React app currently ships a second, untested palette and
   violates this today.*
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

## 6. Wave 2 — the next task, in full

**Goal: the React app stops shipping a second, untested colour palette.**

`frontend/theme.py` is the system of record: 21 tokens × 2 palettes, plus
`readable_on()` and the node ramp, pinned by 26 property tests in
`tests/test_theme.py`. `frontend-react/src/theme/theme.ts` currently hand-writes
~20 hexes, a *disjoint* palette, and does not even use the `page` token
(`#0b0f19` vs the real `#0e1117`). So the app has two palettes and the untested
one is shipping.

Decided with the user: **port the tokens and the contrast logic to TS and pin
them with Vitest parity tests** — not a build-time generated JSON. The cross-check
that keeps the two from drifting is part of the job (W2.4).

### W2.1 — tokens + contrast + node colours
- Port all 21 tokens × 2 palettes **verbatim** from `frontend/theme.py`.
- Port `channels` (throws on non-hex — a test pins that), `luminance`,
  `contrast_ratio`, `hsl`, `palette`, `readable_on` (tie → `ink_light`),
  `node_fill`, `node_pair`.
- **Two traps in `hsl`:** Python's `colorsys.hls_to_rgb` is **HLS, not HSL** —
  argument order `(h, l, s)`. And `Math.round` is provably identical to Python's
  banker's rounding across the whole ramp (verified: zero channels land on an
  exact `.5`), so it is safe.
- **Identity-mode node colours need a synchronous SHA-256.** `crypto.subtle` is
  async and `nodeFill` is called during render, so use `@noble/hashes`. Without
  it every identity-mode colour changes and the golden tables break.
  Only digest bytes **0** (hue) and **2** (saturation) are used; sat ∈ [0.45, 0.63).
- Order ramp: teal `175°` → coral `8°`.

### W2.2 — rebuild the MUI theme from the tokens
- Delete every hex in `src/theme/theme.ts`; build `createTheme` from
  `palette(base)`.
- Generate `index.css` custom properties **from the palette**, so `MuiCssBaseline`'s
  body background and `palette(base).page` cannot diverge — the React analogue of
  `test_the_declared_theme_matches_the_palette`.
- Light/dark toggle: store + `localStorage` + `prefers-color-scheme` default.
  This settles **OPEN decision #2**.

### W2.3 — Vitest parity + enable the scanner
Port `tests/test_theme.py` tests 1–19, including the two sweeps worth writing as
`it.each`: the **72-hue** `readable_on` sweep (worst measured: 5.73 dark / 7.46
light) and the **24-hue** node-vs-canvas sweep (1.317 dark / 1.348 light). Add
golden hex tables — the agent measured the order ramp (11 ranks) and an 8-name
identity corpus, so drift is a literal diff. Tightest constraint in the system:
dark `bad` on `surface_alt` = **4.70**, only 0.20 over the 4.5 floor.

Then **enable the hex scanner rule** in `.eslintrc.cjs` (currently pinned `off`).

### W2.4 — keep the two palettes from drifting
You chose porting over generation, so a cross-check is what makes "one colour
system" an enforced fact. Options: a Vitest that shells out to read
`frontend/theme.py`, or a small Python test that parses `src/theme/tokens.ts` and
compares. **Verify the guard fails** before trusting it.

## 7. Later waves, briefly

- **W3.1** react-flow DAG. `graphImportance` ported to TS — four fidelity traps:
  **no `localeCompare`** (Python sorts by code point, and locale order flips
  `"a"`/`"B"`); split on `/\s+/` not `' '`; Unicode-aware `isalpha`; and
  `[...name].length` not `.length`. Then zoom 0.5–2.0, edge-type multiselect,
  significance slider, colour-by toggle, legend, "links drawn", both notices, the
  empty placeholder, `resize: vertical`. Edge tooltip = confidence +
  `source_method` + **evidence** — the professor's exact sentence, the one
  feature Engine 2's plan calls genuinely hard to copy. Settles **OPEN #3**.
- **W3.2** timeline + coverage. Note the coverage % is the *merged-span* union,
  one rect per merged run so gaps stay visible, and **band label ink is measured
  per band**, never fixed.
- **W3.3** quota row from `/usage` — no React call exists yet. Goes in
  `AppLayout` (both dashboards), 30 s TTL, reads the active transcribe job's
  `duration_s`.
- **W3.4** library: clip browser, stalled-row triage, course/lecture deletes,
  duplicate-upload dialog, `normalizeCourseId` + the new-course bootstrap (kills
  the hardcoded `selectedCourseId: 'ml'`).
- **W3.5** wire or delete the 10 wrapped-but-uncalled endpoints.
- **W4.1** Playwright. **OPEN #5.**
- **W4.2** §6 parity checklist, then the README (it currently overclaims a DAG
  that does not exist yet).

Bundle size is already 572 kB (177 kB gzipped) and react-flow will add to it —
`manualChunks` or route lazy-loading should land with the DAG.

## 8. Not yet confirmed by a human

Two things are unit-tested and reasoned but have not been seen by a person:

1. **The live SSE round-trip against a real server.** The feed is tested with an
   injected transport, not a real socket. Worth one manual run with the backend
   up: open `/student`, start a job, and confirm the drawer updates and the
   status dot goes green.
2. **The 401 banner's real-world appearance.** Test covers the logic; nobody has
   looked at it. Set `LECGAP_API_KEY` on the server and load the app without
   `VITE_LECGAP_API_KEY`.
