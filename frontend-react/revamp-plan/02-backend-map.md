# 02 · Backend map — every endpoint, its view, and its states

Every call goes through `api/client.ts` (the single fetch path, the `{detail}`
envelope, the 401 interception). No view calls `fetch`. Nothing below adds a
backend endpoint — one is wired for the first time and one gains a home.

## 1. Transport rules that already hold (do not regress)

| Rule | Where it lives | Why it must survive the restructure |
|---|---|---|
| One request path | `api/client.ts` | The API key header and the `{detail}` extraction exist once |
| Upload is XHR, not fetch | `client.ts::putStream` | `fetch` has no `upload.onprogress` |
| SSE uses `fetch` + `streamHeaders()` | `lib/jobFeed.ts` | `EventSource` cannot send the API key header |
| Errors are typed and readable | `LecGapApiError`, `errorMessage` | Views render sentences, never tracebacks |
| Query keys are one table | `lib/queryKeys.ts` | Views cannot invent key shapes |
| Invalidation is one helper | `invalidateCourse()` | Mutations cannot each forget a namespace |

## 2. Endpoint → view → mechanism

| Endpoint (wrapper) | View(s) that call it | Mechanism | Notes |
|---|---|---|---|
| `GET /courses` (`courses.list`) | Sidebar (picker), every view's `enabled` gate | `queryKeys.courses()`, 10 s stale | The picker is always mounted, so this is the one always-on read |
| `GET /courses/{id}/snapshot` | **Overview** (strip + in-flight) | `queryKeys.snapshot(course)`, 5 s | Also seeds nothing else — the mock's "In flight" card reads `in_flight` straight from it |
| `GET /courses/{id}/graph` | **Map**, **Faculty Analytics** | `queryKeys.graph(course)`, 300 s | Shared key: opening both views fetches once |
| `POST /courses/{id}/graph` | Map, Analytics (Rebuild button) | mutation → `invalidateCourse` | `lecture_id` travels as a query param, not a body — the backend declares it that way |
| `GET /courses/{id}/stats` | **Heatmap**, **Divergence**, **Analytics** | `queryKeys.stats(course)`, 300 s | One key, three views; no view refetches what another already has |
| `DELETE /courses/{id}` | Sidebar (delete dialog) | mutation → `invalidateQueries()` + select next course | Selection moves **before** invalidation, so no query fires once against a dead id |
| `GET /lectures?course_id=` | **Lectures**, **Clips** (picker), **Lecture detail** (picker) | `queryKeys.lectures(course)`, 10 s | The lecture list is the shared spine of three views |
| `GET /lectures/{id}` | **Lecture detail** | `queryKeys.lectures(course)` slice, or a dedicated `['lecture', id]` | See §4 — this is a decision, not a default |
| `GET /lectures/{id}/progress` | **Lecture detail** (transcribing state) | new `lib/useLectureProgress.ts`, polled only while `status === 'transcribing'` | **First real home.** Today the endpoint has no caller |
| `GET /lectures/{id}/clips` | **Clips**, **Remediation** (per step) | `queryKeys.clips(lectureId)`, 10 s | Not course-scoped, so `invalidateCourse` does not clear it — a finished clip job invalidates it by key (already in `useJobFeed`) |
| `POST /lectures` (`create`) | **Lectures** (upload dialog) | mutation | Step 1 of two-step upload |
| `PUT /lectures/{id}/media` (`uploadMedia`) | Lectures (upload dialog) | XHR, progress + cancel | Step 2; enqueues transcription and returns its `job_id` |
| `POST /lectures/{id}/concepts` | Lectures (row action) | mutation → `invalidateCourse` | Also reachable from Overview's "next actions" |
| `POST /lectures/{id}/clips` | Lectures, Clips | mutation → `invalidateCourse` | Job completion refreshes the clip list |
| `POST /lectures/{id}/rerun` | Lectures (resumable triage) | mutation → `invalidateCourse` | First real home — wrapped since the beginning, never called until now |
| `DELETE /lectures/{id}` | Lectures (row remove, bulk empty-row delete) | mutation → `invalidateCourse` | Busy-guarded while a job runs |
| `POST /quizzes/jobs` | **Quiz** | mutation; returns `job_id` | Capped; the cap travels in the body (§ the quiz-cap bug) |
| `GET /quizzes?course_id=&student_id=` | Quiz | mutation on demand, or `queryKeys.remediation`-style key | Doubles as "resume the quiz I was taking" |
| `POST /quizzes/submit` | Quiz | mutation, one-shot | Ids clear on submit so stale answers cannot re-send |
| `GET /students/{id}/remediation` | **Remediation** | `queryKeys.remediation(studentId)` — **wire it** | Wrapped and keyed today, called by nothing |
| `GET /jobs` | Jobs view, feed fallback | read by `lib/jobFeed` polling path only | Views never call this directly; they read the cache |
| `GET /jobs/stream` | shell (one connection) | `lib/jobFeed` singleton, `useJobFeedConnection` in `AppShell` | **Never** subscribed to by a component that renders `<Outlet/>` (§1) |
| `POST /jobs/{id}/cancel` | Jobs view, JobDrawer | mutation | Failure reports inline, keeps the card |
| `GET /media/clips/{id}/{file}` | Clips, Remediation, Lesson detail | `<video src>` | Percent-encoded filename; byte-range capable; never a filesystem path |
| `GET /usage` | **Overview**, **System** | `queryKeys.usage()`, 30 s | First real home — never called in React until now |
| `GET /health` | System | link/status only | No query; the auth banner links to it |

