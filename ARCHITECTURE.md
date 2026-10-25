# LecGap — Architecture Overview

> One-page context file. Designed to onboard a new agent or developer in
> under 2 minutes without reading the 132 KB WORKLOG.

---

## What the system does

LecGap automatically builds a prerequisite concept graph from lecture
recordings and uses it to:

1. **Personalise remediation for students** — wrong quiz answers trace backwards
   through the graph to produce an ordered study plan with video clips.
2. **Show instructors where students got confused** — heatmap of failure rates
   per concept, and taught-vs-learned order divergence.

---

## Repository layout

```
lecture-comprehension-gap-detector/
├── backend/              FastAPI backend (Python)
│   ├── api/              HTTP endpoints (routes, schemas)
│   ├── pipeline/         Processing stages (transcription → concepts → graph → clips)
│   ├── db/               SQLite database layer
│   └── worker/           Background job runner
├── frontend-react/       React + Vite + MUI frontend (THIS is the active frontend)
│   └── src/
│       ├── api/          Typed HTTP client wrappers
│       ├── features/     Page-level components (student/, faculty/, system/)
│       ├── components/   Shared components (graph/DagView, common/*)
│       ├── store/        Zustand stores (useAppStore, useQuizStore)
│       ├── lib/          Pure helpers (queryKeys, graphImportance, usageLine, …)
│       └── theme/        MUI theme + token system
├── frontend/             ⚠️ LEGACY Streamlit frontend — to be retired
├── data/                 Raw lecture files (gitignored)
├── notebooks/            Kaggle fine-tuning experiments
├── scripts/              Utility scripts (evaluate_classifier, export openapi, …)
├── tests/                Backend pytest suite
└── plan/                 Design documents (ROADMAP, EVALUATION, LIMITATIONS, …)
```

---

## Backend pipeline stages

| Stage | File | What it does |
|---|---|---|
| 1 — Transcription | `pipeline/transcribe.py` | Whisper (local or Groq) → timestamped segments in SQLite |
| 2 — Concept extraction | `pipeline/passages.py` | One LLM pass → passages (title/kind/summary/span) + spoken prerequisite links |
| 3 — Prerequisite classification | `pipeline/classify_prerequisites.py` | Frozen MiniLM encoder + logistic head (F1 0.569 on LectureBank) |
| 4 — Graph construction | `pipeline/build_graph.py` | Deduplication → DAG with cycle resolution → topological sort |
| 5 — Clip segmentation | `pipeline/segment_clips.py` | ffmpeg cuts per concept teach-span |
| 6 — Quiz generation | `pipeline/quiz.py` | LLM generates MCQ per concept |
| 7 — Refinement loop | `pipeline/refine.py` | Quiz signals update edge confidence |

All stages run as **background jobs** — the frontend polls a job feed via SSE
(`GET /jobs/feed`). No endpoint blocks waiting for a pipeline result.

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/courses` | List courses |
| `GET` | `/courses/{id}/snapshot` | Dashboard numbers (lectures, concepts, graph, clips, quiz) |
| `GET` | `/courses/{id}/graph` | Prerequisite DAG (nodes, edges, topological order, evidence) |
| `GET` | `/courses/{id}/stats` | Faculty stats (heatmap, divergence, taught/learned order) |
| `POST` | `/courses/{id}/graph` | Queue a graph build job |
| `GET` | `/lectures` | List lectures for a course |
| `GET` | `/lectures/{id}` | Lecture detail (segments + concepts) |
| `POST` | `/lectures/{id}/concepts` | Queue concept extraction |
| `POST` | `/lectures/{id}/clips` | Queue clip cutting |
| `POST` | `/quizzes/jobs` | Queue async quiz generation |
| `GET` | `/quizzes` | Fetch current quiz for student |
| `POST` | `/quizzes/submit` | Submit answers → score + remediation plan |
| `GET` | `/students/{id}/remediation` | Fetch last remediation plan (survives reload) |
| `GET` | `/jobs/feed` | SSE stream of job updates |
| `GET` | `/usage` | API quota counters |

The OpenAPI schema lives at `GET /openapi.json` when the backend is running.
Run `scripts/export_openapi.py` to snapshot it to `scripts/openapi.json`.

---

## Frontend routing

```
/student/overview     OverviewView      — hero + pipeline stepper + snapshot
/student/lectures     LecturesView      — upload, extract, cut clips, triage
/student/map          MapView           — prerequisite DAG (DagView)
/student/lecture      LectureDetailView — per-lecture concepts + timeline
/student/quiz         QuizView          — generate → answer → submit
/student/remediation  RemediationView   — ordered study plan + clip player + Show on map
/student/clips        ClipsView         — all clips for the course
/faculty/analytics    AnalyticsView     — prerequisite edge table + rebuild
/faculty/heatmap      HeatmapView       — wrong-answer rate per concept
/faculty/divergence   DivergenceView    — taught vs learned order
/faculty/coverage     CoverageView      — coverage per lecture
/jobs                 JobsView          — live job registry
/system               SystemView        — API quota + feed connectivity
```

---

## State management

| Store | What it owns |
|---|---|
| `useAppStore` (Zustand) | `selectedCourseId`, `studentId` — persisted to localStorage |
| `useQuizStore` (Zustand) | Active quiz draft, selected answers, submit result |
| React Query cache | All server data; keyed by `queryKeys.*` (centralised in `lib/queryKeys.ts`) |

React Query cache sharing: `['graph', courseId]` is shared between MapView
and AnalyticsView — navigating between them fetches once.

---

## Active branch

`engine2/scaffold` is the active branch (~100 commits ahead of `main`).
`main` has 3 doc-only commits that `engine2/scaffold` doesn't have yet.

**Do not merge yet.** Plan:
1. Cherry-pick the 3 main commits into `engine2/scaffold`.
2. Delete `frontend/` (Streamlit) from the repo.
3. Merge `engine2/scaffold` → `main` with `--no-ff`.

---

## Known open issues (as of Oct 2026)

See [`frontend-react/EVALUATION_AND_PLAN.md`](frontend-react/EVALUATION_AND_PLAN.md) for the
full priority matrix. Top items:

- Graph node type lacks `lecture_id` — "colour by lecture source" and scatter
  plot cluster view both require a backend schema addition.
- `api/types.ts` is hand-maintained — should be generated from `/openapi.json`
  via `openapi-typescript`.
- Faculty dashboard visualisations (heatmap, divergence) are functional but
  need richer chart types in Phase 2.
