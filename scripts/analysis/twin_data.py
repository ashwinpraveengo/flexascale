"""Load the 16-service live runs as aligned per-sample rows (shared by the twin fit and diagnostics)."""
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_runs(root="reports/experiments", since="20261025", min_services=16):
    """Yield (run, rows) with rows = list of {t, elapsed, users, rps, p95_ms, ..., services: {name: {...}}}."""
    for d in sorted(Path(root).glob("2026*")):
        if d.name < since:
            continue
        try:
            r = json.loads((d / "run.json").read_text())
        except (OSError, ValueError):
            continue
        if r.get("state") != "completed" or len(r.get("start_replicas") or {}) < min_services:
            continue
        by_t = defaultdict(lambda: {"services": {}})
        with open(d / "telemetry.csv") as f:
            for row in csv.DictReader(f):
                t = float(row["t"])
                s = by_t[t]
                for k in ("elapsed", "users", "rps", "fail_rps", "p50_ms", "p95_ms", "p99_ms"):
                    v = row.get(k)
                    s[k] = float(v) if v not in (None, "", "None") else None
                svc = {}
                for k in ("desired", "ready", "cpu_cores", "cpu_pct", "request_rate", "latency_ms", "latency_p95_ms", "memory_bytes"):
                    v = row.get(k)
                    svc[k] = float(v) if v not in (None, "", "None") else None
                s["services"][row["service"]] = svc
        rows = [dict(t=t, **v) for t, v in sorted(by_t.items())]
        yield r, rows
