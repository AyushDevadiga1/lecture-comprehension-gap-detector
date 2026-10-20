# LecGap frontend revamp — plan

> **What this is.** The plan for restructuring the React frontend from two
> monolithic dashboards into the approved multi-view application, without
> losing any invariant, test, or backend function along the way.
>
> **Status: approved, not started.** Nothing in `src/` has been changed for this
> plan yet. The layout it implements is `references/lecgap-full-mock.html`, and
> the type pairing is Newsreader + Plus Jakarta Sans + JetBrains Mono (chosen in
> `references/style-lab.html`).

## Why a plan before code

The current app works and is heavily guarded: 490 unit tests, 11 browser tests,
two colour guards, a token-name guard, an SSE invariant test, and a Python
theme-parity twin. The mock reorganises *where everything lives* — routes,
shell, views — which touches the exact seams those guards sit on. A restructure
that is done ad-hoc will break the §10 video gate, the colour scans, or the
e2e specs, and the failure will look like a mystery rather than a consequence.

So: freeze the decisions here, migrate in phases, and keep the gates green at
every phase boundary.

## What the plan changes, in one table

| Aspect | Today | After |
|---|---|---|
| Navigation | Two routes (`/student`, `/faculty`), role tabs in the navbar | One shell, sidebar nav, 13 routes, one view per concern |
| Shell | `AppLayout` = navbar + banner + outlet + drawer | `AppShell` = sidebar + topbar + banner + outlet + drawer |
| Views | `StudentDashboard` (799 lines), `FacultyDashboard` (433) | 7 student views, 4 faculty views, 2 system views |
| Upload | Inline card on the student page | Dialog, opened from sidebar and from Lectures |
| Coverage timeline | Not built in React | `CoverageTimeline` (port of the Python `lecture_html`) |
| Faculty stats | Three tables in one page | Analytics (telemetry + DAG), Heatmap, Divergence, Coverage |
| Jobs | Drawer only | Drawer **and** a full Jobs view |
| Sliders | Browser default `accent-color` | Themed `MuiSlider` overrides (track/thumb/focus ring from tokens) |
| Type | Space Grotesk + IBM Plex Sans | Newsreader + Plus Jakarta Sans (+ JetBrains Mono unchanged) |
| Deep links | Course only | Every view: lecture, clip, student id |

## The guardrails this plan refuses to break

Stated up front because every phase is judged against them:

1. **§1 — a component that renders `<Outlet/>` must not subscribe to job state.**
   The 1 Hz SSE tick must never re-render the page or restart a `<video>`.
2. **§10 — a playing video survives a job tick.** Browser tier, real SSE.
3. **No colour literal outside `src/theme/`.** Both guards (ESLint AST + raw scan).
4. **Every named token must exist.** The token-name scan.
5. **`jobFeed.` is touched in exactly one place** (`lib/useJobFeed.ts`).
6. **401 = one banner, with a working Retry.** Never a dead "no courses" state.
7. **Every user-visible failure says what happened and offers the next action.**
8. **Job completions are announced in the page body**, never inside a
   self-refreshing surface.
9. **No new runtime dependencies.** MUI, react-query, zustand, reactflow,
   framer-motion, @noble/hashes — that is the whole list, and it stays that way.
10. **First paint stays ≤ ~200 KB gzipped.** Views are code-split; the shell is not.

## Read in this order

| File | What it settles |
|---|---|
| `NEXT-AGENT.md` | **Start here if you are picking this up** — current state, next task, and the traps that cost time |
| `01-architecture.md` | Routes, shell, file layout, state tiers, component inventory |
| `02-backend-map.md` | Every endpoint → view → query key → states → invalidation |
| `03-invariants-and-quality.md` | The invariants above in detail, error handling, a11y, testing, perf budget |
| `04-phases.md` | P0–P6 migration with a gate at each boundary, and which tests break when |
| `05-open-decisions.md` | The four choices still open, with cost of each option |

## What this plan deliberately does not do

- No backend changes. Every endpoint already exists; one (`GET /students/{id}/remediation`)
  gets wired for the first time, and one (`GET /lectures/{id}/progress`) gains a
  real home.
- No palette change. The palette stays espresso/teal dark + warm light. Which one
  *greets* users is `05-open-decisions.md` #1.
- No mobile layout. Desktop-first, as today; narrow-width behaviour is a later brick.
- No library swaps. The type change is a font file and a theme ramp, not a framework.
