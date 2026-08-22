"""
API routes — the Streamlit frontend talks to the pipeline only through
these, never by importing backend/pipeline/* directly.
"""

# TODO: as each pipeline stage becomes real, add an endpoint here, e.g.
#   POST /lectures            -> ingest + kick off transcription
#   GET  /lectures/{id}/graph -> current concept graph for a course
#   POST /quiz/submit         -> record a response, trigger remediation
#   GET  /dashboard/{course}  -> faculty confusion heatmap + divergence
