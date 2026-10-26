"""Per-service mean latency vs CPU cores per ready replica (all 16-service runs, any controller)."""
import csv, json, collections, statistics as st
from pathlib import Path
BINS = [0, .05, .1, .15, .2, .25, .3, .35, .4, .45, .5, 1.0]
data = collections.defaultdict(lambda: collections.defaultdict(list))
for d in sorted(Path("reports/experiments").glob("2026102[56]-*")):
    try:
        r = json.loads((d / "run.json").read_text())
    except Exception:
        continue
    if r.get("state") != "completed" or len(r.get("start_replicas") or {}) < 16:
        continue
    with open(d / "telemetry.csv") as f:
        for row in csv.DictReader(f):
            try:
                cores, ready, lat = float(row["cpu_cores"]), int(row["ready"]), float(row["latency_ms"])
            except (ValueError, TypeError):
                continue
            if ready < 1:
                continue
            per = cores / ready
            for lo, hi in zip(BINS, BINS[1:]):
                if lo <= per < hi:
                    data[row["service"]][lo].append(lat)
                    break
for svc in ("order-service", "catalog-service", "api-gateway", "cart-service", "inventory-service", "payment-service", "user-service"):
    print(f"{svc:20s}", "  ".join(f"{lo:.2f}:{st.median(v):5.0f}ms(n={len(v)})" for lo, v in sorted(data[svc].items()) if len(v) >= 5))
