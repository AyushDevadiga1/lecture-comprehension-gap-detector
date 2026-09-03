"""Seed a fresh smoke-test DB (data/smoke_lecgap.db) for live-UI smoke testing.

Reuses the real 13-concept course `ml` (names/timestamps from the dev DB) and
cuts ONE real clip from the existing lecture 2 media, so the UI's
st.video(remediation clip) path can be verified against a real file.

Wipes data/smoke_lecgap.db first. Does NOT touch data/lecgap.db.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "smoke_lecgap.db"
MEDIA = REPO / "data" / "raw" / "lec2__smoketest_3min.mp4"
CLIP_DIR = REPO / "data" / "processed" / "clips" / "9999"

# The 13 real concepts extracted from the CampusX MLR lecture (course 'ml').
CONCEPTS = [
    "Multiple Linear Regression", "Simple Linear Regression", "Independent Variables",
    "Dependent Variable", "Linear Model", "Model Coefficients",
    "Intercept (Bias Term)", "Extension of Simple to Multiple Regression",
    "Specialization of Multiple to Simple Regression", "High-Dimensional Data",
    "Prediction", "Input Columns", "Output Column",
]

# A small, real prerequisite structure over those concepts for course 'ml'.
EDGES = [
    ("Simple Linear Regression", "Multiple Linear Regression", 0.9),
    ("Independent Variables", "Multiple Linear Regression", 0.8),
    ("Dependent Variable", "Multiple Linear Regression", 0.8),
    ("Linear Model", "Model Coefficients", 0.7),
    ("Model Coefficients", "Prediction", 0.6),
    ("Input Columns", "Output Column", 0.7),
]


def main() -> None:
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE lectures (
            id INTEGER PRIMARY KEY, course_id TEXT NOT NULL, title TEXT NOT NULL,
            source_path TEXT, status TEXT NOT NULL DEFAULT 'uploaded',
            error TEXT, created_at TEXT, processed_at TEXT);
        CREATE TABLE transcript_segments (
            id INTEGER PRIMARY KEY, lecture_id INTEGER NOT NULL,
            idx INTEGER, start_s REAL, end_s REAL, text TEXT);
        CREATE TABLE concepts (
            id INTEGER PRIMARY KEY, course_id TEXT, lecture_id INTEGER,
            name TEXT, source TEXT, implicit INTEGER,
            start_s REAL, end_s REAL, created_at TEXT);
        CREATE TABLE graph_nodes (
            id INTEGER PRIMARY KEY, course_id TEXT, name TEXT, created_at TEXT);
        CREATE TABLE graph_edges (
            id INTEGER PRIMARY KEY, course_id TEXT, source TEXT, target TEXT,
            confidence REAL, created_at TEXT);
        CREATE TABLE clips (
            id INTEGER PRIMARY KEY, lecture_id INTEGER, concept_id INTEGER,
            concept_name TEXT, start_s REAL, end_s REAL, path TEXT,
            ok INTEGER, error TEXT, created_at TEXT);
        CREATE TABLE quiz_questions (
            id INTEGER PRIMARY KEY, course_id TEXT, concept TEXT,
            question TEXT, distractor_a TEXT, distractor_b TEXT,
            distractor_c TEXT, "order" INTEGER, created_at TEXT);
        CREATE TABLE quiz_responses (
            id INTEGER PRIMARY KEY, course_id TEXT, student_id TEXT,
            question_id INTEGER, concept TEXT, selected TEXT, correct INTEGER,
            latency_s REAL, attempt INTEGER, created_at TEXT);
        """
    )

    # Lecture 2 -> course 'ml', pointing at the real media so a clip can be cut.
    cur.execute(
        "INSERT INTO lectures (id, course_id, title, source_path, status, created_at) "
        "VALUES (2, 'ml', 'smoke lecture', ?, 'ready', datetime('now'))",
        (str(MEDIA),),
    )
    for i, name in enumerate(CONCEPTS):
        cur.execute(
            "INSERT INTO concepts (course_id, lecture_id, name, start_s, end_s) "
            "VALUES ('ml', 2, ?, 30.0, 179.8)",
            (name,),
        )
        if name == "Simple Linear Regression":
            simple_concept_id = cur.lastrowid

    for src, tgt, conf in EDGES:
        cur.execute(
            "INSERT INTO graph_nodes (course_id, name) VALUES ('ml', ?)", (src,))
        cur.execute(
            "INSERT INTO graph_nodes (course_id, name) VALUES ('ml', ?)", (tgt,))
        cur.execute(
            "INSERT INTO graph_edges (course_id, source, target, confidence) "
            "VALUES ('ml', ?, ?, ?)",
            (src, tgt, conf),
        )

    # Cut ONE real 3-second clip from the media for the remediation playback path.
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    clip_path = CLIP_DIR / "Simple Linear Regression__30-179.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", "30", "-to", "179.8", "-i", str(MEDIA),
         "-c", "copy", str(clip_path)],
        capture_output=True,
    )
    ok = r.returncode == 0 and clip_path.exists()
    cur.execute(
        "INSERT INTO clips (lecture_id, concept_id, concept_name, start_s, end_s, "
        "path, ok) VALUES (2, ?, 'Simple Linear Regression', 30.0, 179.8, ?, ?)",
        (simple_concept_id, str(clip_path), int(ok)),
    )
    conn.commit()
    conn.close()

    print("seeded smoke DB:", DB)
    print("  lectures: 1 (course 'ml', ready)")
    print(f"  concepts: {len(CONCEPTS)}")
    print(f"  graph edges: {len(EDGES)}")
    print(f"  clip ok={ok}: {clip_path if ok else '(FAILED)'}")


if __name__ == "__main__":
    main()
