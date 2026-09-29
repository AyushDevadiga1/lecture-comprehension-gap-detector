# DIAGNOSED 2026-09-29 — the wedge, with the evidence

> # ⛔ REFUTED 2026-09-29 (later the same day). F1 and F2 below fix nothing.
>
> **The central claim of this document is wrong.** There was no SQLite write
> lock, no deadlock, and no wedged throttle. The three `extract` jobs **crashed
> instantly** and were then left `running` forever, which looks identical to
> "blocked" from outside.
>
> ## What actually happened
>
> The real traceback, from a uvicorn log, was:
>
> ```
> sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
> [SQL: DELETE FROM concepts WHERE concepts.lecture_id = ?]
> [parameters: (1,)]
>   backend/api/jobs/extract.py:88
> ```
>
> `clips.concept_id` is a real foreign key into `concepts.id` and `db.py:61`
> sets `PRAGMA foreign_keys=ON`. Lecture 1 had **24 clips pointing at its 24
> concepts** (cut by job 11 one minute before the first extract). `extract.py`
> deleted the concepts first, so the clips' FK dangled and the statement failed
> immediately. Every re-extraction of a lecture with clips died there.
>
> ## Why the throttle diagnosis was wrong
>
> §2 read "0.00 s of CPU over 5 s" as *blocked, not computing*. A **crashed**
> worker produces the same reading. §3 then attributed the dead buttons to
> `_PipelineThrottle.__enter__` waiting with no timeout — but the throttle was
> never exhausted, because `__exit__` unwinds correctly when a worker raises.
> Measured directly after a crash: **`PIPELINE_SEMAPHORE.in_use == 0`**.
>
> So:
>
> - **F1 (periodic reaper) — no longer required for this.** Not harmful, and it
>   is still defensible hardening for a genuinely killed process, but it was not
>   the fix and it would not have prevented the incident.
> - **F2 (bounded throttle acquire) — dropped.** It guards a failure mode that
>   does not exist. The throttle already released correctly on every path.
> - **F3 (per-lecture 409) — still worth doing**, as a double-click guard, but
>   it would have *masked* the crash rather than fixed it.
>
> ## What the real fixes were
>
> Both landed on `engine2/scaffold`:
>
> - `425388c` — detach the lecture's clips (`concept_id -> NULL`) before deleting
>   its concepts. Plus: the test engine now sets `PRAGMA foreign_keys=ON`, which
>   is *why* 710 passing tests missed this. The suite was running against a laxer
>   database than the app.
> - `ed8086d` — `job_scope` settles a crashing worker as `error` instead of
>   leaving it `running` with a frozen heartbeat forever.
>
> ## And the reason it *looked* like "every button is dead"
>
> A second, independent bug: `JobFeed.connect()` assigned `this.sink` and then
> called `disconnect()`, which nulls it. So `publish()`'s `this.sink?.(next)` was
> a permanent no-op and **the job feed never delivered a single snapshot to the
> UI**. The drawer read "Disconnected / No background jobs registered yet" for
> the life of the page. Fixed in `de74a02`.
>
> All 297 React tests missed it because every one of them asserts through
> `feed.subscribe()` and connects without a sink — a different code path from the
> one the app uses.
>
> ## Why it took a live tier to find
>
> `npm run test:live` (added in `c097be6`) boots a real uvicorn against a real
> throwaway database and asserts that the drawer shows a job that exists only
> there, delivered over a real SSE stream. No fake transport can make that
> assertion, because a fake cannot be wrong in the way the sink path was.
>
> **The original text of this document is kept below unchanged**, as the record
> of what was believed and why. It is evidence about how a partial log invites
> the wrong conclusion — the `0.00 s CPU` inference in §2 is the exact trap.
> Sections 3, 4 and 5 are marked inline where they are refuted.

> **The task is `plan/NEXT_SESSION_PROMPT.md`.** This document is the evidence
> behind it. If you were sent here directly, read the prompt file first, then
> come back for the detail behind F1–F3.

> This supersedes the "inconclusive" conclusion in
> `plan/MANUAL_VERIFICATION_2026-09-29.md`. The app was reached this time and the
> cause is identified. **The fix is not written yet** — it is specified in §5.

## 1. What was actually running

> **§1 is accurate.** The backend, the SSE endpoint and the job registry all
> worked. Keep this section.

The backend was up and healthy throughout:

```
GET /health  -> 200
GET /courses -> 2 courses, with real data
  ml:   4 lectures, 196 concepts, graph=True
  prob: 1 lecture,   51 concepts, graph=True
```

`curl -N http://127.0.0.1:8000/jobs/stream` streamed correctly:
`retry: 2000`, then `event: jobs` with a full-array snapshot, then `: keep-alive`
about once a second. **The backend, the SSE endpoint and the job registry are all
working.** Vite's proxy was never implicated.

## 2. The actual state: three crashed jobs, left `running`

