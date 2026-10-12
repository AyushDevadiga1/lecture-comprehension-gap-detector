# 09 · Library — `frontend/panels/library.py`

**File:** `frontend/panels/library.py` (201 lines). Concept clips and
lecture-row management. Clips render as real players inside a bounded frame —
a server-side filesystem path is an implementation detail and useless to a
reader — and the list scrolls inside its own box rather than stretching the
page.

## Clip playback

- `clip_rows(lecture_id)` — all clip rows for a lecture (`GET
  /lectures/{id}/clips`), `[]` when unreachable.
- `render_clips(lecture_id, …)` — splits rows into **playable** (`ok`) and
  **unplayable**, captions the count ("N of M concept clips are playable"),
  and renders each playable clip as its concept name + time span with a
  `video_box` player. A clip whose path maps to no URL gets an inline
  "clip file missing on the server — re-cut" note instead of a dead player;
  unplayable rows collapse into one "re-run Cut concept clips" line.
- `clip_watch_picker(nav_course)` — ready-lecture picker + "Show clips"
  button; the open lecture persists in Tier-2 `clips_view` so reruns don't
  collapse it.
- `clips_followup(job, lecture_id)` — the hook `drain_ready` calls after a
  clip job lands (`after == "clips_list"`), rendering the fresh list in the
  page body.

## Stalled-row triage (`stalled_rows`, `render_stalled_rows`)

Two very different situations both surface as status `uploaded`, and the panel
splits them because they need opposite actions:

- **Resumable** — media is registered and on disk (`has_media`); only
  transcription never started. Fixable in place with `POST
  /lectures/{id}/rerun` ("Start processing", busy-guarded). `error`-status
  rows without media are *not* resumable.
- **Abandoned** — no file ever arrived (row created, stream died). Nothing to
  resume; the panel offers one "Delete these empty rows" button and reruns.

Each rerun failure surfaces its `{detail}`; last-error captions persist on
resumable rows.

## Lecture rows (`render_lecture_rows`)

Checkbox-per-row deletion via `DELETE /lectures/{id}`, with per-row failure
messages; any success invalidates the whole Tier-1 cache.

## Shared helpers

`lecture_label(l)` (`#id — title`) and `ready_lectures(course)` (course-scoped,
`status == "ready"`) are imported by the ingest, graph, faculty and quiz
panels — one definition of "which lectures are actionable".
