"""Boot the app on an explicit database, for the LIVE test tier.

## Why this exists instead of setting an env var from the test runner

The obvious way to point a spawned `uvicorn` at a throwaway database is
`spawn(python, ['-m','uvicorn',...], { env: { ...process.env,
LECGAP_DATABASE_URL: 'sqlite:///...' } })`. On this machine that env var
arrived **intermittently** — the same spawn, same key, same value and same cwd
returned the variable in one run and dropped it in the next, with no error. The
failure mode is silent and severe: the server boots perfectly happily against
the developer's REAL `data/lecgap.db`, `recover_orphans()` runs against real job
rows at import, and the tests then assert against a developer's actual lecture
data. A green run would have meant nothing.

So the env var is not trusted. This launcher sets it **in-process, before the
first backend import**, which is the one ordering that is deterministic (it is
the same ordering `tests/conftest.py` relies on, and for the same reason), and
then *verifies* the engine actually bound where it was asked to. If it did not,
the process refuses to serve rather than quietly using real data.

The same treatment covers `LECGAP_CLIPS_BASE_DIR`. `backend.config` freezes
`CLIPS_BASE_DIR` at import exactly as `backend.models.db` freezes its engine, so
a served-clip path that silently fell back to the default would hand the E2E
tier somebody's real lecture media -- and, in the other direction, would 404 the
fixture the §10 gate needs to play. Both are verified, both refuse to serve.

Usage:
    python scripts/run_live_server.py <sqlite-file> <port> [--seed]

`--seed` populates the database first, in this process, before uvicorn starts.
Playwright launches `webServer` *before* `globalSetup`, so an external seed step
is a race: the backend comes up on an empty file whose parent directory may not
even exist yet. Seeding in-process makes the ordering explicit instead of
relying on which hook happens to run first.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE_DB = (REPO / "data" / "lecgap.db").resolve()
LIVE_CLIPS = (REPO / "data" / "processed" / "clips").resolve()

if len(sys.argv) not in (3, 4):
    print(__doc__)
    raise SystemExit(2)

DB = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
SEED = "--seed" in sys.argv[3:]

# Where cut clips live for THIS process. Beside the throwaway database, so a
# test run leaves its database and its media together and neither outlives the
# other. The seed script derives the same default, and refuses the repo's real
# clip tree outright.
CLIPS_DIR = Path(
    os.environ.get("LECGAP_CLIPS_BASE_DIR") or (DB.parent / "clips")
).resolve()

if DB == LIVE_DB:
    raise SystemExit(f"REFUSING TO RUN: {DB} is the live database.")

if CLIPS_DIR == LIVE_CLIPS or LIVE_CLIPS in CLIPS_DIR.parents:
    raise SystemExit(
        f"REFUSING TO SERVE: clip tree {CLIPS_DIR} is inside the real one at "
        f"{LIVE_CLIPS}. The E2E tier writes real media bytes and must never "
        "touch real lecture media."
    )

if SEED:
    # The seed script creates the parent directory and the schema, and refuses
    # the live database on its own. Run it as a subprocess so it gets a clean
    # interpreter state and its own engine.
    import subprocess

    DB.parent.mkdir(parents=True, exist_ok=True)
    # Passed through explicitly, not left to the child's own default: the seed
    # and this server must agree on one tree, and the seed is a separate
    # process that would otherwise be re-deriving the same value by a different
    # route.
    r = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("seed_live_db.py")), str(DB)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**os.environ, "LECGAP_CLIPS_BASE_DIR": str(CLIPS_DIR)},
    )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"seed_live_db.py failed with exit code {r.returncode}")

# Before ANY backend import. backend.models.db builds its engine at import time,
# and backend.config freezes CLIPS_BASE_DIR the same way.
os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{DB.as_posix()}"
os.environ["LECGAP_CLIPS_BASE_DIR"] = str(CLIPS_DIR)
# A guarded backend would 401 the SSE stream; the live tier is unguarded.
os.environ.pop("LECGAP_API_KEY", None)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.config import CLIPS_BASE_DIR  # noqa: E402
from backend.models.db import engine  # noqa: E402

bound = Path(str(engine.url).replace("sqlite:///", "")).resolve()
if bound != DB:
    raise SystemExit(
        f"REFUSING TO SERVE: asked for {DB}, engine bound to {bound}. "
        "LECGAP_DATABASE_URL did not take effect before the engine was built."
    )

# The same verification for the clip tree, because it is frozen at import too
# and a silent fallback would serve real lecture media to a test — or, worse,
# 404 the very bytes the §10 gate exists to play.
if Path(CLIPS_BASE_DIR).resolve() != CLIPS_DIR:
    raise SystemExit(
        f"REFUSING TO SERVE: asked for clips in {CLIPS_DIR}, but "
        f"CLIPS_BASE_DIR resolved to {CLIPS_BASE_DIR}. LEGCAP_CLIPS_BASE_DIR "
        "did not take effect before backend.config was imported."
    )

print(f"[live-server] engine bound to {bound}", flush=True)
print(f"[live-server] clips served from {Path(CLIPS_BASE_DIR).resolve()}", flush=True)
print(f"[live-server] serving on http://127.0.0.1:{PORT}", flush=True)

import uvicorn  # noqa: E402

uvicorn.run("backend.main:app", host="127.0.0.1", port=PORT, log_level="warning")