> **§2 is REFUTED — read this before the paragraph below.** The jobs were not
> blocked on the SQLite write lock. They raised `IntegrityError` at
> `extract.py:88` and died; the last paragraph of this section mistook "0.00 s
> of CPU" for *blocked* when a **crashed** worker reads identically. The three
> observations are all correct and all reproduce; only the conclusion was wrong.
>
> The specific error, recovered later from a uvicorn log, is
> `FOREIGN KEY constraint failed` on `DELETE FROM concepts WHERE
> lecture_id = ?`, because `clips.concept_id` references `concepts.id` and
> `PRAGMA foreign_keys=ON`. Lecture 1 had 24 clips pointing at its 24 concepts.
>
> What survives from this section, and matters: the jobs stopped refreshing
> `heartbeat_at` — for a *dead* worker rather than a blocked one — so the
> change-gated SSE snapshot stopped changing and the UI never learned anything
> had happened. That part was right and is still true.

`GET /jobs?active_only=true` returned exactly three jobs, all identical:

```
id=14 extract running extracting 70%  last heartbeat 12:28:06Z
id=12 extract running extracting 70%  last heartbeat 12:27:16Z
id=10 extract running extracting 70%  last heartbeat 12:26:45Z
```

Three findings, in order of importance:

1. **All three are `extract` for `lecture_id: 1`, created within 90 seconds of
   each other.** That is one user clicking *Extract Concepts* three times on the
   same lecture inside a minute and a half.
2. **All three froze at the same place** — `stage=extracting`, `pct=70`,
   `detail="Persisting concepts, passages, and spoken links..."`. That string is
   emitted at `backend/api/jobs/extract.py:78-81`, immediately before
   `with SessionLocal() as db:` at line 82, which opens a write transaction
   (`extract.py:88-90` deletes every `Concept` / `LectureLink` / `Passage` for
   the lecture) and then flushes rows in a loop.
3. **They are blocked, not computing.** Sampled the backend process over 5 s:
   **0.00 s of CPU**. Not a slow model, not a slow ffmpeg encode — blocked.

Groq is fine: a live `chat/completions` call returned **HTTP 200 in 1.26 s**, and
`GET /usage` shows `groq.chat: {"calls": 0}` because *no extract job ever got far
enough to record a call* — they froze in persistence, after the LLM stage.

So: **three concurrent extract workers on the same lecture, contending for the
same rows, all deadlocked on the SQLite write lock.** The prime suspect is
`extract.py:88-90` — three sessions each issuing `DELETE ... WHERE
lecture_id = 1` inside a transaction, with `PRAGMA busy_timeout=30000`. A
`busy_timeout` should turn contention into a 30-second `OperationalError`, not a
permanent block, so either the pragma is not reaching these sessions or the
deadlock is a lock-ordering cycle rather than simple contention. **That still
needs a thread dump to confirm** — see §6.

## 3. Why everything else broke: the throttle has no timeout

> **§3 is REFUTED. Do not implement this.** The throttle was never exhausted.
> `_PipelineThrottle.__exit__` releases when a worker raises, because the
> `with` block unwinds — measured after a real crash:
> `PIPELINE_SEMAPHORE.in_use == 0`.
>
> The reasoning below assumed a job that *never exits* its `with` block. No such
> job existed; the three jobs exited by raising. The missing-timeout is a real
> latent weakness (a genuinely stuck worker would queue everything behind it
> silently) but it is **not** what happened, and F2 as specified here would have
> changed nothing while looking like a fix.
>
> What actually made the UI look dead is in the top box: the job feed never
> delivered a snapshot to the UI at all, plus a crash that produced no visible
> outcome.

`LECGAP_MAX_PIPELINE_JOBS=3`, and three jobs were wedged. `_PipelineThrottle.__enter__`
(`backend/api/jobs/common.py:47-56`) does:

```python
while self._free <= 0:
    self._cond.wait()          # <- no timeout
```

**A permit is released only by the job holding it exiting its `with` block.** A job
that never exits holds its permit forever, and once `MAX_PIPELINE_JOBS` jobs are
wedged, every subsequent transcribe/extract/clips/graph request blocks
indefinitely with no error and no timeout. That is the "hugely delayed" in the
original report: new actions were not failing, they were queueing behind a
permanently full semaphore.

> The "hugely delayed" symptom is real but has a different cause: the crash
> happens at 70%, *after* the minutes-long LLM structure pass, so each click
> looked stuck for minutes and then produced nothing. That is also why three jobs
> were created within 90 seconds — a user clicking again because nothing
> appeared.

## 4. Why nothing self-healed

> **§4 is CORRECT and still the reason the jobs stayed `running`.** The cause was
> a crash rather than a wedge, but the effect is the same: `recover_orphans()`
> only runs at import, so nothing settled a job that died after boot. Fixed by
> `ed8086d`, which settles a crashing worker immediately instead of waiting for
> a restart.

`recover_orphans()` runs **only at import time** (`backend/main.py:30-35`). It
cannot reap a job that wedges *after* boot.

