"""Contract gate — the shape of the HTTP surface, pinned.

C4's missing half. `plan/FRONTEND_API_CONTRACT.md` is a document; this asserts
it. Without it, drift is discovered by a client at runtime as an `undefined`,
which is exactly the failure mode the typed client was supposed to prevent.

Three things are pinned:

  1. **No filesystem path in a payload.** REACT_ARCHITECTURE.md §3: "a payload
     containing a filesystem path is a *contract test failure*, not a runtime
     surprise". `ClipOut.path` is the one deliberate exception and is asserted
     as such; everything else is swept.
  2. **The answer key never ships.** `SECURITY_AUDIT` answer-key leak: a
     `QuizQuestionOut` must not carry `answer`, `correct` or a distractor's
     rationale keyed by id.
  3. **Every documented endpoint exists, with the documented method.** The
     contract table in §2 and the OpenAPI schema must agree, in both
     directions -- a route nobody documented is as much a drift as a documented
     route that vanished.
"""

import pytest
from fastapi.routing import APIRoute

from backend.main import app
from backend.api.schemas import ClipOut, QuizQuestionOut


# --------------------------------------------------------------------- helpers

def _schema() -> dict:
    return app.openapi()


def _routes() -> set:
    """{(METHOD, path)} for every served endpoint.

    Read from the OpenAPI schema rather than ``app.routes``: current FastAPI
    nests ``include_router`` behind a ``_IncludedRouter``, so walking
    ``app.routes`` does not reach the domain routes at all. The schema is the
    canonical description of the HTTP surface anyway -- it is what a generated
    client is built from.
    """
    out = set()
    for path, operations in _schema()["paths"].items():
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                out.add((method.upper(), path))
    return out


def _response_schema(operations: dict, method: str):
    responses = operations[method].get("responses", {})
    for code in ("200", "201", "202", "206"):
        r = responses.get(code)
        if not r:
            continue
        content = (r.get("content") or {}).get("application/json")
        if content:
            return content["schema"]
    return None


