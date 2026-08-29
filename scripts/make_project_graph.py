"""
Generate an interactive dependency + milestone graph for the project.

Produces data/processed/project_graph.html (git-ignored) showing:
  - Python modules and their import dependencies (edges)
  - Which roadmap phase each module belongs to
  - Build progress per phase

Usage: python scripts/make_project_graph.py
"""

import sys
from pathlib import Path

import networkx as nx
from pyvis.network import Network

REPO = Path(__file__).resolve().parents[1]

# module -> roadmap phase
PHASES = {
    "backend.main": "Phase 1/2 API",
    "backend.api.routes": "API layer",
    "backend.models.db": "Data layer",
    "backend.pipeline.llm": "LLM access layer",
    "backend.pipeline.transcribe": "Phase 1",
    "backend.pipeline.extract_concepts": "Phase 2",
    "backend.pipeline.classify_prerequisites": "Phase 3 (stub)",
    "backend.pipeline.build_graph": "Phase 4 (stub)",
    "backend.pipeline.segment_clips": "Phase 5 (stub)",
    "backend.pipeline.refine": "Phase 7 (stub)",
    "frontend.app": "Frontend shell",
}

DONE = {"Phase 1", "Phase 2", "LLM access layer", "API layer", "Data layer",
        "Phase 1/2 API", "Frontend shell"}


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
    for mod, phase in PHASES.items():
        g.add_node(mod, phase=phase)

    # infer internal edges from `from backend.x.y import ...` / `import backend.x`
    for path in REPO.rglob("*.py"):
        if ".git" in path.parts or "scripts" in str(path):
            continue
        rel = path.relative_to(REPO).with_suffix("")
        key = str(rel).replace("\\", ".")
        if key not in g:
            continue
        for imp in extract_imports(path):
            if imp.startswith("backend"):
                candidates = [m for m in g if m == imp or m.startswith(imp + ".")]
                target_mod = imp
                if not any(m == imp for m in g):
                    continue
                if target_mod in g and target_mod != key:
                    g.add_edge(key, target_mod)

    # phase-level collapsing too complex for now; render module graph
    net = Network(height="750px", width="100%", directed=True, notebook=False)
    net.bgcolor = "#ffffff"
    colors = {
        "Phase 1": "#4caf50", "Phase 2": "#2196f3", "LLM access layer": "#ff9800",
        "API layer": "#9c27b0", "Data layer": "#009688", "Phase 1/2 API": "#00bcd4",
        "Frontend shell": "#795548", "Phase 3 (stub)": "#f44336",
        "Phase 4 (stub)": "#f44336", "Phase 5 (stub)": "#f44336",
        "Phase 7 (stub)": "#f44336",
    }
    for mod, data in g.nodes(data=True):
        phase = data["phase"]
        done = phase in DONE
        net.add_node(
            mod,
            label=mod,
            color=colors.get(phase, "#cccccc"),
            borderWidth=2,
            borderWidthSelected=3,
            shape="box",
            title=f"Phase: {phase}\nStatus: {'IMPLEMENTED' if done else 'STUB/PLANNED'}",
        )
    for a, b in g.edges():
        net.add_edge(a, b, arrows="to")

    out = REPO / "data" / "processed" / "project_graph.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(out))
    print("wrote", out)
    print("modules:", g.number_of_nodes(), "| edges:", g.number_of_edges())


if __name__ == "__main__":
    main()
    sys.exit(0)
