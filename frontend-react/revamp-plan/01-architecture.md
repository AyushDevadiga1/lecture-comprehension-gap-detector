# 01 · Architecture — routes, shell, layout, state

## 1. Route model

Every mock view becomes a real route. That buys deep links, the back button,
per-route code splitting, and a way to test a view without clicking through the
app.

```
/                          → <Navigate to="/student/overview" replace />
/student                   → redirect to /student/overview
/student/overview          snapshot · in-flight · quota · next actions
/student/lectures          table · upload · triage · duplicate guard
/student/map               DAG · controls · evidence · study sequence
/student/lecture/:id?      coverage timeline · evidence table · processing states
/student/quiz              start · queued · answering · result · error states
/student/remediation       ordered plan · clip playback
/student/clips?:lecture=   library · player
/faculty                   → redirect to /faculty/analytics
/faculty/analytics         telemetry strip · faculty DAG · rebuild
/faculty/heatmap           confusion rates
/faculty/divergence        taught vs learned · both sequences
/faculty/coverage          faculty lecture timeline
/jobs                      full job table (drawer still exists)
/system                    quota detail · feed modes · failure surfaces
*                          NotFound
```

**Legacy paths keep working.** `/student` and `/faculty` already exist in the
wild (bookmarks, the e2e specs, `NotFound`'s button), so both redirect to their
index view rather than 404. That single decision is what keeps `app.e2e.spec.ts`
passing through P0.

**Route params vs query params.** A lecture or clip identity is *content* → path
or query (`/student/lecture/3`, `/student/clips?lecture=1`), because it is
shareable and should survive a reload. A transient canvas selection (which DAG
node is focused) stays in component state — nobody bookmarks a node.

## 2. Shell

`AppLayout` becomes `AppShell`. One structural change: a sidebar becomes the
primary navigation, and the navbar's role tabs go away (the sidebar already
carries both groups).

```
AppShell
├── Sidebar            brand · course select + delete · nav groups · footer (feed, quota, theme)
├── (main column)
│   ├── AuthBanner     unchanged, still above everything
│   ├── Topbar         breadcrumb · student id · feed chip · jobs button
│   └── <Outlet/>      the 13 lazy views
├── JobDrawer          unchanged
└── JobCompletionHost  unchanged
```

`AppShell` keeps the two things it already owns and must keep owning:
`useJobFeedConnection(selectedCourseId)` (one connection, ref-counted) and
**not reading job state itself** (§1). The sidebar's job count and the topbar's
feed chip read the cache the way `Navbar` does today — through `useJobFeed`'s
selectors, which are `useSyncExternalStore` over the query cache.

Nav groups (from the mock): **Student** (7) · **Faculty** (4) · **System** (2).
Grouping is data, not markup: one `NAV` array in `Sidebar.tsx` with
`{ group, label, to, badge? }`, so adding a view is one line and the sidebar and
the route table cannot drift apart in wording.

## 3. File layout

Minimal churn: everything that works stays where it is. New code goes in the
same shapes the repo already uses.

```
src/
  App.tsx                     route table, lazy imports, Suspense per route
  AppProviders.tsx            unchanged
  main.tsx                    unchanged
  api/                        unchanged
  lib/                        unchanged (one addition: useLectureProgress)
  store/                      unchanged
  theme/                      + MuiSlider overrides in muiTheme.ts
  components/
    layout/
      AppShell.tsx            was AppLayout.tsx
      Sidebar.tsx             new
      Navbar.tsx              slimmed: course select moves in, brand stays
    common/                   existing + CoverageTimeline.tsx (new)
    graph/DagView.tsx         unchanged
    media/VideoPlayer.tsx     unchanged
    student/
      UploadDialog.tsx        extracted from StudentDashboard's inline card
      SnapshotStrip.tsx       extracted (5 stat bricks)
      StalledTriage.tsx       extracted (resumable / abandoned)
      LectureTable.tsx        extracted
    faculty/
      TelemetryStrip.tsx      extracted + extended (root concepts, gaps)
      HeatmapTable.tsx        extracted
      DivergenceTable.tsx     extracted
  features/
    student/views/
      OverviewView.tsx  LecturesView.tsx  MapView.tsx  LectureDetailView.tsx
      QuizView.tsx  RemediationView.tsx  ClipsView.tsx
    faculty/views/
      AnalyticsView.tsx  HeatmapView.tsx  DivergenceView.tsx  CoverageView.tsx
    system/views/
      JobsView.tsx  SystemView.tsx
```

