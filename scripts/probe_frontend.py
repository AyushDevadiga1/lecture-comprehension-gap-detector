"""Frontend integrity + latency/concurrency probe.

Simulates exactly the HTTP requests `frontend/app.py` makes (student + faculty
tabs + the sidebar), against a live backend. It reports:

  * integrity: every request the UI can make returns 2xx with the JSON shape
    the UI actually reads (drives the same helpers/nonexistent flags),
  * latency: per-endpoint min/median wall-clock + payload bytes,
  * waterfall: the frontend's current cost is the SUM of serial calls a single
    Streamlit rerun performs (`/courses` -> `/lectures` -> detail/graph/stats),
    recomputed here vs what a parallel fetch would cost (the concurrency gap),
  * penetration/burst: W concurrent calls to the hot endpoints measure
    threadpool+SQLite saturation and whether the burst starves /health.

Usage:
    python scripts/probe_frontend.py [--url http://127.0.0.1:8000] [--burst 40]
"""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

ENDPOINTS = {
    "health": {"path": "/health", "kind": "get"},
    "courses": {"path": "/courses", "kind": "get"},
    "lectures": {"path": "/lectures", "kind": "get"},
    "progress": {"path": "/lectures/{id}/progress", "kind": "get"},
}

INTEGRITY_CHECKS = [
    ("GET /courses", "/courses", {}),
    ("GET /lectures", "/lectures", {}),
    ("GET /lectures/4", "/lectures/{id}", {}),
    ("GET /courses/ml1/graph", "/courses/{cid}/graph", {}),
    ("GET /courses/ml1/stats", "/courses/{cid}/stats", {}),
    ("GET /lectures/4/clips", "/lectures/{id}/clips", {}),
    ("GET /lectures/4/progress", "/lectures/{id}/progress", {}),
]


def _pick_first(d, *keys):
    for k in keys:
        if str(k) in d:
            return str(k)
    return None


def locate(base: str):
    """Discover a lecture id + course id to probe (matches what the UI picks)."""
    lecs = requests.get(f"{base}/lectures", timeout=30).json()
    if not lecs:
        return None, None
    rid = str(lecs[-1]["id"])

    courses = requests.get(f"{base}/courses", timeout=30).json()
    cid = None
    for c in courses:
        if c["course_id"] == lecs[-1]["course_id"]:
            cid = c["course_id"]
            break
    if cid is None:
        cid = lecs[-1]["course_id"]
    return rid, cid


def time_one(base, path):
    t0 = time.perf_counter()
    try:
        r = requests.get(f"{base}{path}", timeout=60)
        dt = (time.perf_counter() - t0) * 1000
        return dt, r.status_code, len(r.content)
    except requests.RequestException as exc:
        return (time.perf_counter() - t0) * 1000, -1, str(exc)


def sample(base, path, n=5):
    rows = [time_one(base, path) for _ in range(n)]
    times = sorted(r[0] for r in rows if r[1] == 200)
    ok = sum(1 for r in rows if r[1] == 200)
    size = next((r[2] for r in rows if r[1] == 200), 0)
    return {
        "path": path,
        "samples": n,
        "ok": ok,
        "p50_ms": round(statistics.median(times), 1) if times else None,
        "min_ms": round(times[0], 1) if times else None,
        "p95_ms": round(times[int(0.95 * len(times)) - 1], 1) if len(times) >= 5 else None,
        "payload_bytes": size,
    }


