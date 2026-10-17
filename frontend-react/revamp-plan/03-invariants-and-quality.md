# 03 · Invariants, quality, testing, perf

This is the file to read before touching `AppShell`, `useJobFeed`, or anything
that renders `<Outlet/>`. Each invariant below has cost real debugging time;
each one has a guard, and the guard must stay green through every phase.

## 1. The invariants, with their guards

### I1 · `<Outlet/>` must not subscribe to job state

**The failure:** a 1 Hz SSE tick updates a component that renders the page
outlet → the whole route re-renders → a playing `<video>` restarts. This was the
original defect the rebuild existed to remove.

**How it holds now:** `useJobFeedConnection` in `AppLayout` *connects* and reads
nothing. Readers are `useJobs` / `useActiveJobs` / `useJobCards` /
`useFeedStatus`, which are `useSyncExternalStore` over the React Query cache, and
they are used by `Navbar`, `JobDrawer`, `JobCompletionHost` — never by a parent
of the outlet.

**What the plan must not do:** `AppShell` calls `useJobFeedConnection` exactly as
`AppLayout` does. The Sidebar gets its job badge from `useActiveJobs` (a leaf
read), not from a prop threaded down from the shell, and the shell must not read
the job list to decide anything.

**The guard:** `src/lib/rerender.test.tsx` (§1) — including its blunt
`"must not contain 'jobFeed.'"` source scan. If a new file needs to mention the
feed, it says "the feed module" in prose, or the scan fails.

### I2 · The jobs cache key is fed by the stream, never fetched

**The failure:** `useQuery({ queryKey: jobs, queryFn: () => empty })` fetches,
and that resolution can land *after* the first SSE snapshot and overwrite it
with an empty list — an intermittently empty drawer.

**How it holds now:** the stream writes with `queryClient.setQueryData`; readers
use `useSyncExternalStore`. There is no `queryFn` for that key anywhere.

**What the plan must not do:** the new Jobs view reads `useJobList` /
`useJobCards`. It does not "add a real query" for `/jobs`, even though the
endpoint exists. The endpoint is reached by `lib/jobFeed`'s polling path only.

### I3 · The sink writes under the course the connection was made for

**The failure (fixed, with a regression test):** the sink was built once in a
ref, closing over the first render's `courseId`. On a first visit that is
`null`, so every snapshot was written to `['jobs','']` while readers read
`['jobs','ml']` — the drawer said "Connecting" forever against a healthy stream.

**How it holds now:** the sink is created inside the connection effect, so its
closure is the course it is for.

**What the plan must not do:** move `useJobFeedConnection` into a component that
can re-mount per view or per course switch in a different way, and re-introduce
the ref pattern. It stays in the shell, called once, with `courseId` as its
dependency.

### I4 · A playing video survives a job tick (§10)

Browser tier: real Chromium, real SSE, real `requestAnimationFrame` coalescing
(`lib/jobsSink.ts`). This is the gate that proves I1–I3 together, end to end.

**What the plan must not do:** render the video inside anything that subscribes
to the feed. `VideoPlayer` and the Clips/Remediation views read no job state.

**The guard:** `e2e/video.e2e.spec.ts`, which will need its `goto` updated to
`/student/clips` in P3 — that is the one deliberate edit to that spec.

### I5 · No colour literal outside `src/theme/`

Two guards, one AST (`.eslintrc.cjs` `no-restricted-syntax`) and one raw scan
(`theme/scan.test.ts`), both covering hex **and** CSS colour functions. The scan
is deliberately stricter than lint: it matches inside comments too.

**What the plan must not do:** put a colour in a new component's `sx`. Every
value comes from a token, or from `tint()` / `token()` / `gradient()` in
`theme/alpha.ts`. The new `CoverageTimeline` will want concept-band colours — it
takes them from `theme/nodeColors.ts`, exactly as `DagView` does, which is why
that module exists.

### I6 · Every named token exists

`theme/scan.test.ts` extracts `token('x')` / `tint('x', n)` /
`gradient('x','y')` names from every non-theme source and asserts each resolves
in the palette. A typo would otherwise emit `var(--lgc-<typo>)` — invalid at
computed-value time, silently falling back, which is how the DAG's edges once
vanished.

### I7 · `getAuthBanner` behaviour: sticky, with an exit

The 401 flag is sticky by design (a later success does not clear it) **and** has
exactly one exit: `AuthBanner`'s Retry, which clears the flag and calls
`resetQueries()`. Both halves are tested. The plan keeps the banner in the shell.

### I8 · Job completions are announced in the page body

`recordNewCompletions` records into `useCompletionStore`;
`JobCompletionHost` renders the notice. Neither lives inside a self-refreshing
surface, so the message cannot flash and vanish on the next tick. The new Jobs
view must not render completion notices — it shows job rows, not announcements.

## 2. Error handling, per layer

| Layer | Owner | Behaviour |
|---|---|---|
| Render throw | `ErrorBoundary` (root in `main.tsx`, per-route around `<Outlet/>`) | Panel naming the view + Retry; sidebar and drawer stay mounted |
| Query error | the view | `ErrorAlert` with the backend `{detail}` and a retry affordance where the action is repeatable |
| Mutation error | the view | inline, next to the control that failed; never a toast that can be missed |
| Transport failure | `api/client.ts` | one retry on connection errors; typed error out; never a raw throw to a component |
| 401 | `AuthBanner` | one banner, sticky, with Retry |
| Feed outage | topbar chip + Jobs view | three distinct states (live / polling / disconnected), never one label |

