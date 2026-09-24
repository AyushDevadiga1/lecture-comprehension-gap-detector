# Frontend Roadmap — React engine (Engine 2, documented now, executed later)

> **Status: AGREED (2026-09-24)** — direction signed off: stay on Streamlit
> *now* (`plan/FRONTEND_ARCHITECTURE.md`), keep React as a documented leaf-replacement
> over the SAME backend contract (`plan/FRONTEND_API_CONTRACT.md`). This doc is the
> go/no-go criteria, hard preconditions, stack, and migration path — it is a plan,
> not a commitment to build immediately.

## 1. Why this engine exists

The decision log (`plan/DECISIONS.md`, 2026-08) always left the frontend open:
"FastAPI backend + Streamlit frontend … explicitly not treated as final — Ayush
flagged he may want to upgrade the frontend (e.g. to a dedicated framework)". The
2026-09-24 frontend audit confirmed the Streamlit engine has real structural pain
(per-rerun UI-state loss, per-session-only job visibility, weak cross-user
transparency). A React engine is the honest, production-grade way to fix that **if
and when** the team can afford it.

## 2. Go / no-go trigger

The roadmap is explicitly NOT the default next step. Trigger condition (one of):

1. **Phases 3 + 7 substance is locked** (prerequisite classifier evaluability +
   synthetic-student refinement validation — the project's actual technical
   claim, per `plan/ROADMAP.md` cut-lines), **and** there is dev time remaining
   before the demo/viva, **or**
2. **The frontend becomes the showcase** — the demo surface (live DAG, heatmap,
   remediation playback) is judged worth more than additional pipeline time.

Honoring `plan/TEAM.md` (solo-execution risk): if a single person owns this,
treat the React build as a 3–6 week solo detour and re-run the trigger against
the calendar, not the wish list.

## 3. Hard preconditions (make-or-break)

A React frontend must not inherit today's backend limits. These are **backend
changes**, independent of framework, and are the real reason the Streamlit engine
already fixes the media endpoint and locks the contract:

1. **Locked + versioned API contract** — `plan/FRONTEND_API_CONTRACT.md` v1 frozen;
   any breaking change bumps the version and gives the frontend a migration
   window. This includes: JSON shapes, the `{detail}` error envelope, media URLs,
   CORS configuration, and the auth header scheme.
2. **Media-serving endpoint** (`GET /media/clips/{lecture_id}/{filename}`) landed
   in Engine-1 M3 — React `<video>` consumes the same URL. No filesystem paths
   anywhere in payloads; contract v2 may emit URLs directly instead of mapping at
   the frontend edge.
3. **Backend job registry** — replace fire-and-forget `BackgroundTasks` with
   real jobs: `POST /jobs` → `job_id`, persisted progress (survives restart),
   status state machine (`queued → running → ready | error | orphaned`), terminal
   `updated_at` heartbeats, and a **per-course advisory lock** so two users can't
   interleave extraction/clips/graph on one course (progress published by
   `job_id`, not by `lecture_id`). Without this, React has the exact same
   progress-transparency ceiling as Streamlit today.
4. **Quiz idempotency / versioned question ids** — `POST /quizzes` must stop
   delete-and-recreate churn; students' in-flight quizzes must survive another
   student generating a quiz for the same course. Requires a QuestionItem
   version stamp the frontend echoes back on submit.

## 4. Chosen stack (realistic for this team on Windows + conda)