def burst(base, path, workers):
    """'Penetration' burst: hammer one hot endpoint with `workers` parallel
    calls, then immediately measure whether /health and /courses suffer."""
    started = time.perf_counter()
    timings = []
    statuses = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(time_one, base, path) for _ in range(workers)]
        for f in as_completed(futs):
            dt, code, extra = f.result()
            timings.append(dt)
            statuses.append(code)
    wall = (time.perf_counter() - started) * 1000
    times = sorted(t for t, c in zip(timings, statuses) if c == 200)
    h = time_one(base, "/health")
    return {
        "burst_path": path,
        "workers": workers,
        "wall_ms": round(wall, 1),
        "ok": sum(1 for c in statuses if c == 200),
        "p50_ms": round(statistics.median(times), 1) if times else None,
        "p95_ms": round(times[int(0.95 * len(times)) - 1], 1) if len(times) >= 5 else None,
        "http_errors": sum(1 for c in statuses if c != 200),
        "health_during_burst_ms": round(h[0], 1),
        "health_status": h[1],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--burst", type=int, default=32)
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    base = args.url.rstrip("/")
    rid, cid = locate(base)
    if rid is None:
        print("INTEGRITY: FAIL — no lectures in DB to probe")
        return 1

    print(f"probe target: {base}  (lecture {rid}, course {cid})")

    # ---- integrity pass
    print("\n== INTEGRITY (UI request surface) ==")
    failures = 0
    fixed = {
        "{id}": rid,
        "{cid}": cid,
    }
    for label, template, *_ in INTEGRITY_CHECKS:
        path = template
        for k, v in fixed.items():
            path = path.replace(k, v)
        t0 = time.perf_counter()
        r = requests.get(f"{base}{path}", timeout=60)
        dt = (time.perf_counter() - t0) * 1000
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            body = None
        ok_shape = True
        if label == "GET /courses":
            ok_shape = isinstance(body, list)
        elif label == "GET /lectures":
            ok_shape = isinstance(body, list)
        elif label == "GET /lectures/4":
            ok_shape = isinstance(body, dict) and "segments" in body and "concepts" in body
        elif label == "GET /courses/ml1/graph":
            ok_shape = isinstance(body, dict) and "edges" in body and "topological_order" in body
        elif label == "GET /courses/ml1/stats":
            ok_shape = isinstance(body, dict) and "heatmap" in body and "divergence" in body
        elif label == "GET /lectures/4/clips":
            ok_shape = isinstance(body, dict) and "clips" in body
        elif label == "GET /lectures/4/progress":
            ok_shape = isinstance(body, dict) and "progress_pct" in body and "status" in body
        status = "ok" if r.status_code == 200 and ok_shape else "FAIL"
        if status != "ok":
            failures += 1
        print(f"  [{status}] {label:36s} http={r.status_code} {dt:8.1f}ms "
              f"json_keys={'yes' if body is not None else 'no'}")
    print(f"  integrity: {'REFERENCES OK' if failures == 0 else str(failures) + ' references FAILED'}")

    # ---- latency pass
    print("\n== LATENCY (5-sample, median) ==")
    lat = {}
    for name, spec in ENDPOINTS.items():
        path = spec["path"].replace("{id}", rid).replace("{cid}", cid)
        row = sample(base, path, n=args.samples)
        lat[name] = row
        print(f"  {name:9s} {row['path']:30s} ok={row['ok']}/{row['samples']} "
              f"p50={row['p50_ms']}ms min={row['min_ms']}ms "
              f"payload={row['payload_bytes']}B")

    # ---- waterfall vs concurrency
    print("\n== WATERFALL (what one rerun pays, serial vs parallel) ==")
    serial_paths = [
        "/courses",
        "/lectures",
        f"/courses/{cid}/graph",
        f"/courses/{cid}/stats",
        f"/lectures/{rid}",
        f"/lectures/{rid}/progress",
        f"/lectures/{rid}/clips",
    ]
    per = {p: sample(base, p, n=args.samples)["p50_ms"] or 0 for p in serial_paths}
    serial_total = sum(per.values())
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(serial_paths)) as ex:
        list(ex.map(lambda p: requests.get(f"{base}{p}", timeout=60), serial_paths))
    parallel_total = (time.perf_counter() - t0) * 1000
    print("  serial (current frontend):           "
          f"{serial_total:.0f} ms  -> {int(serial_total / 1000)} s")
    print("  parallel (what a concurrency fix   ")
    print("          gives on the SAME pipeline): {:.0f} ms".format(parallel_total))
    if parallel_total > 0:
        print("  speedup available: {:.1f}x".format(serial_total / parallel_total))

    # ---- penetration/burst
    print("\n== BURST / SATURATION (penetration pass) ==")
    for path in ("/lectures", f"/lectures/{rid}", "/courses", "/health"):
        row = burst(base, path, args.burst)
        print(f"  {path:24s} workers={row['workers']:<3d} wall={row['wall_ms']}ms "
              f"p50={row['p50_ms']}ms p95={row['p95_ms']}ms "
              f"errors={row['http_errors']} health_after={row['health_during_burst_ms']}ms")
        time.sleep(0.4)

    print("\nprobe complete.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())