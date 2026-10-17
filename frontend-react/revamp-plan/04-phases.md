# 04 · Phases — migration with a green gate at every boundary

Seven phases. Each ends with `npm run verify` **and** `npm run test:e2e` green,
and each is one or two commits, so a phase can be reverted on its own. The order
is chosen so the riskiest work (P0) happens while there is the least new code,
and the newest work (P5) happens after the patterns are proven.

**Rule for every phase:** the only edits allowed are the ones the phase names.
A bug found while moving code is fixed in its own commit, so "the move was
faithful" stays a checkable claim.

---

## P0 — Shell, routes, and the pure move

**The phase that changes the most and behaves the same.**

| Work | Detail |
|---|---|
| `AppShell` | `AppLayout` renamed; adds `<Sidebar/>`; keeps `useJobFeedConnection` and the §1 discipline |
| `Sidebar` | Nav from one `NAV` array (group, label, to, badge); course picker + delete move here from `Navbar`; footer carries feed chip, quota line, theme toggle |
| `Navbar` → `Topbar` | Slimmed to breadcrumb, student id, feed chip, jobs button. Role tabs removed — the sidebar carries both groups |
| Routes | 13 routes in `App.tsx`, every view `React.lazy`, one `<Suspense>` per route; `/student` and `/faculty` redirect to their index views |
| The move | `StudentDashboard`'s sections and `FacultyDashboard`'s sections are lifted, **verbatim**, into their view files; both monoliths deleted |
| Theme | Font swap to Newsreader + Plus Jakarta Sans (files, ramp, heading weights); `MuiSlider` overrides §6 of `01-architecture.md` |

**Edits this phase forces, stated up front:**

- `quizWiring.test.tsx`, `triage.test.tsx`, `dashboard.live.test.tsx` render
  `<StudentDashboard/>`. They re-target to the view that owns the thing under
  test (`<QuizView/>`, `<LecturesView/>`). **Assertions do not change** — only
  the render target. This is an improvement: a test that renders one view cannot
  accidentally depend on another.
- `theme.e2e.spec.ts`'s `goto('/student')` becomes `/student/overview`.
- `shots.spec.ts` gets per-view targets.

**Gate:** `verify` green (490 tests, same assertions) · `test:e2e` green ·
first paint still within ~200 KB gz.

**Exit:** every previous feature reachable through the new nav, with the sidebar
rendering in both themes.

---

## P1 — Overview and Lectures

| View | Work | Reused |
|---|---|---|
| Overview | `SnapshotStrip` (the five bricks), in-flight card from `snapshot.in_flight`, quota card (`/usage`), next-actions row | `queryKeys.snapshot`, `queryKeys.usage` |
| Lectures | `LectureTable`, `UploadDialog` extracted from the inline card, `StalledTriage` (resumable / abandoned), duplicate guard | `lectureTriage.ts`, `uploadMedia`, `rerun`, `delete` |

**New tests:** `UploadDialog.test.tsx` (duplicate gate blocks until acked, ack
resets when the file changes, progress goes indeterminate → percent → done,
cancel settles).
**New e2e:** one smoke per view (renders, no console errors, no failed requests,
one meaningful assertion each).
**Gate:** green; the duplicate guard and triage still behave exactly as the unit
tests describe.

---

## P2 — Concept map and Lecture detail

| View | Work | Reused |
|---|---|---|
| Map | `DagView` + the control row (colour by, edge types, node limit, find, reset) + evidence panel + learner-order list | `DagView`, `graphImportance`, `nodeColors` — all unchanged |
| Lecture detail | **`CoverageTimeline`** (new), coverage/evidence table, processing states, `useLectureProgress` | `/lectures/{id}`, `/progress`, the Python `lecture_html` as the porting reference |

**The only genuinely new rendering in the whole revamp is `CoverageTimeline`.**
It gets its own test with golden values measured from the Python — the same
discipline `graphImportance` was ported under (four fidelity traps, all tested).

**Gate:** green; `dag.e2e.spec.ts` re-targeted to `/student/map` and passing;
timeline values match the Python on a seeded lecture.

---

## P3 — Quiz, Remediation, Clips

