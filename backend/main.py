"""
FastAPI entrypoint.

Run locally with:
    uvicorn backend.main:app --reload
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from backend.api import routes
from backend.models.db import init_db
from backend.pipeline.llm import backend_status

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

init_db()

app = FastAPI(title="LecGap API")
app.include_router(routes.router)


@app.get("/health")
def health():
    """Basic liveness check + which LLM backends are usable right now."""
    return {
        "status": "ok",
        "service": "lecgap-backend",
        "llm_backends": backend_status(),
    }