`StudentDashboard.tsx` and `FacultyDashboard.tsx` are **deleted** in the phase
that extracts their last section — not kept as thin wrappers. A wrapper is how a
codebase ends up with two homes for one thing.

## 4. State tiers — the rule that decides where anything lives

Four tiers, in this order of preference. The point is that a future contributor
does not have to guess.

| Tier | Home | For | Examples |
|---|---|---|---|
| 1 · Server | React Query cache | Anything the backend owns | snapshot, graph, stats, lectures, clips, jobs, usage |
| 2 · Session | zustand (`useAppStore`, `useQuizStore`, `useCompletionStore`) | Preferences and in-progress work that outlives a view | course, student id, theme base, drawer open, quiz draft |
| 3 · URL | route params / query | Content identity and shareable position | lecture id, clip id, active view |
| 4 · Local | `useState` | Ephemeral view detail | dialog open, selected concept, search text |

**The rule:** server-derived ⇒ tier 1, never copied into tier 2. A course
selected in `useAppStore` is an *identifier*, not data; the data stays in the
cache under `['snapshot', courseId]`. This is the discipline the current code
already follows — the plan just makes it explicit so the 13 views do not each
invent their own copy of it.

## 5. Component inventory

### Reused unchanged (the expensive parts)

`api/client.ts` (single fetch path, `{detail}` envelope, XHR upload progress),
all of `lib/`, all three stores, `theme/*`, `DagView`, `VideoPlayer`,
`ErrorBoundary`, `ErrorAlert`, `AuthBanner`, `JobDrawer`, `JobCompletionHost`,
`StatusBadge`, `LoadingScreen`, `Rise`, `SectionIcon`, `NotFound`.

### Extracted from the monoliths (moves, not rewrites)

`UploadDialog`, `SnapshotStrip`, `StalledTriage`, `LectureTable`,
`TelemetryStrip`, `HeatmapTable`, `DivergenceTable`. These are already written
and tested; the work is lifting them into files with explicit props, not
re-authoring them.

### New work (the only genuinely new rendering)

| Component | Why it is new | Source of truth |
|---|---|---|
| `Sidebar.tsx` | No sidebar exists | the mock's nav groups |
| `CoverageTimeline.tsx` | Never built in React | port of `frontend/render.py::lecture_html` |
| `JobsView.tsx` | Jobs only exist in the drawer | `useJobList` + `useJobCards` |
| `SystemView.tsx` | Quota is not rendered anywhere | `/usage` + feed mode |
| `RemediationView.tsx` | `getRemediation` is wrapped but never called | `lib/quiz.ts` submission shape |
| `LectureDetailView.tsx` | No per-lecture page today | `/lectures/{id}` + `/progress` |
| `MuiSlider` overrides | Sliders are unstyled browser defaults | tokens |

### Deliberately not new

No component library, no charting library, no animation library beyond the
`framer-motion` already installed, no icon package beyond `@mui/icons-material`.
DAG stays reactflow. Timeline stays hand-rolled SVG — it is 200 lines of maths
and it already exists in Python to port against.

## 6. The slider, concretely

The user's note: sliders must match the theme, not the browser default.

One override in `theme/muiTheme.ts`, so every slider in the app is themed at
once — the node-limit slider (Map), the volume and scrub of `VideoPlayer`
(already custom, keep), and any future filter:

```
MuiSlider:
  rail        → var(--lgc-track)
  track       → var(--lgc-info)
  thumb       → var(--lgc-info) fill, 2px var(--lgc-page) ring, 14px
  hover ring  → tint('info', 18)          (matches MuiTextField's focus ring)
  valueLabel  → surface bg, border, mono font, 11px
  marks       → 2px ticks in var(--lgc-track)
```

Same tokens as everything else, so the sliders survive both base themes and the
colour guards without a special case. The `range` inputs in the mocks are
placeholders; the real ones are this.

## 7. What "lightweight" means here, numerically

- **First paint:** shell + overview + providers + MUI, ≤ ~200 KB gz (today's
  baseline is ~197 KB gz across `index` + `vendor-*`; the sidebar adds ~2 KB).
- **Per-view chunks:** every view except Map is < 16 KB gz. Map carries reactflow
  at ~52 KB gz and stays lazy — it already is.
- **Queries:** a view owns its query and mounts it on entry; leaving a view
  unmounts it. Fewer concurrent requests than today, because today `/stats` and
  `/graph` both fire the moment `/faculty` opens.
- **Memory:** the job snapshot is one array in one cache key, as now. No view
  keeps a second copy.
