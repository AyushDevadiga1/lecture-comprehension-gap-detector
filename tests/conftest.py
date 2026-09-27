"""Test isolation fixture.

Tests must not touch the development database. Point every test run at a
throwaway SQLite DB before importing backend modules, so the production
data/lecgap.db remains untouched regardless of import order.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Isolate the DB at the earliest possible moment - before any test module
# imports backend.config. This must be a hard set, not setdefault: a module-level
# `os.environ[...]` in a test file runs during collection, which is *after*
# conftest, and would otherwise win and re-point the engine at data/.
td = tempfile.mkdtemp(prefix="lecgap-test-")
os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{Path(td) / 'test.db'}"


def pytest_collection_finish(session):
    """Fail loudly if a test file re-pointed the engine at the real database.

    A test module that sets LECGAP_DATABASE_URL at module scope does so during
    collection, which is *after* this file, so it can win. Any resulting path is
    fine except the live data/lecgap.db — that one would let the suite write to
    real lecture data.
    """
    from backend.models import db as dbmod

    live = (REPO / "data" / "lecgap.db").resolve()
    bound = Path(str(dbmod.engine.url).replace("sqlite:///", "")).resolve()
    assert bound != live, (
        f"tests bound to the live database ({bound}); "
        "remove the module-level LECGAP_DATABASE_URL override"
    )


@pytest.fixture(autouse=True)
def _no_live_job_feed(monkeypatch):
    """Keep the progress cards offline.

    The first card that sees a durable job id opens the SSE feed, which is a
    background thread with its own reconnect loop. In a test suite that thread
    outlives the test that started it and would then poll a *later* test's
    monkeypatched client. The singleton is pre-seeded with an unstarted feed,
    so the real wiring is still exercised but no socket is ever opened; tests
    that want the feed's behaviour construct a JobFeed themselves.
    """
    from frontend import jobfeed

    monkeypatch.setattr(jobfeed, "_feed", jobfeed.JobFeed(), raising=False)
