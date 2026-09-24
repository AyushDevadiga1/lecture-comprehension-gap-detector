"""Namespaced session-state helpers (Tier-2 cache) — Streamlit-bound, thin.

Every piece of UI state that must survive a rerun lives in a *namespace* under
``st.session_state`` (keys prefixed ``lecgap:``). Namespaces (contract with
``plan/FRONTEND_ARCHITECTURE.md`` §3.3):

    nav     - course, last-loaded course for data panels
    quiz    - questions, version, render_t, course_id, student_id
    faculty - stats, graph, per-course cache stamps
    jobs    - items: [{lecture_id, title, kind, after}]
    tl      - selected lecture + rendered timeline key

Tests replace the module-level ``st`` with a stub exposing a dict session_state.
"""

import streamlit as st

_PREFIX = "lecgap:"


def get_state(ns: str) -> dict:
    """Return the namespace dict, creating it on first access."""
    key = _PREFIX + ns
    if key not in st.session_state:
        st.session_state[key] = {}
    return st.session_state[key]


def get(ns: str, key: str, default=None):
    return get_state(ns).get(key, default)


def set(ns: str, **kv) -> None:
    get_state(ns).update(kv)


def clear(ns: str) -> None:
    st.session_state.pop(_PREFIX + ns, None)


def clear_all() -> None:
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(_PREFIX):
            del st.session_state[key]