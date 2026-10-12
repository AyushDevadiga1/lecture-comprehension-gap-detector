# 07 · App shell — `frontend/panels/shell.py`

**File:** `frontend/panels/shell.py` (684 lines). Everything that frames the
page or reports background state lives here, so content panels never touch
session plumbing, the job feed, or the upload registry.

## Sidebar (`course_sidebar`)

Course picker + readiness caption + course delete, in the sidebar. Course
options come from `GET /courses`, falling back to the distinct course ids in
the lecture list. Empty backend → "No courses yet." The first course
auto-selects when nothing (or a stale value) is stored. A caption shows
lectures/ready/concepts/graph-nodes plus the live `_snapshot_line`. "Refresh
course list" clears the whole Tier-1 cache and reruns. Deleting a course calls
`DELETE /courses/{id}`, clears the cache, drops `nav_course`, and reruns.
`rerun()` tolerates runtimes without `st.rerun` (AppTest) by swallowing the
failure.

## Quota row (`render_usage_row`, `_usage_summary`)

Reads `GET /usage` and renders one caption per line: `LectGap quota — …`.
Pure, unit-testable composition: Groq chat (requests + tokens left, reset
countdown), Groq Whisper (requests left), Local Whisper
(available/offline/unlimited/ffmpeg ✓✗), Ollama reachability, plus a
per-lecture estimate ("this lecture ≈ N Groq requests ≈ M more lectures like
this") when a transcription is active and Whisper quota data exists.

## Auth banner (`render_auth_banner`)

Renders one top-level error when the recorded error has `kind == "auth"`.
**Known gap (verified):** nothing in `client.py` ever records that kind — the
only kinds produced are `timeout`, `network`, `http`, `json` — so this banner
can never fire as written; a 401 arrives as `kind="http", status=401`. See
file 17. (The React rebuild's 401-banner work exists because of exactly this
class of failure.)

## Upload registry (`begin_upload`, `cancel_upload`, `_upload_status`)

Module-level dict keyed by lecture id, lock-guarded, process-global — so a
daemon upload thread survives between script executions and two sessions share
it. `begin_upload` refuses a second upload for the same lecture, spawns the
worker, registers a `start_job(…, kind="upload")` card, and returns whether it
started. `cancel_upload` sets the event; the chunk generator stops between
chunks.

`_upload_status` returns one of three states — this exact three-way split is a
fixed bug:

- `"done"` — transfer finished; read ok/error/job_id (the PUT enqueued the
  durable transcription job, so the card follows the real thing from here).
  The entry is popped under the lock *after* reading, so a concurrent reader
  never sees a half-removed entry, and memory stays tight.
- `"pending"` — a live entry whose thread hasn't finished.
- `"absent"` — no entry at all (never started, or already consumed).

Previously "pending" and "absent" collapsed into one value, so the monitor
could not tell a transfer in flight from one with no thread behind it and
reported "Upload failed" on the first poll, making Cancel unreachable.

## Job registry (`start_job`, `active_job`)

`start_job(course_id, lecture_id, title, kind, after, job_id)` remembers a
background job so the monitor renders its card next rerun. Jobs accumulate —
starting a new one never drops an old card — and identical
(lecture, kind) pairs coalesce. `active_job(lecture_id, kinds)` is the
busy-guard panels use to disable actions while work runs.

## Progress cards (`render_progress_cards`, `_auto_refreshing`)

Live cards inside a **self-refreshing `st.fragment(run_every="1s")`** — only
this block re-executes, so clip players, the graph and the quiz stay mounted.
The block re-reads the Tier-2 job list every tick, renders the cards it owns
(`kinds` partitions the dashboard into separate ingest/process monitors, each
under the controls that started those jobs), writes its verdict back, and
carries the other monitor's jobs over untouched.

`_auto_refreshing` degrades to a plain render where fragments don't exist
(AppTest, Streamlit < 1.37) — but *only* the two "not supported" shapes fall
back silently; any other exception is re-raised, because a monitor that
quietly stops refreshing is the exact failure this was written to remove.

Per-card behaviour (constants): slow stages (`building_graph`,
`extracting`, `cutting_clips`, `clips`, `local_transcribing`,
`loading_model`, `transcribing`) get 600 non-advancing ticks (~10 min)
before being called stalled, vs 40 for fast stages; a 6-hour deadline drops a
job whose feed went quiet with an explanation instead of rendering forever.

## Completion rule (`_record_ready`, `drain_ready`)

When a job finishes, the monitor records (never renders) the completion:
invalidate the course, append `{lecture_id, course_id, title, after, detail}`
to Tier-2 `jobs.completed`. `drain_ready(on_ready)` — called once per full
page pass, **outside the fragment** — renders each "Done" line and runs the
panel follow-up (e.g. the clip list after a cut). A success message rendered
inside the fragment would flash and vanish on the next tick.

## Snapshot strip (`render_course_snapshot`)

The 5 s snapshot drives both dashboards. Renders the readiness caption;
`transcribing` rows get live `stage + progress_pct` lines (progress endpoint
first, snapshot values as fallback) and seed monitor cards so a fresh tab
attaches to backend jobs it wasn't present for (kind `"attach"`); `uploaded`
rows are *not* auto-carded — a stuck `uploaded` row is a hint, never a
spinning card — and are instead pointed at the stalled-row triage (file 09),
because the snapshot cannot tell resumable rows from abandoned ones and must
not claim they are all broken.
