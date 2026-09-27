"""Docs render checks — the mermaid diagrams are documentation, so they must parse.

Why this file exists
--------------------
A stray character in an edge label made the whole system-architecture diagram
fail to render on GitHub. The label was::

    JOBS -->|"job row + stage/detail/%"| DB

Mermaid's lexer treats a bare ``%`` as the start of a comment, so it swallowed
the rest of the line — including the closing quote — and the diagram after it
failed with "Parse error on line 41". A reader saw *no architecture diagram at
all* and no hint that the markdown was otherwise fine. Found with mermaid's own
parser (``scripts/check_mermaid.mjs``), not by reading the text.

So the cheap static rules that would have caught it are pinned here and run on
every commit. The full parse is opt-in, because it needs Node:

    npm --prefix .mermaid-check install mermaid jsdom
    python scripts/check_mermaid.mjs ...  (or) set LECGAP_MERMAID_DIR=.mermaid-check
    python -m pytest tests/test_docs_render.py -k real
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
#: Every committed markdown that ships a diagram.
DOCS = ["README.md", "working.md", "plan/REACT_ARCHITECTURE.md",
        "plan/ENGINE2_REBUILD_PLAN.md", "plan/ARCHITECTURE.md",
        "plan/FRONTEND_ARCHITECTURE.md"]

_FENCE = re.compile(r"```mermaid\r?\n(.*?)```", re.S)
#: `class A,B c;` / `classDef name fill:...;`
_CLASS = re.compile(r"^\s*class\s+([A-Za-z0-9_,\s]+?)\s+\w+\s*;", re.M)
#: A node declaration: `A["..."]`, `A("...")`, `A{"..."}`, `A[".."][("..")]`
_NODE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*[\[\(\{]", re.M)


def _blocks(path: Path):
    text = path.read_text(encoding="utf-8")
    return _FENCE.findall(text), text


@pytest.mark.parametrize("name", DOCS)
def test_every_mermaid_block_avoids_the_lexers_comment_character(name):
    """A bare ``%`` inside a diagram is a comment for mermaid's lexer.

    It does not error where it sits - it eats the remainder of its own line,
    which unbalances the very next token, so the reported error points somewhere
    else entirely. That indirection is why this is a rule and not a diagnosis.
    """
    path = REPO / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    blocks, _ = _blocks(path)
    for index, block in enumerate(blocks, 1):
        for lineno, line in enumerate(block.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("%%"):
                continue                      # a real comment line: allowed
            assert "%" not in stripped, (
                f"{name} mermaid block #{index} line {lineno}: a bare '%' is a "
                f"comment for mermaid and will unbalance this line:\n  {stripped}")


@pytest.mark.parametrize("name", DOCS)
def test_code_fences_are_balanced(name):
    """An odd fence count swallows the rest of the document into a code block."""
    path = REPO / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    _, text = _blocks(path)
    fences = len(re.findall(r"^```", text, re.M))
    assert fences % 2 == 0, f"{name} has {fences} ``` fences (odd = unclosed block)"


@pytest.mark.parametrize("name", DOCS)
def test_every_styled_class_target_is_declared(name):
    """`class A,B style;` for a node that was never declared renders nothing and
    is easy to leave behind when a node is renamed in one place only."""
    path = REPO / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    blocks, _ = _blocks(path)
    for index, block in enumerate(blocks, 1):
        declared = set(_NODE.findall(block))
        styled = set()
        for group in _CLASS.findall(block):
            styled.update(part.strip() for part in group.split(",") if part.strip())
        missing = sorted(styled - declared)
        assert not missing, (
            f"{name} mermaid block #{index} styles undeclared node(s): "
            f"{missing} (declared: {sorted(declared)})")


@pytest.mark.skipif(
    not shutil.which("node"),
    reason="the full mermaid parse needs Node (not part of the Python env)",
)
def test_mermaid_blocks_parse_for_real(name="README.md"):
    """Opt-in: parse every diagram with mermaid itself.

    The static rules above catch the mistakes seen so far; this catches the ones
    nobody thought of. It needs Node plus a mermaid install, which is not a
    Python dependency, so it skips unless ``LECGAP_MERMAID_DIR`` points at one
    (``npm --prefix .mermaid-check install mermaid jsdom``).
    """
    dir_ = os.getenv("LECGAP_MERMAID_DIR")
    script = REPO / "scripts" / "check_mermaid.mjs"
    if not dir_ or not (Path(dir_) / "node_modules" / "mermaid").exists():
        pytest.skip("set LECGAP_MERMAID_DIR to a node_modules dir containing mermaid")
    targets = [str(REPO / n) for n in DOCS if (REPO / n).exists()]
    proc = subprocess.run(
        ["node", str(script), *targets],
        cwd=dir_, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"mermaid parse failed:\n{proc.stdout}\n{proc.stderr}"
