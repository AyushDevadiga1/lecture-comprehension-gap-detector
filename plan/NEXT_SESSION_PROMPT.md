# NEXT SESSION — start here

> # ⛔ THE TASK BELOW IS DONE. It was also WRONG. Read this box, not the rest.
>
> Everything from "## The bug to fix" onwards describes a **SQLite write-lock
> deadlock** that never happened. It was a **foreign-key violation**, and the
> three "wedged" jobs crashed instantly rather than blocking. **F1 and F2 fix
> nothing** — the throttle was never exhausted, measured `in_use == 0` straight
> after a crash. F3 is done too.
>
> **All of it has since been fixed, on `engine2/scaffold` (10 commits):**
>
> | Commit | What it actually was |
> |---|---|
> | `425388c` | `IntegrityError` on `DELETE FROM concepts` — `clips.concept_id` is a real FK and `PRAGMA foreign_keys=ON`. Detach the clips before deleting their concepts. The test engine now enforces FKs, which is *why* 710 tests missed it. |
> | `ed8086d` | `job_scope` had no `except`, so a crashed worker stayed `running` with a frozen heartbeat forever. |
> | `de74a02` | **`JobFeed.connect()` assigned `this.sink` then called `disconnect()`, which nulls it.** The job feed never delivered a single snapshot to the UI. This is the actual "every button is dead". |
> | `c097be6` | `npm run test:live` — a real uvicorn, a real throwaway DB, real components. It is what found `de74a02`. |
> | `4031f6b` | `npm run test:e2e` — a real browser reads the SSE stream through Vite's proxy. |
> | `446b33e` | F3 wired: the per-course lock now actually guards the pipeline (was defined, tested, and called from nowhere). |
> | `7b87f36` | Clip browser — the clips existed and nothing could show them. |
> | `7efdc4c` | **Timestamp bug.** `_iso` relabelled a naive UTC timestamp as local, so the UI showed "330m 36s elapsed" for a 26-second job. |
>
> `plan/WEDGE_DIAGNOSIS_2026-09-29.md` carries the full refutation with evidence.
> `plan/REACT_HARDENING_HANDOFF.md` §1 has the current numbers and §4a what the
> automated tiers cannot see.
>
> ## What is left
>
> 1. **A human has to run the app.** Behaviour is verified in a real browser by
>    the E2E tier; appearance and legibility are not verified at all, and no
>    agent can verify them. Run `npm run shots` and look.
> 2. **The §10 gate** — a playing `<video>` surviving a job tick. This is the
>    app's whole reason for existing and is still unproven. Needs a tiny real
>    media file in the E2E seed.
> 3. **Wave 3** — react-flow DAG, timeline/coverage, quota row, and the 10
>    wrapped endpoints that are still called by nothing.
>
> `main` is untouched at `5e0a434`. Nothing pushed. The working tree is clean
> apart from `output.txt`.

> **Paste this into the new session:**
>
> `Read C:\Users\hp\Desktop\lecture-comprehension-gap-detector\plan\NEXT_SESSION_PROMPT.md and follow it exactly.`

Everything below is the prompt as it was written before the refutation. It is
kept so the record is honest, but **do not act on it** — read the box above.

Everything below is the prompt itself. It is written to be pasted whole, so it
repeats what the other docs say on purpose — a new session should not have to
stitch four files together before it can act.

---

Working on `C:\Users\hp\Desktop\lecture-comprehension-gap-detector`, branch
`engine2/scaffold`. **Do NOT touch `main`** (pinned at `5e0a434`) and do not merge
to it — the React app is not ready and `main` is deliberately kept clean.

## Read first, in this order

Follow these rather than re-deriving anything:

1. `plan/REACT_HARDENING_HANDOFF.md` — the main handoff. It opens with a **STOP
   box**: the app has never been verified working. It holds the invariants, the
   working commands, and ten traps that each cost real time.
2. `plan/WEDGE_DIAGNOSIS_2026-09-29.md` — the diagnosed bug and the three fixes
   you are about to write, with the evidence and the preconditions.
3. `plan/MANUAL_VERIFICATION_2026-09-29.md` — superseded on the diagnosis, but
   its six-step procedure for checking the app end to end is still the best one.

**`WORKLOG.md` is git-ignored, so it is NOT in your context.** Everything you need
is in the three documents above.

## Where things actually stand

**Updated 2026-09-29.** The task below is done. Ten commits landed on
`engine2/scaffold`; `main` is untouched at `5e0a434`.

