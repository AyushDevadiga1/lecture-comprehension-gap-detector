"""
FastAPI entrypoint.

Run locally with:
    uvicorn backend.main:app --reload
"""

from fastapi import FastAPI

from backend.api import routes
from backend.models.db import init_db

init_db()

app = FastAPI(title="LecGap API")
app.include_router(routes.router)


@app.get("/health")
def health():
    """Basic liveness check."""
    return {"status": "ok", "service": "lecgap-backend"}