The backend was restarted at 18:07:04 local (12:37:04Z). At that moment the three
jobs were ~10 minutes old, and `ORPHAN_AFTER_S = 900s` (15 min) is deliberately
generous — a long ffmpeg re-encode publishes nothing for minutes. So recovery
correctly declined to touch them. They are now ~25 minutes old and *would* be
reaped at the next restart, but **nothing reaps them while the process runs.**

**A correction to my own analysis, recorded because it nearly became a bad fix:**
I first read the stored `heartbeat_at` of `12:26:45` as local wall-clock and
concluded a UTC/local mismatch in `_as_utc`. That was wrong. SQLAlchemy stores
UTC on this connection — verified by round-trip: writing an aware
`datetime.now(timezone.utc)` of `12:50:21Z` read back as naive `12:50:21`, a drift
of **0.0 minutes**. So `12:26:45Z` really was 12:26:45 UTC, i.e. 17:56:45 local,
~10 minutes before the restart. `recover_orphans` behaved exactly as documented.
The `_as_utc` change was made and then reverted; `job_registry.py` is unmodified.

## 5. The fix, specified but not yet written

> **§5 is SUPERSEDED. F2 is dropped and F1 is not required.** The fixes that
> actually landed are in the top box (`425388c`, `ed8086d`, `de74a02`) and none
> of them is the one specified here. F3 is still a reasonable double-click guard
> and remains undone. The text below is kept as the record of what was planned.

Three changes, in dependency order. **Nothing below is done.**

### F1 — a periodic reaper, not a boot-only one (the core fix)

> **Not the core fix.** No throttle permit needed freeing; there was nothing to
> unblock. Still defensible as hardening for a process that is killed outright,
> and the §4 observation (nothing reaps after boot) is real — but `ed8086d`
> already covers the case that actually occurred, by settling the job at the
> moment it crashes rather than waiting up to 15 minutes for a reaper.

Run `recover_orphans()` on an interval (a daemon thread started at import, ~60 s)
as well as at boot. A job whose heartbeat is older than `ORPHAN_AFTER_S` becomes
`orphaned`, which is the honest state — nothing is executing it.

This alone unblocks the throttle, because the wedged job's worker is not going to
exit its `with` block on its own. Note the caveat already in the code: the
reaper cannot interrupt a running worker, it can only stop *reporting* it and stop
counting it. To actually free the permit, pair it with:

### F2 — a bounded acquire on the throttle

> **DROPPED. This guards a failure mode that does not exist.** The throttle
> released correctly on every path, including the crash that caused the
> incident (`in_use == 0` measured afterwards). Implementing this would have
> looked like progress and fixed nothing.

Give `_PipelineThrottle.__enter__` a timeout (or convert it to
`acquire(blocking=False)` + a bounded wait) and have the **workers** translate a
failed acquire into a job error rather than waiting silently. A job that cannot
get a permit in, say, 30 s should say so. This turns "silently queued forever"
into "honest 409/error", which is the difference the roadmap keeps asking for.

### F3 — one extract per lecture, server-side
The client disables the row buttons while a lecture is busy
(`useBusyLectureIds`), but that is a UI affordance, not a guarantee, and it only
works if the feed is live. The durable fix is a per-lecture advisory lock in
`POST /lectures/{id}/concepts` returning **409** when a job for that lecture is
already in flight. `job_registry.py` already has `acquire_course` /
`release_course` / `CourseBusy` written and unit-tested — **and never called from
any route.** That is the missing wiring, and it is the single change that would
have prevented this incident.

## 6. Immediate state and what to do next

**The app is unblocked.** The three jobs were manually marked `orphaned`; the
semaphore in the running process was never exhausted (they wedged after boot), so
reloading the page should show working buttons and a clean drawer.

Confirm by: reload `/student`, check the Navbar dot is green *SSE Live*, then
click *Extract Concepts* **once** and watch a single job card advance.

Before writing F1–F3, the next session should get the evidence this session could
not:

1. **A thread dump of a wedged process**, to confirm the deadlock is the SQLite
   write lock and not something else. `py-spy dump --pid <n>` is the direct route;
   if it cannot be installed offline, reproduce with three concurrent
   `POST /lectures/1/concepts` against a fresh DB and inspect.
2. **Whether `PRAGMA busy_timeout` actually reaches the worker's sessions** —
   `db.py` sets it via a `connect` event listener; confirm the pragma value
   inside an extract worker's session.
3. **Whether the three jobs wrote anything to the `error` column** — they did not,
   which is itself a finding: a job that dies in persistence reports nothing.

## 7. What the test suite could not have caught

297 React tests and 710 Python tests passed throughout. Both suites are
structurally blind to this incident:

- the React suite mocks the transport, so the live feed — and therefore
  `useBusyLectureIds`, and therefore the double-click protection — was never
  exercised end to end;
- the Python suite has no test that starts a real extract and asserts the throttle
  frees when it fails, and `recover_orphans` is only tested at boot.

Worth adding with F1–F3: a test that holds two permits with a blocked worker and
asserts the third acquire *times out* rather than blocking, and a test that a
second `POST /lectures/{id}/concepts` while one is in flight returns 409.
