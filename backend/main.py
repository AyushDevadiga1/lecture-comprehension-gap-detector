"""
FastAPI entrypoint.

Run locally with:
    uvicorn backend.main:app --reload
"""

import logging
import os
from pathlib import Path
import secrets

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from backend.api import routes
from backend.models.db import init_db
from backend.pipeline.llm import backend_status, backend_status_detailed

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

init_db()

app = FastAPI(title="LecGap API")


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    """API key verification when LECGAP_API_KEY is configured.

    When unset, requests pass through unhindered for seamless local development
    and test runs. When set, verifies X-API-Key or Bearer token against the
    configured secret using constant-time comparison.
    """
    api_key = os.getenv("LECGAP_API_KEY", "").strip()
    if api_key:
        exempt_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
        if request.url.path not in exempt_paths:
            client_key = request.headers.get("X-API-Key")
            if not client_key:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    client_key = auth_header[7:].strip()
            if not client_key or not secrets.compare_digest(client_key, api_key):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


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
    """Basic liveness check. Public: reports only aggregate LLM availability,
    never provider/model names or which secrets are configured (#15)."""
    return {
        "status": "ok",
        "service": "lecgap-backend",
        "llm_backends": backend_status(),
    }


@app.get("/llm/backends")
def llm_backends():
    """Detailed backend/config probe. Kept off the public /health payload and,
    when LECGAP_API_KEY is set, guarded by the auth middleware (#15)."""
    return {"llm_backends": backend_status_detailed()}
