"""Unit tests for frontend/state.py (Tier-2 session-state namespaces).

Tests replace the module-level ``st`` with a stub exposing a dict
session_state, since state.py only ever touches ``st.session_state``.
"""

import types

import pytest

from frontend import state


class _SessionState:
    def __init__(self):
        self._d = {}

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        return self._d[key]

    def __setitem__(self, key, value):
        self._d[key] = value

    def __delitem__(self, key):
        del self._d[key]

    def pop(self, key, default=None):
        return self._d.pop(key, default)

    def keys(self):
        return self._d.keys()


@pytest.fixture
def sess(monkeypatch):
    ss = _SessionState()
    st = types.SimpleNamespace(session_state=ss)
    monkeypatch.setattr(state, "st", st)
    return ss


def test_namespaces_are_isolated(sess):
    state.set("quiz", questions=["q1"], version=1)
    state.set("faculty", stats={"heatmap": []})
    assert state.get("quiz", "questions") == ["q1"]
    assert state.get("faculty", "stats") == {"heatmap": []}
    assert state.get("quiz", "missing", "dflt") == "dflt"


def test_unknown_namespace_defaults(sess):
    assert state.get("nope", "key") is None
    assert state.get("nope", "key", 7) == 7
    assert state.get_state("nope") == {}


def test_clear_removes_namespace(sess):
    state.set("quiz", version=1)
    state.clear("quiz")
    assert "lecgap:quiz" not in sess


def test_keys_are_prefixed(sess):
    state.set("quiz", version=1)
    assert set(sess.keys()) == {"lecgap:quiz"}


def test_clear_all_only_prefixes(sess):
    sess["other"] = "keep"
    state.set("quiz", version=1)
    state.set("jobs", items=[])
    state.clear_all()
    assert set(sess.keys()) == {"other"}