## 3. Invalidation map (the one rule, applied)

```
any mutation that can change course data
        → invalidateCourse(queryClient, courseId)
              ├── ['courses']
              ├── ['snapshot', courseId]
              ├── ['graph', courseId]
              ├── ['stats', courseId]
              └── ['lectures', courseId]   (+ unscoped variants)

clip job finishes (useJobFeed completion hook)
        → ['clips', lectureId]

course deleted
        → select the next course FIRST, then queryClient.invalidateQueries()
```

`clips` and `remediation` are deliberately outside `invalidateCourse` — they are
keyed by lecture and student, not course. That is already true and the plan does
not change it.

## 4. Two decisions this map forces (settled here)

**a) Per-lecture detail gets its own key.** `GET /lectures/{id}` returns
transcript segments and concepts — a much bigger payload than the list. Adding
`queryKeys.lecture(id)` (`['lecture', id]`, 300 s) keeps a 500-row list from
being re-fetched to read one lecture, and keeps the two shapes apart. It joins
`COURSE_SCOPED` predicates as an *unscoped-by-course* variant cleared by
`invalidateCourse` through a `lecture` rule — see `lib/queryKeys.ts` when
implementing; the predicate gains one case, nothing else moves.

**b) `progress` is polled, not streamed.** The SSE job feed already carries
stage and percentage for the *course*, so the Lecture-detail progress card reads
the job cache when a job exists for that lecture and falls back to
`/progress` polling only for a transcribing lecture with no visible job (a tab
opened mid-transcription). That is the same reasoning as the feed's
polling fallback and it keeps one connection, not two.

## 5. Request budget per view (mount → requests)

| View | Fires on mount | Shared with |
|---|---|---|
| Overview | `/courses/{id}/snapshot`, `/usage` | courses (sidebar), jobs cache |
| Lectures | `/lectures` | Overview, Clips, Lecture detail |
| Map | `/courses/{id}/graph` | Faculty Analytics |
| Lecture detail | `/lectures/{id}` (+ `/progress` only while transcribing) | — |
| Quiz | none until the button (generation is explicit) | — |
| Remediation | `/students/{id}/remediation` | — |
| Clips | `/lectures/{id}/clips` | Remediation (per step) |
| Faculty Analytics | `/courses/{id}/graph`, `/courses/{id}/stats` | Map, Heatmap |
| Heatmap | `/courses/{id}/stats` | Analytics, Divergence |
| Divergence | `/courses/{id}/stats` | Analytics, Heatmap |
| Faculty Coverage | `/lectures` (+ `/lectures/{id}`) | Lectures, Lecture detail |
| Jobs | none — reads the feed cache | shell |
| System | `/usage` | Overview |

**Total on a cold visit to one view: two requests at most.** Today, opening
`/faculty` fires snapshot + graph + stats + lectures before you have read
anything. This is where the "lightweight" claim is actually earned — not from a
smaller bundle, from not fetching what the screen in front of you does not show.

## 6. What happens when things fail (per view, not global)

| Failure | Surface | Copy |
|---|---|---|
| 401 anywhere | `AuthBanner` (shell) with Retry | states the key is missing; Retry clears and refetches |
| Course-scoped 404 (course deleted elsewhere) | Sidebar re-selects the first available course | silent recover, not an error |
| `graph` 404 (no graph yet) | Map / Analytics | "no graph yet — extract concepts first" + the button |
| `stats` empty | Heatmap / Divergence | "no graded answers yet" — not an empty chart |
| `clips` 404 on play | Clips | "clip file missing on the server — re-cut" |
| `remediation` 404 | Remediation | "take the quiz first" |
| Render throw in a view | `ErrorBoundary` around `<Outlet/>` | names the view, offers Retry, keeps the sidebar |
| Feed `unavailable` | Topbar chip + Jobs view | "will not update until it reconnects" — distinct from "polling" |
