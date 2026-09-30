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

if len(sys.argv) not in (3, 4):
    print(__doc__)
    raise SystemExit(2)

DB = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
SEED = "--seed" in sys.argv[3:]

if DB == LIVE_DB:
    raise SystemExit(f"REFUSING TO RUN: {DB} is the live database.")

if SEED:
    # The seed script creates the parent directory and the schema, and refuses
    # the live database on its own. Run it as a subprocess so it gets a clean
    # interpreter state and its own engine.
    import subprocess

    DB.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("seed_live_db.py")), str(DB)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"seed_live_db.py failed with exit code {r.returncode}")

# Before ANY backend import. backend.models.db builds its engine at import time.
os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{DB.as_posix()}"
# A guarded backend would 401 the SSE stream; the live tier is unguarded.
os.environ.pop("LECGAP_API_KEY", None)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.models.db import engine  # noqa: E402

bound = Path(str(engine.url).replace("sqlite:///", "")).resolve()
if bound != DB:
    raise SystemExit(
        f"REFUSING TO SERVE: asked for {DB}, engine bound to {bound}. "
        "LECGAP_DATABASE_URL did not take effect before the engine was built."
    )

print(f"[live-server] engine bound to {bound}", flush=True)
print(f"[live-server] serving on http://127.0.0.1:{PORT}", flush=True)

import uvicorn  # noqa: E402

uvicorn.run("backend.main:app", host="127.0.0.1", port=PORT, log_level="warning")
