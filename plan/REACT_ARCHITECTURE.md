# React Frontend — Architecture Decisions

> **Status: PROPOSED (2026-09-27)** — written *before* the first React line, so the
> scaffold is built on decided ground rather than a guessed contract. Companion to
> `plan/FRONTEND_REACT_ROADMAP.md` (stack §4, parity §6, non-goals §8) and
> `plan/ENGINE2_REBUILD_PLAN.md` (checkpoints C4–C9).
>
> **This is a decision document, not a task list.** Each section states a choice,
> the alternatives that were rejected, and why — with the thing in *this* repo
> that makes the choice necessary. Anything marked **OPEN** must be decided before
> the checkpoint that depends on it.

---

## 0. What the last engine cost us, and what must not be repeated

Three defects, all in the same layer, drove this rebuild:

| Defect | Root cause | Rule for the new engine |
|---|---|---|
| A background job re-rendered the whole page every 0.5–1.5 s, restarting every `<video>` | progress was **polled by re-render** | progress arrives by **push**; a value that changes must never be the reason a component re-renders |
| A long operation showed no progress and had to be waited out | work was a fire-and-forget task, not an observable resource | every long operation is a **durable job** the client can name and subscribe to |
| A finished job's follow-up (the clip list) flashed and vanished | the announcement lived inside the thing that re-rendered | **transient outcomes are recorded, then announced once by the page** |

None of these are Streamlit's fault, and none are fixed by a different framework.
C2–C4 fixed them in the current engine (`main`, `886b845`); this document is
about not throwing them away in the rewrite. Every decision below is checked
against those three rules.

---

## 1. Decision — the job feed is the single source of truth for progress

**Decision.** One `EventSource` subscription to `GET /jobs/stream` lives in a
single module (`src/lib/jobFeed.ts`) and writes every event into **one** React
Query cache entry. Components read job state through `useJobs()`; **no component
subscribes, polls, or holds its own copy.**

```
EventSource(/jobs/stream)  ──►  jobFeed (one per tab, ref-counted)
                                     │  on change
                                     ▼
                        queryClient.setQueryData(['jobs', courseId], rows)
                                     │
                    ┌────────────────┴────────────────┐
              useJobs() reads              useJobCards() derives
              (subscription data)          (per-lecture cards)
```

**Why not a subscription per component.** Each `useJob` hook owning an
`EventSource` would mean one connection per card, N connections for a course, and
— worse — a storm of re-renders at exactly the moment a job is running. This is
the "progress is the reason everything re-renders" trap in its React form.

**Why not React Query's own polling for progress.** It is the same defect as the
poll loop, at a different cadence: `refetchInterval` re-runs every query, and any
component watching a progress value re-renders on every tick for the length of the
job. Polling stays for things that genuinely are snapshots (course list, graph).

**Terminal states must be quiet.** A job reaching `ready | error | orphaned |
cancelled` is removed from the *live* view after one render, exactly as
`drain_ready` does in `frontend/panels/shell.py` today. A finished job does not
keep a card (or a `st.fragment` equivalent) alive.

**OPEN (before C6):** the keep-alive interval the stream uses
(`interval_s=1.0` today) versus the React re-render budget. One event per second
is fine; the risk is a burst of `setQueryData` calls when 12 jobs change at once.
Answer: batch with a microtask/`requestAnimationFrame` coalescer in `jobFeed`, so
one flush per frame regardless of event count. Decide with a measured trace, not
a guess.

---

## 2. Decision — server state in React Query, UI state in zustand, and the line between them

**Decision.**

| Lives in | What | Examples |
|---|---|---|
| **React Query** | anything the server owns | lectures, courses, concepts, graph, stats, snapshot, jobs, quiz questions |
| **zustand** | anything the *user* is in the middle of | the quiz draft, the student's selected options, the chosen lecture, panel-local UI toggles |

The rule: **if losing it loses information the server has, it is server state; if
losing it loses nothing but the user's typing, it is UI state.**

**Why this matters concretely.** Roadmap §6 requires: *start a lecture job
mid-quiz, finish the quiz — nothing regenerated or lost.* Under this split a job
completion invalidates the lecture/graph keys (cheap, refetched) and touches
nothing in the quiz draft, because the draft is not in the query cache. The
Streamlit version needed a dedicated `completed` session-state record and a
`drain_ready` to get this right; here it falls out of the split.

