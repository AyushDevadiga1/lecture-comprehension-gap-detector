"""
SQLite persistence layer — sits behind the API, never touched directly by
the frontend (see plan/ARCHITECTURE.md, "Decoupled architecture").

Planned tables (fill in with SQLAlchemy models as each stage is built):

  lectures        — id, course_id, source_path, title, processed_at
  concepts        — id, course_id, name, embedding, source ('spoken'|'visual')
  concept_edges   — id, course_id, from_concept_id, to_concept_id, confidence
  clips           — id, concept_id, lecture_id, file_path, start, end
  quiz_questions  — id, concept_id, question_text, options, correct_option
  quiz_responses  — id, student_id, question_id, chosen_option, correct, ts
  students        — id, name, email
  refinement_log  — id, course_id, round, edge_id, delta_confidence, ts
"""

# TODO (Phase 1 onward, incrementally): define SQLAlchemy models for the
# tables above as each pipeline stage needs them — don't build the full
# schema speculatively up front, add tables as each phase actually needs
# to persist something.
