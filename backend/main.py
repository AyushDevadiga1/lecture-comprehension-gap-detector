"""
FastAPI entrypoint.

Run locally with:
    uvicorn backend.main:app --reload
"""

from fastapi import FastAPI

from backend.api import routes  # noqa: F401  (router included below once routes.py defines one)

app = FastAPI(title="LecGap API")


@app.get("/health")
def health():
    """Basic liveness check — confirms the backend is up before wiring in real routes."""
    return {"status": "ok", "service": "lecgap-backend"}


# TODO: once backend/api/routes.py defines an APIRouter, include it here:
#   app.include_router(routes.router)