| Concern | Choice | Why |
|---|---|---|
| Build/tooling | Vite + React 18 + TypeScript | Fast, standard, minimal config |
| Data fetching + cache | React Query (TanStack) | TTL + on-mutation invalidate mirroring Engine-1 `client.CacheStore` semantics ("cache before data-layer" rule from the 2026 dashboard research) |
| Routing | react-router (`/student`, `/faculty`) | Role-separated dashboards |
| UI kit | MUI (or light Tailwind) | Tables/forms/steppers cheap to ship |
| DAG | vis-network (reuse pyvis graph JSON) or react-flow | Interactive, tooltips, drag |
| Charts | ApexCharts/ECharts | Heatmap + divergence, animated |
| Video | native `<video>` → `/media/clips/...` | Range-capable backend already there |
| State (beyond server state) | zustand | Tiny, per-session UI state (quiz draft, selections) |
| Tests | Vitest + React Testing Library (unit), Playwright (E2E dashboards) | Mirrors Engine-1 L1/L2/L3 split |

**Auth:** minimal and at the edge — put the app behind a reverse proxy (Caddy /
nginx / Cloudflare Access) rather than hand-rolled RBAC (consistent with the
researched guidance for Python dashboards); keep `X-API-Key` backend guard intact
for the API itself.

## 5. Serving + migration path

1. FastAPI (or nginx) serves the built SPA from `frontend-react/dist`; the API
   stays under `/api/*` (proxy prefix, CORS for dev).
2. **Never a big-bang cutover.** `student_app.py` / `faculty_app.py` keep
   running behind their current URLs for the whole build.
3. Per-dashboard **parity checklist** (below) is the acceptance gate; only when a
   dashboard passes it does the proxy default path flip to the React build.
4. After both flip, the Streamlit entrypoints + `frontend/app.py`-era code are
   retired (kept in history only).

## 6. Parity checklist (each dashboard must beat Engine-1 behavior, not just match)

**Student:**
- [ ] Upload + progress card (multi-job list, refresh attaches to existing jobs)
- [ ] Quiz survives navigation and background job polling (never re-generated invisibly)
- [ ] Submit → score/feedback/remediation; stale-version → friendly regenerate
- [ ] Remediation `<video>` plays clips in learner order (Range streaming)
- [ ] Course select/refresh/delete with correct cache invalidation

**Faculty:**
- [ ] Heatmap + divergence persists across navigation
- [ ] Interactive DAG (draggable, tooltips with evidence, learner order)
- [ ] Per-lecture timeline + coverage; `None` indices render as `—`
- [ ] Multi-user transparency: active jobs visible to all sessions

**Global:** auth boundary enforced; errors always the `{detail}` envelope;
401 = one banner, never a dead "no courses" state; no dependency on Streamlit
runtime.

## 7. Showcase framing (the "wow" surface)

Engine 2 is where the system's *power* becomes demonstrable in a presentation:

- the student path from a lecture upload → concept DAG → quiz → wrong-answer →
  remediation in *graph order*, clips playing;
- the faculty view of **taught vs. learned divergence** as a side-by-side
  animated re-side, heatmap re-sorted live;
- the evidence-loaded DAG (hover an edge, read the exact sentence the professor
  said — `source_method: transcript @0.90`).

The cache/state/contract work in Engine 1 is the prerequisite that makes this a
*sprint of UI work* rather than a re-architecture — which is the entire point of
building it now.

## 8. Non-goals (locked)

- No SSR/Next.js, no microfrontends.
- No bidirectional state sync with the Python apps after cutover.
- No feature expansion beyond Engine-1 parity + the showcase framing above.
- No retraining/test-suite rewrites of the core ML evaluation.

## 9. Milestones (when triggered)

| # | Deliverable | Gate |
|---|---|---|
| R1 | Preconditions 1–4 landed on backend; contract v2 (URLs) drafted | API tests green |
| R2 | Vite+TS scaffold, routing, auth proxy, serving path | `/student` + `/faculty` render |
| R3 | Student dashboard full parity (React Query cache + quiz state) | Parity checklist §6 |
| R4 | Faculty dashboard full parity (DAG, heatmap, divergence, timeline) | Parity checklist §6 |
| R5 | Playwright E2E for both dashboards + CI | E2E green |
| R6 | Cutover: proxy flips; Streamlit retired | Parity + manual demo pass |