**The rule for new views:** every one of the 13 gets a loading state, an empty
state with a next action, and an error state. The mock shows all three for each;
the implementation copies them. An empty `<Box>` is never an acceptable state.

## 3. Accessibility commitments

Carried over, plus what the new shell adds:

- **Landmarks.** `<nav aria-label="Sections">` for the sidebar, `<main>` for the
  outlet region, `<header>` for the topbar. Screen readers can jump.
- **Current view is announced.** The active nav item gets `aria-current="page"`;
  on route change, `document.title` updates and focus moves to the view's `h1`
  (tabIndex `-1`), so a keyboard user is not left at the top of the sidebar.
- **Icon-only controls carry `aria-label`.** This is load-bearing, not
  decoration: a MUI `Tooltip` does not give its child an accessible name — it
  sets `aria-describedby` while open. The e2e tier found this once by timing out
  on `getByRole`.
- **The DAG stays keyboard-operable.** Nodes are buttons with Enter/Space, one
  interactive element per node (React Flow's wrapper is opted out of with
  `selectable: false, focusable: false`).
- **Sliders get `aria-label` and a visible focus ring.** The themed `MuiSlider`
  keeps a 3px `tint('info', 18)` ring, matching `MuiTextField`.
- **Reduced motion is honoured.** `Rise` returns its children unanimated when
  `useReducedMotion()` is true — and the stagger is bounded (40 ms × index,
  capped 160 ms) so a long list never delays a late row by a second.
- **Focus is never trapped** in the drawer or a dialog beyond what MUI already
  guarantees; Escape closes both.

## 4. Testing strategy

### What stays exactly as it is

All 490 unit tests. They test `lib/`, `api/`, `store/`, `theme/`, and the
components being *moved* — a move must not need a test edit, and if it does, the
move changed behaviour.

### What gets added, per phase

| Phase | New tests |
|---|---|
| P0 shell | `Sidebar.test.tsx` — nav groups render, active item marked, badge from the cache |
| P0 shell | `App.test.tsx` extended — each route renders its view, legacy paths redirect |
| P1 lectures | `UploadDialog.test.tsx` — duplicate gate, progress states, cancel |
| P2 map/detail | `CoverageTimeline.test.ts` — port golden values measured from the Python |
| P3 quiz | `RemediationView.test.tsx` — ordered plan, clip per step, empty state |
| P4 faculty | `TelemetryStrip.test.ts` — root concepts = in-degree 0, gap counting |
| P5 system | `JobsView.test.tsx` — orphaned/stalled/expired labels, cancel wiring |

### The e2e tier, and exactly what breaks when

This is the honest section. Routes change, so browser specs change with them:

| Spec | Breaks at | Edit |
|---|---|---|
| `app.e2e.spec.ts` — reads lectures table, clips, SSE | P1 (lectures view) and P3 (clips view) | `goto('/student/lectures')`, `goto('/student/clips')`; assertions unchanged |
| `dag.e2e.spec.ts` | P2 | `goto('/student/map')` |
| `theme.e2e.spec.ts` | P0 | `goto('/student/overview')`; the job-drawer assertions keep working (drawer stays in the shell) |
| `video.e2e.spec.ts` (§10) | P3 | `goto('/student/clips')` — the invariant itself is untouched |
| `shots.spec.ts` | P0 | new screenshot targets per view (it is a review tool, not a gate) |

One new e2e test per view at the phase that adds it: renders, no console
errors, no failed requests, one meaningful assertion. That is 13 cheap tests
that make "the view is wired" non-negotiable, and they are the tier that caught
the last two real defects.

### What no test can see (kept honest)

Colour harmony, spacing, whether a heading wraps badly at 1280px. Those are
screenshot review (`npm run shots`) and human eyes. The plan budgets for that
review at the end of each phase rather than pretending tests cover it.

## 5. Performance budget

| Metric | Budget | Today |
|---|---|---|
| First paint, gz | ≤ 200 KB | ~197 KB (`index` + `vendor-react` + `vendor-mui` + `vendor-query`) |
| Each view chunk, gz | < 16 KB, except Map | Map carries reactflow (~52 KB gz), already lazy |
| Requests on a cold view visit | ≤ 2 | `/faculty` currently fires 4 before render |
| Longest task during a job tick | < 16 ms | rAF-coalesced; one `setQueryData` per frame |
| Live `<video>` restarts during a job | 0 | 0 (I4 gate) |

**Where lightness comes from, in order of effect:**

1. Route-level laziness — a view's code and its queries mount on entry, not at boot.
2. The existing vendor split — app code deploys without invalidating MUI.
3. reactflow behind Suspense — the graph never blocks first paint.
4. Not fetching what the screen does not show (§5 of `02-backend-map.md`).

**Not on the list, deliberately:** swapping MUI for something smaller (the whole
token system, the guards, and 490 tests are built on it), adding a state
library, adding a charting library, or reaching for a virtualised table before
a table is shown to be slow with real data.

## 6. Definition of done for the revamp

- All 13 views reachable, each with loading / empty / error states.
- `npm run verify` green: type-check, lint (zero warnings), unit suite.
- `npm run test:e2e` green, including the §10 video gate on its new route.
- Both colour guards and the token-name guard green with zero exceptions.
- First paint within budget; no view fetches data it does not display.
- No new runtime dependency.
- Every remaining open question either decided or recorded in
  `05-open-decisions.md` — nothing silently deferred.
