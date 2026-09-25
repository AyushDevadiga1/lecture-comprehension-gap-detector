"""
API routes, grouped by resource domain.

The Streamlit frontend talks to the pipeline only through these, never by
importing backend/pipeline/* directly. Endpoint modules hold request->schema->
job glue only; the long-running jobs, shared DB helpers, and Pydantic models
live in backend/api/jobs/* + backend/api/queries.py / schemas.py.

Endpoints:
    lectures.py   — upload/media lifecycle, concept extraction, clips
    courses.py    — per-course prerequisite graph + faculty stats
    quizzes.py    — graded MCQs, submit/grade, remediation sequence

This package aggregates the per-domain routers into one `router` so
backend.main includes a single surface (app.include_router(routes.router)).
"""

from fastapi import APIRouter

from backend.api.routes.courses import router as courses_router
from backend.api.routes.lectures import router as lectures_router
from backend.api.routes.media import router as media_router
from backend.api.routes.quizzes import router as quizzes_router
from backend.api.routes.usage import router as usage_router

router = APIRouter()
router.include_router(lectures_router)
router.include_router(courses_router)
router.include_router(quizzes_router)
router.include_router(media_router)
router.include_router(usage_router)

__all__ = ["router"]