"""
FastAPI entrypoint.

Run locally with:
    uvicorn backend.main:app --reload
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from backend.api import routes
from backend.models.db import init_db
from backend.pipeline.llm import backend_status

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

init_db()

app = FastAPI(title="LecGap API")
app.include_router(routes.router)

_LOGGER = logging.getLogger("lecgap.main")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """M2: never echo unhandled exception internals to the client — log the
    full detail server-side and return a generic 500."""
    _LOGGER.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    """Basic liveness check + which LLM backends are usable right now."""
    return {
        "status": "ok",
        "service": "lecgap-backend",
        "llm_backends": backend_status(),
    }
