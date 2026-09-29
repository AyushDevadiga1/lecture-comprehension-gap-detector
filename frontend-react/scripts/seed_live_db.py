"""Seed a throwaway SQLite database for the live-server test tier.

The React suite is 100% mocked-transport, which is why an app whose extract
worker died with an IntegrityError on every click still showed 297 green
tests. `vitest.live.config.ts` closes that gap for the READ path: it boots a
real uvicorn against a real database and lets the real components render real
responses.

This script builds that database. It is deliberately SMALL and deterministic —
a handful of rows with obvious sentinel names, so a test can assert on a
literal and a failure names the row that went missing. It is not a fixture of
the production dataset; it is a fixture of the SHAPE the UI has to survive.

Usage:
    python scripts/seed_live_db.py <path-to-sqlite-file>

Run with the project interpreter (D:\\Anaconda3\\envs\\lecgap\\python.exe) so the
schema and the engine pragmas match the running app exactly.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# MUST happen before anything imports backend.models.db.
#
# That module builds its engine at import time from `database_url()`, so the
# env var is read once, on first import. Setting it afterwards — as this script
# originally did, after the imports — has no effect on the already-bound engine:
# `engine.dispose()` empties the pool but does not re-read the URL. The result
# was a seed that silently wrote to the DEFAULT database, i.e. the real
# data/lecgap.db, twice, on 2026-09-29.
#
# This is the same class of mistake tests/conftest.py guards against, and the
# same reason it sets the variable at module scope before any backend import.
if len(sys.argv) != 2:
    print(__doc__)
    raise SystemExit(2)

TARGET = Path(sys.argv[1]).resolve()
LIVE_DB = (REPO / "data" / "lecgap.db").resolve()

# The refusal has to come FIRST — before the env var, before any import, and
# above all before the `unlink` that clears a stale target file. A first version
# of this guard sat *after* the unlink, and pointing the script at the live
# database made it try to DELETE the file; it only failed because a running
# uvicorn held it open. This comparison is pure path arithmetic and cannot
# touch the filesystem.
if TARGET == LIVE_DB:
    raise SystemExit(
        f"REFUSING TO RUN: {TARGET} is the live database.\n"
        "The live test tier must never write to real lecture data. Pass a "
        "path under a temp directory instead."
    )

os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{TARGET}"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.models.db import (  # noqa: E402
    Clip,
    Concept,
    GraphEdge,
    GraphNode,
    Job,
    Lecture,
    LectureLink,
    Passage,
    SessionLocal,
    TranscriptSegment,
    engine,
    init_db,
)


def assert_engine_is_not_the_live_db() -> None:
    """Second refusal: the *bound engine* must not point at real data.

    This is the check that would have caught the original bug. It can only run
    after the import, which is why the path check above has to come first.
    """
    bound = Path(str(engine.url).replace("sqlite:///", "")).resolve()
    if bound == LIVE_DB:
        raise SystemExit(
            f"REFUSING TO RUN: engine bound to {bound}, which is the live "
            "database. LEGCAP_DATABASE_URL did not take effect before the "
            "engine was constructed."
        )
    print(f"  target : {TARGET}")
    print(f"  engine : {bound}")


def seed(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    assert_engine_is_not_the_live_db()
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            stale.unlink()

    init_db()

    with SessionLocal() as db:
        # ---------------------------------------------------------- course ml
        ml1 = Lecture(course_id="ml", title="Linear Regression", status="ready")
        ml2 = Lecture(course_id="ml", title="Multiple Regression", status="ready")
        db.add_all([ml1, ml2])
        db.flush()

        db.add_all(
            [
                TranscriptSegment(lecture_id=ml1.id, idx=0, start_s=0.0, end_s=6.0,
                                  text="A linear regression fits a straight line."),
                TranscriptSegment(lecture_id=ml1.id, idx=1, start_s=6.0, end_s=12.0,
                                  text="The slope is the coefficient on x."),
                TranscriptSegment(lecture_id=ml2.id, idx=0, start_s=0.0, end_s=7.0,
                                  text="Multiple regression takes many features."),
            ]
        )

        p1 = Passage(lecture_id=ml1.id, idx=0, title="Fitting a line",
                     kind="explain", start_s=0.0, end_s=12.0,
                     summary="The core of linear regression.",
                     text="A linear regression fits a straight line to data.")
        db.add(p1)
        db.flush()

        c1 = Concept(course_id="ml", lecture_id=ml1.id, passage_id=p1.id,
                     name="Linear Regression", source="spoken", implicit=0,
                     start_s=0.0, end_s=6.0)
        c2 = Concept(course_id="ml", lecture_id=ml1.id, passage_id=p1.id,
                     name="Slope", source="spoken", implicit=0,
                     start_s=6.0, end_s=12.0)
        c3 = Concept(course_id="ml", lecture_id=ml2.id, passage_id=None,
                     name="Multiple Regression", source="spoken", implicit=0,
                     start_s=0.0, end_s=7.0)
        db.add_all([c1, c2, c3])
        db.flush()

        db.add(LectureLink(lecture_id=ml1.id, source_name="Linear Regression",
                           target_name="Slope", confidence=0.9,
                           evidence="The slope is the coefficient on x."))

        for name in ("Linear Regression", "Slope", "Multiple Regression"):
            db.add(GraphNode(course_id="ml", name=name))
        db.add_all(
            [
                GraphEdge(course_id="ml", source="Linear Regression", target="Slope",
                          confidence=0.9, source_method="transcript",
                          evidence="The slope is the coefficient on x."),
                GraphEdge(course_id="ml", source="Linear Regression",
                          target="Multiple Regression", confidence=0.75,
                          source_method="classifier", evidence=None),
            ]
        )

        # Clips that point at their concepts — the exact shape that made
        # `DELETE FROM concepts` raise IntegrityError on re-extraction. If the
        # FK fix ever regresses, the live re-extract test catches it.
        db.add_all(
            [
                Clip(lecture_id=ml1.id, concept_id=c1.id, concept_name="Linear Regression",
                     start_s=0.0, end_s=6.0, path="clips/1/linear.mp4", ok=1, error=None),
                Clip(lecture_id=ml1.id, concept_id=c2.id, concept_name="Slope",
                     start_s=6.0, end_s=12.0, path="clips/1/slope.mp4", ok=1, error=None),
            ]
        )

        # --------------------------------------------------------- course prob
        prob1 = Lecture(course_id="prob", title="Bayes Theorem", status="ready")
        db.add(prob1)
        db.flush()
        db.add(TranscriptSegment(lecture_id=prob1.id, idx=0, start_s=0.0,
                                 end_s=5.0, text="Bayes theorem inverts a probability."))
        db.add(Concept(course_id="prob", lecture_id=prob1.id, name="Bayes Theorem",
                       source="spoken", implicit=0, start_s=0.0, end_s=5.0))
        db.add(GraphNode(course_id="prob", name="Bayes Theorem"))

        # ------------------------------------------------------------- jobs
        # One settled job, so the feed carries a terminal row in its snapshot
        # (the client diffs snapshots to detect completions), and one IN FLIGHT
        # job, because `useActiveJobs` filters terminal rows out of the drawer —
        # without a running job the drawer can only ever be asserted empty, and
        # "the drawer shows the real job" is the single most valuable end-to-end
        # assertion this tier has: real SSE frame -> parsed -> React Query cache
        # -> visible text.
        db.add(Job(kind="extract", status="ready", course_id="ml", lecture_id=ml1.id,
                   title="Linear Regression", stage="ready", detail="Done.",
                   progress_pct=100, error=None))
        db.add(Job(kind="extract", status="running", course_id="ml", lecture_id=ml2.id,
                   title="Multiple Regression", stage="extracting",
                   detail="Persisting concepts, passages, and spoken links...",
                   progress_pct=70, error=None))
        db.commit()

    print(f"seeded {target}")
    print(f"  lectures=3 concepts=4 edges=2 clips=2 graph_nodes=4 jobs=2 (1 ready, 1 running)")


if __name__ == "__main__":
    seed(TARGET)