| View | Work | Note |
|---|---|---|
| Quiz | The existing flow, re-homed. **Not** the mock's five tabs — the mock's tabs exist to *review* the five states; the real view shows the state the quiz is actually in (start → queued → answering → result), one at a time, driven by `useQuizStore` | `quizWiring.test` proves the cap still travels |
| Remediation | Ordered plan, per-step clip, empty state | **`getRemediation` is wired here for the first time** — wrapped and keyed since the beginning, never called |
| Clips | Library + player, unplayable-row notice | `queryKeys.clips`, job-completion refresh already in place |

**e2e:** `video.e2e.spec.ts` (§10 gate) re-targets to `/student/clips`. The
invariant is untouched; only the path changes. One new smoke per view.

**Gate:** green — **including the video gate on its new route**, which is the
strongest evidence that the shell move did not disturb §1.

---

## P4 — Faculty views

| View | Work | Note |
|---|---|---|
| Analytics | `TelemetryStrip` (graph complexity, root concepts, critical gaps, divergence) + DAG + rebuild | Root concepts = **in-degree 0**, not `topological_order.length` — a real bug fixed earlier (`27fed3c`); the strip's test pins it |
| Heatmap | Block-bar rates with counts, empty state | `stats.heatmap` |
| Divergence | Displacement table + both sequences side by side | `stats.divergence`, `taught_order`, `learned_order` |
| Coverage | Faculty lecture timeline | `CoverageTimeline` reused from P2 — second consumer, first proof it was worth extracting |

**New tests:** `TelemetryStrip.test.ts` (root counting, gap counting).
**Gate:** green; three views share one `['stats', courseId]` key and a cold visit
fires **one** request instead of the current four.

---

## P5 — Jobs and System

| View | Work | Note |
|---|---|---|
| Jobs | Full table: kind, target, status, stage, progress, elapsed, cancel. States: running, ready, error, **orphaned**, stalled, expired | `useJobList` / `useJobCards` — reads the cache, never fetches (I2) |
| System | Quota detail, the three feed modes, failure surfaces (401, last-course guard, render failure, empty states) | `/usage`, `feedStatus()` |

**Gate:** green. The drawer and the view read the same cache — same numbers in
both, which is itself asserted.

---

## P6 — Review, a11y, and the copy pass

- **Screenshots** per view, dark and light, 1440 and 1280 — the eye check no test does.
- **Focus management** on route change (focus to the view `h1`, `document.title`
  updates), landmark audit, keyboard walk of every view.
- **Copy pass:** every empty state names the next action; every error quotes the
  backend `detail`; the three feed modes keep three distinct sentences.
- **Final gates** plus `npm run shots`, and any remaining open decision moved to
  decided or explicitly parked.

---

## Risk table

| Risk | Why it is real | Mitigation |
|---|---|---|
| The P0 move silently changes behaviour | 1 200 lines relocate at once | Verbatim move only; bug fixes in separate commits; the 490 existing assertions are the diff detector |
| Three test files couple to `StudentDashboard` | They render the monolith directly | Re-target to the owning view in P0; assertions untouched |
| Lazy routes flash empty during chunk load | Suspense fallback appears before the view | Per-route fallback shaped like the view's skeleton (not a spinner) |
| Route change breaks bookmarks or the e2e specs | Paths are asserted in five places | `/student` and `/faculty` redirect; the five `goto`s are listed phase by phase |
| Colour guard trips on new components | 13 new files writing `sx` | Every value through tokens or `theme/alpha.ts`; `CoverageTimeline` bands via `nodeColors` |
| Fragmentation — 13 views, 13 ways of doing the same thing | The classic multi-view failure | Shared extraction components (strip, table, dialog, timeline); nav and routes from one data table; one query-key table |
| New work in a shared tree | Another session has edited this repo mid-flight | Check `git status` before each phase; one writer at a time; commit per phase |
| Scope creep into palette or backend changes | Both are tempting mid-restructure | Explicitly out of scope (`README.md`, last section); decisions parked in `05-open-decisions.md` |

## Effort shape, honestly

P0 is the heaviest by far — it is a restructure, and restructures are where
things get lost. P1–P5 are each a focused extraction with the guards already in
place, which is why they are small. P6 is review, not construction.

The reason this is a phase plan rather than a single branch is that P0 alone
proves the structure, and P1–P5 can then proceed view by view, each one
shippable, with the app fully working at every boundary.
