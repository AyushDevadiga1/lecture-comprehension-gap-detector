# 08 · Ingest and process — `frontend/panels/ingest.py`

**File:** `frontend/panels/ingest.py` (143 lines). The two things a student does
to a lecture: **ingest** owns upload (form, duplicate detection, the
non-blocking upload-thread hand-off); **process** owns the three pipeline
actions and disables itself while a job runs.

## Upload form (`render_ingest_form`)

A `st.form("upload_form")` with a transcription-backend select (`auto` /
`local` / `groq`; auto means Groq when key + ffmpeg are available, otherwise
the bundled local Whisper) and a file uploader
(mp4/mp3/wav/m4a/mkv/mov/webm).

- **Duplicate guard:** `duplicate_lecture(course_id, filename)` matches the
  file stem against existing lecture titles in the course. A match warns and
  requires an explicit "Upload anyway" checkbox — uploading regardless creates
  a second row, and the panel says so.
- **Two-step upload:** `POST /lectures` creates the row (`{course_id, title,
  whisper_backend?}`), then `shell.begin_upload(…file bytes…)` streams the
  media in a daemon thread. The script never blocks; progress appears in the
  card below. A second click while uploading reports "already in progress"
  instead of queuing duplicate work.
- Below the form: `render_progress_cards(kinds=("upload", "transcribe",
  "attach"))` + `drain_ready()`.

## Process controls (`render_process_controls`)

`Extract concepts → auto-rebuild the course graph → cut clips`, against a
lecture picker built from ready lectures only (file 09). The one-pipeline-job
rule: `shell.active_job(lecture_id, kinds=("extract", "graph", "clips"))`
disables all three buttons while any of them runs, because a second click
would queue duplicate work behind the same semaphore slot.

1. **Extract concepts + build graph** — `POST /lectures/{id}/concepts`,
   tracked as kind `"extract"`.
2. **Rebuild graph only** — `POST /courses/{id}/graph` with
   `lecture_id` as a *query* parameter, tracked as kind `"graph"`.
3. **Cut concept clips** — `POST /lectures/{id}/clips`, tracked as kind
   `"clips"` with `after="clips_list"` so `drain_ready` renders the clip list
   when it lands.

Failures surface the backend `{detail}`; the progress cards for the three
kinds render directly under the buttons that queued them, and `drain_ready`
runs with `library.clips_followup` — outside the fragment, so the finished
clip list lands in the page body and stays put.