def _walk_strings(node):
    """Every string value anywhere in a JSON-ish structure."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_strings(v)


# A path that is unmistakably a server filesystem location. Deliberately does
# not match a URL: the value must start at a filesystem root or a known
# data-directory segment.
_FS_MARKERS = ("data/processed", "data/raw", "data\\processed", "data\\raw", "/home/", "C:\\")


def _looks_like_fs_path(value: str) -> bool:
    return any(m in value for m in _FS_MARKERS)


# ------------------------------------------------------------------- the routes

#: The contract's §2 surface, as (method, path). `plan/FRONTEND_API_CONTRACT.md`.
#: Path-parameter names are the app's; the doc writes them as `{id}` in prose.
CONTRACT_ROUTES = [
    # reads
    ("GET", "/courses"),
    ("GET", "/lectures"),
    ("GET", "/lectures/{lecture_id}"),
    ("GET", "/lectures/{lecture_id}/progress"),
    ("GET", "/lectures/{lecture_id}/clips"),
    ("GET", "/courses/{course_id}/graph"),
    ("GET", "/courses/{course_id}/stats"),
    ("GET", "/courses/{course_id}/snapshot"),
    ("GET", "/quizzes"),
    ("GET", "/students/{student_id}/remediation"),
    ("GET", "/usage"),
    ("GET", "/health"),
    # media
    ("GET", "/media/clips/{lecture_id}/{filename}"),
    # writes
    ("POST", "/lectures"),
    ("PUT", "/lectures/{lecture_id}/media"),
    ("POST", "/lectures/{lecture_id}/concepts"),
    ("POST", "/lectures/{lecture_id}/clips"),
    ("POST", "/lectures/{lecture_id}/rerun"),
    ("POST", "/courses/{course_id}/graph"),
    ("POST", "/quizzes"),
    ("POST", "/quizzes/jobs"),
    ("POST", "/quizzes/submit"),
    ("DELETE", "/courses/{course_id}"),
    ("DELETE", "/lectures/{lecture_id}"),
    # jobs (Engine 2 / C2)
    ("GET", "/jobs"),
    ("GET", "/jobs/stream"),
    ("GET", "/jobs/{job_id}"),
    ("POST", "/jobs/{job_id}/cancel"),
]


class TestContractSurface:
    def test_every_documented_route_exists(self):
        """A route the contract documents but the app lacks is drift."""
        live = _routes()
        missing = [r for r in CONTRACT_ROUTES if r not in live]
        assert missing == [], f"documented in the contract but not served: {missing}"

    def test_no_undocumented_route_shipped(self):
        """A route nobody documented is drift the other way."""
        live = _routes()
        # OpenAPI/HTTP infrastructure and the LLM probe are not part of the
        # frontend contract: /health is, the rest are not payload surfaces.
        not_contract = {
            "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
            "/llm/backends",
        }
        extra = {
            r for r in live
            if r not in set(CONTRACT_ROUTES) and r[1] not in not_contract
        }
        assert extra == set(), f"served but not in the contract: {sorted(extra)}"

    def test_every_json_route_declares_a_response_schema(self):
        """A route with no declared schema serialises ad hoc, so it can drift."""
        schema = _schema()["paths"]
        stream_like = {"/jobs/stream", "/media/clips/{lecture_id}/{filename}"}
        undocumented = []
        for path, operations in schema.items():
            if path in stream_like:
                continue
            for method, op in operations.items():
                if method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    continue
                if _response_schema(operations, method) is None:
                    undocumented.append(f"{method.upper()} {path}")
        assert undocumented == [], undocumented


class TestNoFilesystemPaths:
    def test_clip_out_carries_a_url(self):
        """ClipOut.path is the one sanctioned exception, and url must exist."""
        fields = ClipOut.model_fields
        assert "url" in fields
        c = ClipOut(id=1, lecture_id=7, concept_name="A", start_s=0, end_s=1,
                    path="data/processed/clips/7/a.mp4", ok=True)
        assert c.url == "/media/clips/7/a.mp4"

    def test_media_url_helper_agrees_with_the_schema(self):
        """One place builds URLs; the other must not drift from it."""
        from backend.api.queries import clip_media_url
        for path, lid in [
            ("data/processed/clips/7/a.mp4", 7),
            ("clips/12/some name.mp4", 12),
            ("/abs/clips/3/x.mp4", 3),
        ]:
            schema = ClipOut(id=1, lecture_id=lid, concept_name="A", start_s=0,
                             end_s=1, path=path, ok=True).url
            assert clip_media_url(path, lid) == schema

    def test_no_response_schema_exposes_a_filesystem_path(self):
        """Sweep every declared schema for a path-shaped default or example."""
        schema = _schema()["components"]["schemas"]
        offenders = []
        for name, definition in schema.items():
            if name == "ClipOut":
                continue  # `path` is the documented exception
            for value in _walk_strings(definition):
                if _looks_like_fs_path(value):
                    offenders.append(f"{name}: {value}")
        assert offenders == [], offenders

    def test_clips_by_concept_returns_urls(self):
        from backend.api.queries import clip_media_url
        assert clip_media_url("data/processed/clips/5/x.mp4", 5) == "/media/clips/5/x.mp4"
        # A path with no lecture id cannot form a URL, so it must yield None
        # rather than a broken link.
        assert clip_media_url("x.mp4", None) is None
        assert clip_media_url(None, 5) is None


class TestNoAnswerKey:
    def test_quiz_question_out_has_no_answer_field(self):
        assert "answer" not in QuizQuestionOut.model_fields
        assert "correct" not in QuizQuestionOut.model_fields

    def test_quiz_question_out_serialises_no_answer(self):
        q = QuizQuestionOut(id=1, concept="A", question="q?", options=["a", "b"])
        assert "answer" not in q.model_dump()

    def test_the_read_endpoint_does_not_grade(self):
        """GET /quizzes is a read; grading belongs to submit."""
        spec = _schema()["paths"]["/quizzes"]["get"]
        assert spec["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/QuizOut"
        )
