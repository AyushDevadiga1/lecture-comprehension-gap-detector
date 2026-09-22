"""
P11/L10 — hub model-ID pinning (backend/pipeline/model_ids.py).

Every runtime SentenceTransformer load site must route through the single
pinned model id (env-overridable) and forward the pinned hub revision via
load_kwargs, so the running pipeline can never silently track a moved
HuggingFace artifact.
"""

import numpy as np
import pytest


def test_load_kwargs_revision_scoped_to_pinned_model(monkeypatch):
    from backend.pipeline import model_ids as M

    monkeypatch.setattr(M, "EMBEDDING_REVISION", "abc123")
    assert M.load_kwargs(M.EMBEDDING_MODEL) == {"revision": "abc123"}
    # default arg = the pinned model, so it gets the revision too
    assert M.load_kwargs() == {"revision": "abc123"}
    # an explicit override of the model id keeps full control of its revision
    assert M.load_kwargs("sentence-transformers/all-mpnet-base-v2") == {}

    monkeypatch.setattr(M, "EMBEDDING_REVISION", None)
    assert M.load_kwargs(M.EMBEDDING_MODEL) == {}
    assert M.load_kwargs("sentence-transformers/all-mpnet-base-v2") == {}


def test_default_model_is_the_verified_minilm_id():
    from backend.pipeline.model_ids import EMBEDDING_MODEL

    assert EMBEDDING_MODEL == "sentence-transformers/all-MiniLM-L6-v2"


def test_load_site_defaults_agree_on_pinned_model():
    """build_graph / classify_prerequisites defaults must all point at the
    single pinned model id (no stray hard-coded strings)."""
    from backend.pipeline.build_graph import DEFAULT_EMBEDDING_MODEL
    from backend.pipeline.classify_prerequisites import EMBEDDING_MODEL as CP_MODEL
    from backend.pipeline.model_ids import EMBEDDING_MODEL

    assert DEFAULT_EMBEDDING_MODEL == EMBEDDING_MODEL
    assert CP_MODEL == EMBEDDING_MODEL


def test_classify_load_site_routes_through_pinned_model(monkeypatch):
    """get_candidate_pairs' inline encoder load must hand the pinned model id
    (and revision) to SentenceTransformer."""
    import backend.pipeline.classify_prerequisites as CP
    import backend.pipeline.model_ids as MIDs

    seen = {}

    class FakeST:
        def __init__(self, model_name_or_path, **kwargs):
            seen["model"] = model_name_or_path
            seen["kwargs"] = kwargs

        def encode(self, names, convert_to_tensor=False):
            return np.zeros((max(len(names), 1), 4), dtype=np.float32)

    monkeypatch.setattr(CP, "_st", lambda: (FakeST, None))
    monkeypatch.setattr(MIDs, "EMBEDDING_REVISION", "deadbeef")
    CP.get_candidate_pairs(
        [{"name": "A", "start_s": 0.0}, {"name": "B", "start_s": 5.0}],
        encoder=None,
    )
    assert seen["model"] == MIDs.EMBEDDING_MODEL
    assert seen["kwargs"] == {"revision": "deadbeef"}