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
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from backend import config
from backend.api import routes
from backend.models.db import init_db
from backend.pipeline.llm import backend_status, backend_status_detailed

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

init_db()

# Engine 2 / C2: a job left `running` by a previous process is not running any
# more. Marking it `orphaned` here is what stops the UI polling a progress
# value that can never change again after a restart.
try:
    from backend.api.job_registry import recover_orphans

    recover_orphans()
except Exception as _exc:  # noqa: BLE001 - never block startup on recovery
    logging.getLogger("lecgap.main").warning("orphan recovery failed: %s", _exc)

app = FastAPI(title="LecGap API")

# ------------------------------------------------------------------ CORS (C4)
# The React dev server (Vite) runs on port 5173.  A browser will refuse all
# API calls if the backend doesn't return the correct Access-Control-* headers.
# In production, replace the allow-list with your actual origin(s) via the
# LECGAP_CORS_ORIGINS env var (comma-separated, no trailing slash).
_CORS_ORIGINS_DEFAULT = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("LECGAP_CORS_ORIGINS", _CORS_ORIGINS_DEFAULT).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges"],
)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    """API key verification when LECGAP_API_KEY is configured.

    When unset, requests pass through unhindered for seamless local development
    and test runs. When set, verifies X-API-Key or Bearer token against the
    configured secret using constant-time comparison.
    """
    api_key = config.api_key()
    if api_key:
        exempt_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
        if (
            request.url.path not in exempt_paths
            and not request.url.path.startswith("/media/")
        ):
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
