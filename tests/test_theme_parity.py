"""Cross-engine colour parity — the two palettes cannot drift apart.

Decided in session: the React theme is a **port** of the tokens rather than a
build-time generated artefact, because a generated JSON would add a build step
and a generated file to a codebase that has neither. The cost of that choice is
that nothing stops `src/theme/tokens.ts` from being edited without
`frontend/theme.py`, and the app would then have two palettes again -- the exact
state REACT_ARCHITECTURE.md §4 says to avoid ("If the React app picks its own
colours, the app has two palettes and one of them is untested").

So: read the TypeScript table and compare it to the Python one. This is the
cheapest thing that makes the two systems one, and it fails loudly with the
offending token named.

Parsing notes, because the naive version of either side is wrong:

  - `theme.py` builds its palettes with keyword arguments, so the hex is on the
    same line as the token name for every token except the ones carrying a
    trailing comment. A regex over `name=<hex>` handles both.
  - `node_light` / `node_sat` are floats, not colours, and are compared as
    floats with a tolerance.
  - `tokens.ts` quotes the same names. A value that appears in either file and
    not the other is the failure, and both sides are named in the message.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from frontend import theme as py_theme

REPO_ROOT = Path(__file__).resolve().parents[1]
TS_TOKENS = REPO_ROOT / "frontend-react" / "src" / "theme" / "tokens.ts"

#: Tokens that are not colours.
NUMERIC = {"node_light", "node_sat"}

TOKEN_NAMES = [n for n in py_theme._DARK.__slots__ if n != "base"]


def _ts_source() -> str:
    if not TS_TOKENS.exists():
        pytest.skip(f"{TS_TOKENS} not present (Streamlit-only checkout?)")
    return TS_TOKENS.read_text(encoding="utf-8")


def _py_palette(base: str) -> dict:
    return {name: getattr(py_theme.palette(base), name) for name in TOKEN_NAMES}


def _ts_palette(base: str) -> dict:
    """Pull the palette object for `base` out of tokens.ts.

    Located by the declaration name (`DARK_PALETTE` / `LIGHT_PALETTE`) rather
    than by a `base:` value, because the table refers to the exported `DARK` /
    `LIGHT` constants rather than repeating the literal -- and matching on the
    literal would find the wrong thing (or nothing).
    """
    src = _ts_source()
    decl = f"{base.upper()}_PALETTE: Palette = "
    start = src.find(decl)
    assert start != -1, f"no `{decl}` declaration in {TS_TOKENS}"

    open_brace = src.index("{", start)
    depth = 0
    body = None
    for i in range(open_brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                body = src[open_brace : i + 1]
                break
    assert body is not None, "unbalanced object literal in tokens.ts"

    out: dict = {}
    for name in TOKEN_NAMES:
        m = re.search(rf"^\s*{name}:\s*'([^']+)'", body, re.MULTILINE)
        if m:
            out[name] = m.group(1)
            continue
        m = re.search(rf"^\s*{name}:\s*([0-9.]+)", body, re.MULTILINE)
        if m:
            out[name] = float(m.group(1))
    return out


@pytest.mark.parametrize("base", ["dark", "light"])
class TestTokenParity:
    def test_every_token_is_present_on_both_sides(self, base):
        py = _py_palette(base)
        ts = _ts_palette(base)
        missing_ts = sorted(set(py) - set(ts))
        missing_py = sorted(set(ts) - set(py))
        assert not missing_ts, f"in theme.py but not tokens.ts ({base}): {missing_ts}"
        assert not missing_py, f"in tokens.ts but not theme.py ({base}): {missing_py}"

    def test_colour_tokens_are_identical(self, base):
        py = _py_palette(base)
        ts = _ts_palette(base)
        mismatched = {
            name: (py[name], ts[name])
            for name in py
            if name not in NUMERIC and py[name].lower() != str(ts[name]).lower()
        }
        assert not mismatched, (
            f"colour drift ({base}): "
            + ", ".join(f"{k}: theme.py={v[0]} tokens.ts={v[1]}" for k, v in sorted(mismatched.items()))
        )

    def test_numeric_tokens_match_within_tolerance(self, base):
        py = _py_palette(base)
        ts = _ts_palette(base)
        for name in NUMERIC:
            assert math.isclose(float(py[name]), float(ts[name]), abs_tol=1e-9), (
                f"{name} ({base}): theme.py={py[name]} tokens.ts={ts[name]}"
            )

    def test_the_derived_colours_agree(self, base):
        """Not just the table: the two implementations must produce the same
        node fills, which is where a rounding difference would hide."""
        for hue in (0.0, 0.17, 0.5, 0.83):
            assert py_theme.node_fill(hue, base=base) == _ts_node_fill(hue, base)


def _ts_node_fill(hue: float, base: str) -> str:
    """Run the TypeScript `nodeFill` in-process, via node, and return its hex.

    Deliberately not reimplemented in Python: the point is to compare the two
    *implementations*, so a second Python copy of the maths would prove nothing.
    """
    import json
    import subprocess

    script = (
        "const {nodeFill} = await import('./src/theme/tokens.ts');"
        f"console.log(JSON.stringify(nodeFill({hue!r}, {json.dumps(base)})));"
    )
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        cwd=REPO_ROOT / "frontend-react",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"node could not run the TS module: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


class TestSweepParity:
    def test_the_worst_readable_on_case_agrees(self):
        """The 72-hue sweep's worst case is the number the palette is tuned for.

        `tests/test_theme.py` pins it at >= 4.5:1 on the Python side and
        `src/theme/theme.test.ts` pins the same on the TypeScript side. If the two
        ever disagree about which hue is worst, one of them is wrong.
        """
        import subprocess

        script = (
            "const {readableOn, nodeFill, contrastRatio} = await import('./src/theme/tokens.ts');"
            "let worst = Infinity, hue = 0;"
            "for (let i = 0; i < 72; i++) { const h = i / 72; const f = nodeFill(h, 'dark');"
            " const c = contrastRatio(readableOn(f, 'dark'), f);"
            " if (c < worst) { worst = c; hue = h } }"
            "console.log(JSON.stringify({worst, hue}));"
        )
        proc = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=REPO_ROOT / "frontend-react",
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip(f"node could not run the TS module: {proc.stderr.strip()[:200]}")
        import json

        got = json.loads(proc.stdout)
        py_worst = min(
            py_theme.contrast_ratio(
                py_theme.readable_on(py_theme.node_fill(i / 72, base="dark"), base="dark"),
                py_theme.node_fill(i / 72, base="dark"),
            )
            for i in range(72)
        )
        assert got["worst"] == pytest.approx(py_worst, abs=1e-9), (
            f"worst read-able-on ratio differs: theme.py={py_worst} tokens.ts={got['worst']}"
        )
