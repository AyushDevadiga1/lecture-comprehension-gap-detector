"""
Stage 4 — Graph Construction
See plan/ARCHITECTURE.md, Stage 4.

Confirmed prerequisite pairs become a directed graph (NetworkX), scoped
per-course (not global — see plan/LIMITATIONS.md).

  ConceptGraph.add_concepts(names)     -> dedup via embedding similarity
                                          before adding new nodes; returns the
                                          canonical (possibly merged) name for
                                          each input name.
  ConceptGraph.add_edge(a, b, conf)    -> adds a prerequisite edge, resolving
                                          both endpoints through the dedup map
                                          and keeping the highest confidence on
                                          re-adds.
  ConceptGraph.resolve_cycles()        -> drops the lowest-confidence edge in
                                          each cycle until the graph is a DAG
                                          (confidence-weighted cycle resolution).
  ConceptGraph.topological_order()     -> learner order of the acyclic graph.

The graph only ever contains concepts that appeared in a course's ingested
lectures (no universal concept bank). Graph is persisted per-course in
backend/models/db.py (graph_nodes / graph_edges rows), never as a pickled
file, so the refinement loop (Stage 7) can swap edges safely.
"""

import networkx as nx
import numpy as np

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEDUP_THRESHOLD = 0.85


class ConceptGraph:
    """Per-course prerequisite DAG with embedding-based node deduplication.

    Nodes are concept names; an edge A -> B means "A must be understood
    before B" and carries the classifier's confidence. Methods mutate the
    graph in place; callers own the ordering (add_concepts first, then
    add_edge), then resolve_cycles / topological_order.
    """

    def __init__(
        self,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        dedup_threshold: float = DEDUP_THRESHOLD,
    ) -> None:
        self._g = nx.DiGraph()
        self.embedding_model = embedding_model
        self.dedup_threshold = dedup_threshold
        self._encoder = None
        self._vec_cache: dict = {}
        self._canon: dict = {}  # raw name -> canonical node name
        self.removed_edges = []  # [(source, target, confidence)] from resolve_cycles

    # ------------------------------------------------------------------ nodes

    def _get_encoder(self):
        from sentence_transformers import SentenceTransformer

        if self._encoder is None:
            self._encoder = SentenceTransformer(self.embedding_model)
        return self._encoder

    def _vec(self, name: str) -> np.ndarray:
        if name not in self._vec_cache:
            enc = self._get_encoder()
            v = enc.encode([name], convert_to_tensor=False)
            self._vec_cache[name] = np.asarray(v[0], dtype=np.float32)
        return self._vec_cache[name]

    def add_concepts(self, names) -> list:
        """Add concept nodes, deduping against existing nodes via embedding
        similarity (cosine >= dedup_threshold) so "Gradient Descent" and
        "GD optimization" from different lectures collapse into one node.

        Returns one canonical name per input name (same order/length), which
        callers should reuse when adding edges.
        """
        canonical = []
        for raw in names:
            name = str(raw).strip()
            if not name:
                canonical.append("")
                continue
            if name in self._canon:
                canonical.append(self._canon[name])
                continue

            vec = self._vec(name)
            target = name
            for node in self._g.nodes:
                if node == name:
                    continue
                if _cosine(vec, self._vec(node)) >= self.dedup_threshold:
                    target = node
                    break
            self._canon[name] = target
            if target == name:
                self._g.add_node(name)
            canonical.append(target)
        return canonical

    def nodes(self) -> list:
        return list(self._g.nodes)

    @property
    def node_count(self) -> int:
        return self._g.number_of_nodes()

    # ------------------------------------------------------------------ edges

    def _resolve(self, name) -> str:
        name = str(name).strip()
        return self._canon.get(name, name) if name else ""

    def add_edge(self, a, b, confidence) -> None:
        """Add a prerequisite edge A -> B with a confidence weight.

        Both endpoints are resolved through the dedup map built by
        add_concepts, so edges written against raw lecture names still land on
        canonical nodes, and a pair that collapses to the same node (after
        dedup) is dropped rather than becoming a self-loop. Re-added edges
        keep the highest confidence seen so far.
        """
        a, b = self._resolve(a), self._resolve(b)
        if not a or not b or a == b:
            return
        if not self._g.has_node(a):
            self._g.add_node(a)
        if not self._g.has_node(b):
            self._g.add_node(b)
        confidence = float(confidence)
        if self._g.has_edge(a, b):
            self._g[a][b]["confidence"] = max(
                self._g[a][b]["confidence"], confidence
            )
        else:
            self._g.add_edge(a, b, confidence=confidence)

    def edges(self) -> list:
        return [
            {"source": u, "target": v, "confidence": d["confidence"]}
            for u, v, d in self._g.edges(data=True)
        ]

    @property
    def edge_count(self) -> int:
        return self._g.number_of_edges()

    # ------------------------------------------------------- cycle resolution

    @property
    def is_dag(self) -> bool:
        return nx.is_directed_acyclic_graph(self._g)

    def add_concepts_verbatim(self, names) -> list:
        """Add names as nodes WITHOUT re-running embedding dedup.

        For reloads from the persisted graph (nodes are already canonical
        post-dedup), so no model load is needed just to re-add them.
        """
        canonical = []
        for raw in names:
            name = str(raw).strip()
            if not name:
                canonical.append("")
                continue
            self._canon[name] = name
            if not self._g.has_node(name):
                self._g.add_node(name)
            canonical.append(name)
        return canonical

    def resolve_cycles(self) -> list:
        """Break every cycle by removing its lowest-confidence edge.

        Cycles are found one at a time (feedback-ish arc set: each pass drops
        only the weakest edge actually on a cycle, keeping high-confidence
        prerequisites even when they are part of a conflict).
        """
        removed = []
        while not self.is_dag:
            try:
                cycle = nx.find_cycle(self._g)
            except nx.NetworkXNoCycle:
                break
            u, v = min(
                cycle,
                key=lambda e: self._g[e[0]][e[1]]["confidence"],
            )
            removed.append((u, v, self._g[u][v]["confidence"]))
            self._g.remove_edge(u, v)
        self.removed_edges = removed
        return removed

    def topological_order(self) -> list:
        """Learner order of the graph; auto-resolves any remaining cycles first."""
        if not self.is_dag:
            self.resolve_cycles()
        return list(nx.topological_sort(self._g))

    # ------------------------------------------------------------- utilities

    def to_networkx(self) -> "nx.DiGraph":
        return self._g

    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes(),
            "edges": self.edges(),
            "removed_edges": self.removed_edges,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "is_dag": self.is_dag,
            "topological_order": self.topological_order(),
        }


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(
        np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)
    )


def build_graph_from_pairs(
    names,
    pairs,
    *,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    dedup_threshold: float = DEDUP_THRESHOLD,
) -> "tuple[ConceptGraph, list]":
    """Thin convenience for the API worker: dedup `names` into nodes, add
    `pairs` (each (A, B, confidence)) as edges, and resolve any cycles.

    Returns (graph, removed_edges).
    """
    graph = ConceptGraph(
        embedding_model=embedding_model, dedup_threshold=dedup_threshold
    )
    graph.add_concepts(names)
    for a, b, confidence in pairs:
        graph.add_edge(a, b, confidence)
    removed = graph.resolve_cycles()
    return graph, removed