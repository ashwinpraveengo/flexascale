"""Twin vs live: native HPA (default and 60 s window) on the six evaluation scenarios."""
import json, sys, collections
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
from flexascale.simulator.twin import AppSpec
from flexascale.simulator.twin_control import NativeHPA, simulate
from flexascale.simulator.twin_workloads import EVALUATION_SCENARIOS, build

spec = json.loads((ROOT / "config/twin/shopping.json").read_text())
app = AppSpec.from_json(spec)
live = collections.defaultdict(list)
for d in sorted((ROOT / "reports/experiments").glob("20261026-*")):
    r = json.loads((d / "run.json").read_text())
    if r.get("state") != "completed" or len(r.get("start_replicas") or {}) < 16: continue
    s = r["summary"]
    peaks = collections.defaultdict(int)
    for smp in r["samples"]:
        for name, v in smp["services"].items():
            peaks[name] = max(peaks[name], v["desired"])
    live[(r["request"]["controller"], r["request"]["scenario"])].append(
        (s["resources"]["replica_hours"], s["workload"]["p95_ms"], s["workload"]["mean_latency_ms"], peaks.get("order-service"), peaks.get("user-service")))
print(f"{'scenario':20s} {'ctrl':9s} | live: repl-h  p95  mean  ordMax userMax | twin: repl-h  p95  mean  ordMax userMax")
for ctrl, hpa in (("hpa", NativeHPA(70, 300)), ("hpa_fast", NativeHPA(70, 60))):
    errs = []
    for sc in EVALUATION_SCENARIOS:
        L = np.array(live[(ctrl, sc)], dtype=float).mean(axis=0)
        outs = [simulate(app, build(app, spec["scenarios"], sc), hpa, seed=k) for k in range(5)]
        T = np.mean([[o["replica_hours"], o["p95_ms"], o["mean_latency_ms"],
                      max(x[app.names.index("order-service")] for x in o["sim"].log["desired"]),
                      max(x[app.names.index("user-service")] for x in o["sim"].log["desired"])] for o in outs], axis=0)
        errs.append(100 * (T[0] - L[0]) / L[0])
        print(f"{sc:20s} {ctrl:9s} | {L[0]:6.3f} {L[1]:5.0f} {L[2]:5.0f} {L[3]:5.1f} {L[4]:5.1f} | {T[0]:6.3f} {T[1]:5.0f} {T[2]:5.0f} {T[3]:5.1f} {T[4]:5.1f}  ({errs[-1]:+.1f}%)")
    print(f"  {ctrl}: mean abs replica-hours error {np.mean(np.abs(errs)):.1f}%")