All four tiers are green: **734 pytest**, **317 vitest**, **12 live** (real
uvicorn + throwaway DB), **3 E2E** (real Chromium through Vite's proxy).

What was actually wrong, both now fixed:

- **A foreign-key violation**, not a write lock. `extract.py` deleted a
  lecture's concepts before its clips, and `clips.concept_id` references
  `concepts.id` with `PRAGMA foreign_keys=ON`, so every re-extraction of a
  lecture that already had clips died. `425388c`.
- **The job feed never reached the UI.** `JobFeed.connect()` assigned
  `this.sink` and then called `disconnect()`, which nulls it — a permanent
  no-op. This was the actual "every button is dead". `de74a02`.

F1 and F2 below are **dropped**; do not implement them. F3 is done
(`446b33e`). For the full reasoning see the refutation box in
`plan/WEDGE_DIAGNOSIS_2026-09-29.md`.

## The bug to fix

> ⚠ **REFUTED — kept only as the historical record.** Three `extract` jobs did
> not wedge on a SQLite write lock; they **crashed instantly** and were left
> `running` forever. The throttle was never exhausted (`in_use == 0` measured
> straight after a crash). The inference that produced this whole theory was
> reading "0.00 s of CPU" as *blocked* when a **crashed** worker looks identical.

Three `extract` jobs wedged on a SQLite write lock. Each held one of the three
`LECGAP_MAX_PIPELINE_JOBS=3` permits, and `_PipelineThrottle.__enter__` in
`backend/api/jobs/common.py` does `while self._free <= 0: self._cond.wait()`
**with no timeout** — so three wedged jobs meant every later pipeline request
blocked forever, silently. To the user this presented as "all the buttons are
broken and hugely delayed". On top of that, `recover_orphans()` runs only at
import, so nothing reaps a job that wedges *after* boot.

Write these three fixes, in this order, one commit each:

**F1 — periodic reaper.** Run `recover_orphans()` on an interval (~60 s, daemon
thread started at import) as well as at boot. This is the core fix.

**F2 — bounded acquire on the throttle.** A job that cannot obtain a permit
within a timeout must report an error rather than waiting forever.

**F3 — per-lecture advisory lock.** `POST /lectures/{id}/concepts` returns 409
when a job for that lecture is already in flight. `job_registry.py` **already has
`acquire_course` / `release_course` / `CourseBusy` written and unit-tested, and
they are called from nowhere.** Wiring them up is most of this fix, and it alone
would have prevented the incident.

**Before writing F1**, get the evidence the last session could not: a thread dump
of a wedged process (`py-spy dump --pid <n>`) to confirm the deadlock is the
SQLite write lock and not something else, and confirm that
`PRAGMA busy_timeout=30000` actually reaches the extract worker's session
(`db.py` sets it via a `connect` event listener). Reproduce with three concurrent
`POST /lectures/1/concepts` against a fresh DB if py-spy is unavailable.

## Gate for every commit

```powershell
cd frontend-react
npm run verify          # type-check + lint + test

cd ..\..
& "D:\Anaconda3\envs\lecgap\python.exe" -m pytest tests -q
```

The Python interpreter on `PATH` is already the right one (the `lecgap` conda
env, 3.10.20), but use the explicit path anyway. `data/lecgap.db` must be
byte-identical before and after a pytest run.

Add tests alongside the fixes: one asserting a **third throttle acquire times out**
rather than blocking, and one asserting a **second `POST /lectures/{id}/concepts`
while one is in flight returns 409**.

## Traps

From the handoff; the sharpest ones repeated here.

- **`git rm` stages immediately.** A later `git add <paths>` will *not* undo it, so
  a deletion can land in the wrong commit. That already happened once and left a
  commit importing a file it had deleted. Check
  `git diff --cached --name-status` lists exactly what you meant, and
  `git cat-file -e <sha>:<path>` for anything you deleted.
- **`Set-Content -Encoding utf8` corrupts non-ASCII from PowerShell 5.1** — it turns
  em-dashes into `?`. It bit twice, once silently inside a source file. Use the
  editor for any file containing an em-dash or an arrow.
- **React Query v5's `QueryCache.subscribe` has no `'error'` event.** The events are
  `added` / `removed` / `updated` / `observerResultsUpdated` /
  `observerOptionsUpdated`, with the error only a field on the updated query's
  state. Use `new QueryCache({ onError })`. A handler that filters for `'error'`
  silently never fires.
- **`app.routes` no longer exposes the domain routes.** FastAPI nests
  `include_router` behind a `_IncludedRouter`, so `isinstance(r, APIRoute)`
  matches only `/health` and `/llm/backends`. Read the OpenAPI schema instead.
- **`import.meta.glob` keys a same-directory file as `./name`**, not `../dir/name`.
- **Do not kill a process the user is using.** The last session started a uvicorn,
  judged it not-up, and killed it while the user was still trying to run the app.
  If you start a server, either leave it running and say so, or do not start one.

## Do not

- Do not start **Wave 3** (react-flow DAG, timeline, quota row, library). It is
  blocked until the app is proven to run and the fixes above are in.
- Do not describe the app as working on the strength of the test count. 297 React
  tests and 710 Python tests passed while the app was unusable, because every feed
  test injects a fake transport. **Bring Playwright forward**, not to Wave 4.
- Do not merge to `main` or push, unless explicitly told.

## First thing to do

Ask me to run the app and report what happens, using the procedure in
`plan/MANUAL_VERIFICATION_2026-09-29.md`. Specifically: with the backend and
`npm run dev` both running, open **`http://localhost:5173/student`** — *not*
`:8000`, which is FastAPI and has no UI — confirm the Navbar dot reads **"SSE
Live"**, then click **Extract Concepts once** and watch a single job card
advance. Report back what you see before you change any code.

## Two notes on the current state

- The three wedged jobs were **manually** marked `orphaned` to unblock the app.
  That was a manual intervention, not a fix. The database is clean; the code is
  not.
- A timezone "fix" to `job_registry._as_utc` was written and then **reverted** —
  it was based on a misreading of the stored timestamps. `git diff backend/` is
  empty. The reasoning, including why it was wrong, is in
  `plan/WEDGE_DIAGNOSIS_2026-09-29.md` §4, because the next session will see the
  same naive-looking timestamps and may repeat the mistake.
