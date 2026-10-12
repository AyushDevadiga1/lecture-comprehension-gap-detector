# 14 · Component facade — `frontend/components.py`

**File:** `frontend/components.py` (97 lines). The stable public surface of
the Streamlit frontend: it re-exports the panel functions so existing imports
(`from frontend import components`) and the whole test suite keep working, and
there is exactly one place to look for "what can a dashboard call".

- `shell` (sidebar, auth banner, quota row, snapshot strip, job monitor,
  upload-thread registry — including its private helpers and tunables, which
  tests reach for directly), `ingest` (upload form, process controls,
  duplicate check), `library` (clips, watch picker, stalled/lecture rows),
  `graph` (course + faculty DAG), `quiz`, and — lazily — `faculty`.
- Faculty panels resolve through module `__getattr__`, so `import components`
  stays cheap and never imports Streamlit eagerly for dashboards that don't
  need them; anything else raises `AttributeError`.
- `__all__` enumerates the full public API.

Keeping the facade is what made the panel split a refactor rather than an API
change: the entrypoints and every existing test continued to import
`components.render_*` unchanged.