**Decision — the quiz draft holds the question ids it was served.** On submit it
echoes them back. The backend's quiz **version stamping** (roadmap precondition
4, still to do) is what makes a stale draft fail *gracefully* ("this quiz was
regenerated — start again") instead of 404-ing.

---

## 3. Decision — query keys are course-scoped, and invalidation mirrors one rule

**Decision.** Keys are `[resource, ...scope]` with the course id in scope:

```
['courses']                              GET /courses
['snapshot', courseId]                   GET /courses/{id}/snapshot
['graph', courseId]                      GET /courses/{id}/graph
['stats', courseId]                      GET /courses/{id}/stats
['lectures', courseId]                   GET /lectures?course_id=
['clips', lectureId]                     GET /lectures/{id}/clips
['remediation', studentId]               GET /students/{sid}/remediation
['jobs', courseId]                       fed by the SSE feed, never fetched on a timer
```

Mutations invalidate **by prefix**, through one helper — the direct analogue of
`frontend/client.py::invalidate_for_course`, which today clears the `/courses`
and `/lectures` namespaces after any course-affecting write:

```ts
// one rule, one place — a panel never hand-rolls an invalidation list
export const invalidateCourse = (qc: QueryClient, courseId: string) =>
  qc.invalidateQueries({ predicate: (q) =>
    (q.queryKey[0] === 'lectures' || q.queryKey[0] === 'snapshot' ||
     q.queryKey[0] === 'graph' || q.queryKey[0] === 'stats') &&
    (q.queryKey.length === 1 || q.queryKey[1] === courseId) })
```

**Why not "refetch everything on any mutation".** It is what a first draft does,
and it costs a full refetch of lists + graph + stats on every clip row write.

**No filesystem paths in the frontend.** `frontend/client.py::media_url` exists
only because payloads carry server-side paths. Contract v2 emits `url` directly;
the React client has no path→URL mapper at all, and a payload containing a
filesystem path is a **contract test failure**, not a runtime surprise.

---

## 4. Decision — the theme is a generated theme, from the tokens the Python side already pins

**Decision.** `frontend/theme.py` is the single source of colour truth. Contract
v2 or a small generated JSON exposes those tokens; MUI's theme is built from
them at boot; the DAG/timeline renderers take their colours from the same source
as `frontend/render.py` does now.

**Why.** `tests/test_theme.py` already pins properties that a JS theme cannot
easily re-derive: every text token ≥ 4.5:1 on every surface in both themes,
meaningful marks ≥ 3:1, and a node label legible on its fill for every rank and
every hashed identity hue. If the React app picks its own colours, the app has
two palettes and one of them is untested.

**Decision — the contrast logic is ported, not re-invented.** `readable_on()`
(better-measured ink) and the node ramp move to TypeScript as ~40 lines with the
same property tests in Vitest, asserting the same floors. The alternative —
"reuse MUI's accessible defaults" — does not cover a coloured node fill, which is
where the original 2.6:1 failure lived.

**OPEN (before C7):** light/dark switching. `[theme] base` is declared in
`.streamlit/config.toml`; the React app needs its own switch and a `prefers-color-scheme`
default. Decision needed on whether the *server* remains the source of theme
(every browser follows one setting) or each client follows the OS.

---

## 5. Decision — the DAG is a React component over the same payload, not a port of the SVG string

**Decision.** Render the graph with a React graph library over
`GET /courses/{id}/graph` (which already carries `source_method` and `evidence`
per edge). **Recommendation: `react-flow`** over vis-network.

Why react-flow:

- The backend emits nodes + edges + `topological_order`; react-flow's layered
  layout takes the ordering directly.
- Edge tooltips are a prop, not string HTML — which matters, because the pyvis
  path had to HTML-escape every attacker-influenced string by hand
  (`SECURITY_AUDIT.md` #24) and the inline SVG carries the same hazard.
- The "hover an edge for the professor's exact sentence" claim — the thing §4 of
  the Engine 2 plan calls the only genuinely hard-to-copy feature — is a
  `<Tooltip>` on a `<ReactFlow>` edge.
- vis-network would mean carrying a second graph engine, a second layout, and the
  CDN dependency that already failed once offline.

**What is kept from the current renderer:** the `graph_importance` significance
ranking (server-side truth today, ported with its own tests), the order/identity
colour modes, and the legend — the colour scheme must be *stated*, not assumed.

**OPEN (before C7):** whether to move `graph_importance` to the backend. Today
the Python side ranks and the client asks for "the top N". That is fine; duplicating
it in TypeScript would create two answers to "which concepts are significant".

---

## 6. Decision — one request path, no per-panel client

**Decision.** A single generated, typed client (from the contract v2 OpenAPI
snapshot) plus a thin hand-written wrapper per domain (`courses.ts`, `lectures.ts`,
`jobs.ts`, `quiz.ts`). Panels import those wrappers; **no panel calls `fetch`.**

Consequences, all of them the point:

- The `X-API-Key` header, the `{detail}` error extraction, the validated base URL
  and the 401 banner exist exactly once.
- A 401 renders as one banner, never as "no courses" — the roadmap's non-negotiable.
- Every call is typed from the contract, so drift fails CI (the OpenAPI snapshot
  test) instead of producing `undefined` at runtime.

**Auth.** Per roadmap §4, the app sits behind a reverse proxy and the `X-API-Key`
guard stays on the API. The React client reads the key from a build-time env var
for local dev only.

---

## 7. Decision — uploads use `XMLHttpRequest`, and report real progress

**Decision.** The two-step upload already exists and is already streaming
(`POST /lectures` → row, then `PUT /lectures/{id}/media` with a streaming body).
React consumes it unchanged, with `XMLHttpRequest` for `upload.onprogress` —
`fetch` still has no upload-progress event stream in any shipping browser.

**Why this matters more than it looks.** The PUT publishes live percentage to the
job row, and the card is fed by the same SSE feed as everything else — so the
transfer bar and the transcription bar are the *same* card, and a reload
re-attaches. The `job_id` the PUT returns is what makes that possible; that is
why every queueing endpoint now returns one.

**Cancel** is the `cancel` event on the request, surfaced as a button that
disables itself (the C0 rule: no double-fired work).

---

## 8. Decision — repository layout and where each piece lives

```
frontend-react/
  src/
    api/            generated client + one wrapper per domain + the error envelope
    features/       student/ faculty/ — components + hooks, no fetch calls
    lib/            jobFeed.ts (SSE), mediaUrl.ts, contrast.ts, theme.ts
    store/          zustand slices (quiz draft, selection)
    test/           Vitest setup + the ported contrast tests
  e2e/              Playwright
```

Rules that keep it honest:

- `features/**` may not import `fetch` or the generated client directly — the
  wrappers are the boundary. Lint-enforced, not a convention.
- `lib/jobFeed.ts` is the only file that knows `/jobs/stream` exists.
- No component holds a job's progress in local state. If a component needs to
  know a job finished, it reads `useJobs()`.

---

## 9. What is deliberately *not* decided here

- **The component library beyond MUI's core.** Radix/headless vs MUI everywhere;
  decided at C5 with real screens in front of us, not on paper.
- **Charting.** The heatmap and divergence are small; a charting library is
  justified only if the hand-rolled version is unreadable first.
- **Anything about the ML pipeline.** Non-goal (roadmap §8). The React app is a
  client of the API; it never imports `backend/` — the same rule the Streamlit
  frontend already keeps.

---

## 10. Order of work, and what blocks what

```
C4  contract v2  ──────────────► C5  scaffold (typed client needs the contract;
  CORS · URLs not paths ·         Vite is browser-blocked without CORS)
  OpenAPI snapshot test
                                   C6  student upload + live progress
                                       (needs §1 and §3 settled)
                                   C7  faculty DAG + analytics (needs §5, §4)
                                   C8  quiz + remediation (needs §2)
                                   C9  Playwright E2E, then flip
```

**Gate per checkpoint (roadmap §6 parity checklist) plus:** a Playwright test
that a job running for 30 s does **not** restart a playing `<video>`, and a
Vitest port of the contrast floors from `tests/test_theme.py`. If either fails,
the engine has reintroduced the defect this whole exercise exists to remove.

---

## 11. OPEN decisions, with the checkpoint that needs them

| # | Question | Needed by | Why it is not answered here |
|---|---|---|---|
| 1 | Event coalescing budget for job bursts (frame vs microtask vs raw) | C6 | needs a measured trace on real job fan-out |
| 2 | Theme source of truth: server setting vs `prefers-color-scheme` | C7 | a product call, not a technical one |
| 3 | `graph_importance`: keep server-side, or port? | C7 | duplicating it is a real risk; the answer depends on how the graph endpoint is shaped |
| 4 | MUI vs a lighter kit, decided with screens rather than a table | C5 | paper comparison of UI kits is not evidence |
| 5 | Playwright in CI or pre-merge only | C9 | depends on whether the team has CI at all (`plan/TEAM.md` flags this) |
