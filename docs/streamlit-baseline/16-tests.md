# 16 · Tests that pin the frontend

All under `tests/` on `main`, run with `pytest`. Seams are stated per file
because "how is this tested without a browser/backend" is the reusable
knowledge.

| File | Target | Seam / style |
|---|---|---|
| `test_theme.py` | `frontend/theme.py` + everything it feeds | Pure maths: WCAG AA per text token per surface in both themes; node-ink legibility for every rank and hashed name; declared Streamlit theme matches the palette |
| `test_client.py` | `frontend/client.py` | Monkeypatched `client.requests.request` (single transport seam); controllable `CacheStore(clock=…)`; covers retry-once, timeout, 4xx detail extraction, non-JSON, thread-isolated errors |
| `test_jobfeed.py` | `frontend/jobfeed.py` | Fake sockets driving the loops; no Streamlit/network/threads except the `stop()`-unblocks-reader proof |
| `test_state.py` | `frontend/state.py` | Module-level `st` replaced with a dict-backed stub |
| `test_components.py` | monitor bookkeeping, stage text | `sess` + `fake_st` fixtures; regression test for the single-slot overwrite bug; duplicate detection via `ingest` |
| `test_frontend_render.py` | `frontend/render.py` | Direct HTML assertions: placeholder carries the theme, DAG SVG has no external deps, one node per kept concept, arrowheads, hostile labels escaped |
| `test_snapshot.py` | `GET /courses/{id}/snapshot` | Throwaway SQLite DB via `tests/conftest.py`; ORM-seeded rows; no real jobs |
| `test_baseline_fixes.py` | stalled rows, clips, graph, cards | `fake_st` app-test style: resumable-vs-abandoned split, start-processing button → rerun endpoint, clip counts, graph absence/counts/course-scoping, card partitioning by kind |
| `test_c0_fixes.py` | C0 hardening (`ENGINE2_REBUILD_PLAN`) | Uploaded-row stops re-rendering; hanging upload stalls instead of spinning; missing entry fails fast; slow-but-steady stages not cut off; registry lock-guarded; concurrent `begin_upload` registers exactly one |
| `test_runtime_fixes.py` | real-session failures | `media_url` percent-encoding round-trips (spaces, literal `%`, non-ASCII) + traversal rejection; `dag_svg` structure/escaping |
| `test_contract.py` | backend↔contract doc | Every documented route exists; no undocumented route ships; every JSON route declares a response schema; no schema exposes a filesystem path; `media_url` helper agrees with the schema; quiz question has no answer field |

The through-line: failures that are invisible in code review (light values on
a dark page, 2.6:1 label ink, a collapsed pending/absent upload state, an
unencoded space in a clip URL) are pinned as properties, not as the specific
hexes or strings that happened to be wrong.
