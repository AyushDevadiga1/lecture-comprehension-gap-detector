"""
Generate an interactive dependency + milestone graph for the project.

Produces data/processed/project_graph.html (git-ignored) showing:
  - Python modules and their import dependencies (edges)
  - Which roadmap phase each module belongs to
  - Implementation status, derived from the source itself (a module counts
    as implemented unless its code still carries stub markers like "# TODO"
    or "stub" comments) — so the graph stops going stale by hand.

Usage: python scripts/make_project_graph.py
"""

import sys
from pathlib import Path

import networkx as nx
from pyvis.network import Network

REPO = Path(__file__).resolve().parents[1]

# module -> (phase label, hex color)
MODULES = {
    "backend.main": ("API entrypoint", "#00bcd4"),
    "backend.api.routes": ("API layer", "#9c27b0"),
    "backend.models.db": ("Data layer", "#009688"),
    "backend.pipeline.llm": ("LLM access layer", "#ff9800"),
    "backend.pipeline.transcribe": ("Phase 1", "#4caf50"),
    "backend.pipeline.extract_concepts": ("Phase 2 (+2b)", "#2196f3"),
    "backend.pipeline.fine_tune": ("Phase 3 infra", "#795548"),
    "backend.pipeline.classify_prerequisites": ("Phase 3", "#8bc34a"),
    "backend.pipeline.build_graph": ("Phase 4", "#8bc34a"),
    "backend.pipeline.segment_clips": ("Phase 5", "#8bc34a"),
    "backend.pipeline.quiz": ("Phase 6", "#8bc34a"),
    "backend.pipeline.refine": ("Phase 7", "#8bc34a"),
    "frontend.app": ("Frontend shell", "#3f51b5"),
}

# Markers that mean "this module is still being built" (kept minimal so the
# graph auto-flips to green as phases finish).
STUB_MARKERS = ("# TODO", "stub", "not yet implemented", "placeholder")


def _is_stub(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    return any(m in text for m in STUB_MARKERS)


def extract_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("from ") or s.startswith("import "):
            if s.startswith("from"):
                parts = s.split(None, 2)
                if len(parts) >= 2:
                    imports.add(parts[1])
            else:
                parts = s.split(None, 2)
                if len(parts) >= 2:
                    imports.add(parts[1].split(".")[0])
    return imports


def main() -> None:
    g = nx.DiGraph()
    for mod, (phase, color) in MODULES.items():
        path = REPO / Path(*mod.split(".")).with_suffix(".py")
        istub = not path.exists() or _is_stub(path)
        g.add_node(mod, phase=phase, color=color, istub=istub)

    # infer internal edges from `from backend.x.y import ...` / `import backend.x`
    for path in REPO.rglob("*.py"):
        if ".git" in path.parts or "scripts" in str(path):
            continue
        rel = path.relative_to(REPO).with_suffix("")
        key = str(rel).replace("\\", ".")
        if key not in g:
            continue
        for imp in extract_imports(path):
            if not imp.startswith("backend"):
                continue
            if imp in g and imp != key:
                g.add_edge(key, imp)
            else:
                # import of a submodule (e.g. `import backend.api`) — link to
                # the deepest known module we actually have.
                prefixes = [p for p in g if key != p and (imp + ".").startswith(p + ".")]
                for p in prefixes:
                    g.add_edge(key, p)

    net = Network(height="750px", width="100%", directed=True, notebook=False)
    net.bgcolor = "#ffffff"
    for mod, data in g.nodes(data=True):
        status = "IMPLEMENTED" if not data["istub"] else "STUB/PLANNED"
        net.add_node(
            mod,
            label=mod,
            color=data["color"] if not data["istub"] else "#f44336",
            borderWidth=2,
            borderWidthSelected=3,
            shape="box",
            title=f"Phase: {data['phase']}\nStatus: {status}",
        )
    for a, b in g.edges():
        net.add_edge(a, b, arrows="to")

    out = REPO / "data" / "processed" / "project_graph.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(out))
    stubs = [m for m, d in g.nodes(data=True) if d["istub"]]
    print("wrote", out)
    print("modules:", g.number_of_nodes(), "| edges:", g.number_of_edges())
    print("still stubs:", ", ".join(stubs) if stubs else "none")


if __name__ == "__main__":
    main()
    sys.exit(0)