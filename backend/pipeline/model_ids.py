"""
Model-ID pinning (P11/L10).

The hub identifiers below are the single source of truth for which encoder the
pipeline loads off HuggingFace, so a deployment can fix one model name *and*
one commit revision instead of silently tracking a moving hub artifact. Both
are env-overridable:

  LECGAP_EMBEDDING_MODEL    e.g. "sentence-transformers/all-mpnet-base-v2"
  LECGAP_EMBEDDING_REVISION e.g. "<git commit sha>" — empty by default; set it
                            to freeze the exact hub snapshot (reproducible,
                            CVE-stable pinning rather than latest-at-runtime).

Every runtime ``SentenceTransformer(...)`` load site routes through these two
values (see ``load_kwargs``), so the running pipeline never silently switches
to a moved hub artifact.
"""

from backend.config import EMBEDDING_MODEL, EMBEDDING_REVISION


def load_kwargs(model: str = None) -> dict:
    """Keyword args to forward to a ``SentenceTransformer(...)`` load site.

    The pinned hub revision is applied only when the model being loaded IS the
    pinned model; a caller that deliberately overrides the model id keeps
    control of its own revision. Empty by default so the load behaves exactly
    as before unless an operator opts into revision pinning.
    """
    if (model or EMBEDDING_MODEL) == EMBEDDING_MODEL and EMBEDDING_REVISION:
        return {"revision": EMBEDDING_REVISION}
    return {}