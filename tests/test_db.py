"""Schema layer (backend/models/db.py) — creation and additive migration.

Pin the parts the API suites never exercise directly: init_db creating every
model table, and _migrate_schema bringing older databases up to the current
model WITHOUT touching their rows. The migration is metadata-derived (single
schema truth) — these tests make sure it stays faithful to the models, still
adds the classic upgrade columns with their defaults, and skips columns SQLite
cannot add safely to a live table.
"""

from sqlalchemy import create_engine, inspect, text

from backend.models import db as models
from backend.models.db import _migrate_schema


def _cols(engine, table: str) -> set:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_init_db_creates_exactly_the_model_schema(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(models, "engine", engine)

    models.init_db()

    tables = set(inspect(engine).get_table_names())
    assert tables == set(models.Base.metadata.tables)
    # single-truth check: every model column exists, and nothing extra
    for table_name, table in models.Base.metadata.tables.items():
        assert _cols(engine, table_name) == {c.name for c in table.columns}


def test_init_db_is_idempotent_and_migration_is_noop_on_fresh_db(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(models, "engine", engine)

    models.init_db()
    first = {t: _cols(engine, t) for t in inspect(engine).get_table_names()}
    models.init_db()
    second = {t: _cols(engine, t) for t in inspect(engine).get_table_names()}
    assert first == second


def test_migrate_adds_legacy_columns_and_preserves_rows(monkeypatch):
    """Upgrade a pre-Stage-6/8 database: columns appear, rows survive."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE quiz_questions ("
            " id INTEGER PRIMARY KEY, course_id VARCHAR, concept VARCHAR, "
            " question VARCHAR, \"order\" INTEGER)"
        ))
        conn.execute(text(
            "CREATE TABLE concepts ("
            " id INTEGER PRIMARY KEY, course_id VARCHAR, lecture_id INTEGER, "
            " name VARCHAR, source VARCHAR, implicit INTEGER, "
            " start_s FLOAT, end_s FLOAT)"
        ))
        conn.execute(text(
            "CREATE TABLE graph_edges ("
            " id INTEGER PRIMARY KEY, course_id VARCHAR, source VARCHAR, "
            " target VARCHAR, confidence FLOAT)"
        ))
        conn.execute(text(
            "INSERT INTO graph_edges (course_id, source, target, confidence) "
            "VALUES ('c1', 'A', 'B', 0.9)"
        ))
        conn.execute(text(
            "INSERT INTO quiz_questions (course_id, concept, question) "
            "VALUES ('c1', 'A', 'what is A?')"
        ))

    monkeypatch.setattr(models, "engine", engine)
    _migrate_schema()

    assert {"answer", "explanation", "rationale_a", "rationale_b", "rationale_c"} <= _cols(engine, "quiz_questions")
    assert "passage_id" in _cols(engine, "concepts")
    assert {"source_method", "evidence"} <= _cols(engine, "graph_edges")

    with engine.connect() as conn:
        row = conn.execute(text("SELECT source_method, evidence FROM graph_edges WHERE id = 1")).fetchone()
        assert row == ("classifier", None)  # server default applied, data kept
        q = conn.execute(text("SELECT concept, question FROM quiz_questions WHERE id = 1")).fetchone()
        assert q == ("A", "what is A?")


def test_migrate_is_idempotent(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE graph_edges (id INTEGER PRIMARY KEY, source VARCHAR, target VARCHAR)"
        ))
    monkeypatch.setattr(models, "engine", engine)
    _migrate_schema()
    runner = _cols(engine, "graph_edges")
    _migrate_schema()
    assert _cols(engine, "graph_edges") == runner


def test_migrate_skips_not_null_column_without_default(monkeypatch):
    """A NOT NULL column with no server default can't be backfilled — skip it."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        # old lectures table missing `title` (NOT NULL, no server default)
        conn.execute(text(
            "CREATE TABLE lectures (id INTEGER PRIMARY KEY, course_id VARCHAR, status VARCHAR)"
        ))
    monkeypatch.setattr(models, "engine", engine)
    _migrate_schema()  # must not raise
    assert "title" not in _cols(engine, "lectures")


def test_migrate_creates_nothing_on_unrelated_tables(monkeypatch):
    """Tables not in the model aren't invented or altered."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE random_table (id INTEGER PRIMARY KEY)"))
    monkeypatch.setattr(models, "engine", engine)
    _migrate_schema()
    assert _cols(engine, "random_table") == {"id"}