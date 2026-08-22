"""
Stage 4 — Graph Construction
See plan/ARCHITECTURE.md, Stage 4.

Confirmed prerequisite pairs become a directed graph (NetworkX), scoped
per-course (not global — see plan/LIMITATIONS.md).

  add_concepts_to_graph(graph, concepts)   -> dedup via embedding
                                               similarity before adding
                                               new nodes.

  add_edge(graph, a, b, confidence)        -> adds a prerequisite edge;
                                               resolve cycles via
                                               confidence-weighted
                                               topological sort.
"""

# TODO (Phase 4): implement using networkx.DiGraph. Persist the graph
# per-course in backend/models/db.py (nodes/edges tables), not as a
# pickled file, so the refinement loop (Stage 7) can update it safely.
