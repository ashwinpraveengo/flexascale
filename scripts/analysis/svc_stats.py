"""Per-service CPU (cores), CPU % of request and replicas in the 16-service runs, by controller."""
import csv, json, sys, collections, statistics as st
from pathlib import Path
rows = collections.defaultdict(lambda: collections.defaultdict(list))   # (ctrl) -> svc -> [(cpu_cores, cpu_pct, desired)]
runs = collections.Counter()
for d in sorted(Path("reports/experiments").glob("2026102[56]-*")):
    try:
        r = json.loads((d / "run.json").read_text())
    except Exception:
        continue
    if r.get("state") != "completed" or len(r.get("start_replicas") or {}) < 16:
        continue
    ctrl = r["request"]["controller"]
    runs[ctrl] += 1
    t0 = r["started_at"]
    with open(d / "telemetry.csv") as f:
        for row in csv.DictReader(f):
            if float(row["t"]) < t0:
                continue
            try:
                rows[ctrl][row["service"]].append((float(row["cpu_cores"] or 0), float(row["cpu_pct"] or 0), int(row["desired"])))
            except ValueError:
                pass
print("runs:", dict(runs))
for ctrl in ("hpa", "hpa_fast", "auto", "flexascale"):
    if ctrl not in rows:
        continue
    print(f"\n== {ctrl}: service  mean_cores  p95_cores  max_cores  mean_cpu%req  max_cpu%req  mean_repl  max_repl")
    for svc, v in sorted(rows[ctrl].items(), key=lambda kv: -st.mean(x[0] for x in kv[1])):
        c = sorted(x[0] for x in v)
        print(f"  {svc:24s} {st.mean(c):.3f} {c[int(.95*len(c))]:.3f} {c[-1]:.3f}  {st.mean(x[1] for x in v):6.1f} {max(x[1] for x in v):6.1f}  {st.mean(x[2] for x in v):.2f} {max(x[2] for x in v)}")
