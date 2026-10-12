# 06 · Client-side job feed — `frontend/jobfeed.py`

**File:** `frontend/jobfeed.py` (231 lines). A push channel for job progress.
Thread-safe: written by the consumer thread, read by whichever Streamlit thread
renders the fragment.

## Why it exists

The progress monitor used to re-run the *entire* Streamlit script every
0.5–1.5 s to read a progress number. That rebuilt every element on the page,
restarting every `<video>` player and making long lists unusable while a job
ran. Nothing in the framework can avoid a re-render on a push, so the fix has
two halves: this module keeps a live snapshot in memory (fed by SSE, so asking
costs nothing), and `shell.py` renders the cards inside an `st.fragment` so
only the card block re-executes (file 07).

## Protocol and fallback

- Primary: `GET /jobs/stream?interval_s=1.0[&course_id=…]` as server-sent
  events (`Accept` via auth headers; API key sent, so a guarded backend does
  not 401 the stream). Connect timeout 5 s; read timeout 20 s — comfortably
  above the server's ~1 s keep-alive, or an idle course would look dead.
- Lines that are not `data: ` are skipped (`retry:`, `: keep-alive`,
  `event:`). A malformed frame is skipped, never fatal. A non-200 response, a
  dead socket, or a backend that predates the endpoint all mean "not a stream".
- Fallback: one cheap `GET /jobs` reading, then back off and retry the stream
  with the ladder `(1, 2, 5, 10)` seconds, sticky at the end. Polling *instead*
  of retrying the stream is the named bug this loop shape prevents.
- Modes: `starting | stream | poll | unavailable`. `change_token` advances
  only when the published list is **non-empty**, so an idle course is not
  mistaken for a change and the fragment can no-op.

## Reads and lifecycle

- `snapshot()` returns a copy (callers cannot corrupt the feed);
  `job(job_id)` returns one row or `None` ("no durable row yet" — the caller
  decides whether to fall back to the legacy per-lecture endpoint);
  `mode()`, `changed_since(token)`, `change_token()`.
- `start()` is idempotent and safe to call on every rerun; `stop()` sets the
  flag *and* closes the in-flight response, so a daemon thread parked on an
  idle socket cannot hold the connection for the life of the process.
- `job_feed(course_id)` is a **process-wide singleton**: one SSE connection
  for all sessions. `course_id` shapes only the first connection — later calls
  share the open stream rather than re-negotiating it. `reset_feed_for_tests()`
  stops and clears it.

## What the tests pin (`tests/test_jobfeed.py`)

Frames publish the snapshot; the API key travels on the stream request; byte
frames decode; malformed frames don't kill the feed; 404/dead-socket mean
"not a stream"; snapshots are copies; the token moves only on non-empty
lists; the poll fallback reads the list and reports `unavailable` otherwise.
No Streamlit, no network, no threads except the one proving `stop()` unblocks
a reader.
