"""Headroom check in the twin: HPA variants and simple rules on the six evaluation scenarios (25 users)."""
import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flexascale.simulator.twin import AppSpec
from flexascale.simulator.twin_control import Guards, NativeHPA, OperatorLoop, limit_target_policy, simulate, threshold_policy
from flexascale.simulator.twin_workloads import EVALUATION_SCENARIOS, build

spec = json.loads((ROOT / "config/twin/shopping.json").read_text())
app = AppSpec.from_json(spec)
wls = [build(app, spec["scenarios"], sc) for sc in EVALUATION_SCENARIOS]
SEEDS = range(6)

def run(ctrl_factory):
    rows = []
    for wl in wls:
        for k in SEEDS:
            rows.append(simulate(app, wl, ctrl_factory(), seed=k))
    return rows

def agg(rows):
    f = lambda k: np.array([r[k] for r in rows])
    return {"rh": f("replica_hours").mean(), "p95": f("p95_ms").mean(), "mean": f("mean_latency_ms").mean(),
            "fail": f("failure_pct").mean(), "slo": f("slo_violation_s").mean(), "ev": f("scaling_events").mean(),
            "osc": f("oscillations").mean(), "per": {wl.name: np.mean([r["replica_hours"] for r in rows if r["workload"] == wl.name]) for wl in wls},
            "p95per": {wl.name: np.mean([r["p95_ms"] for r in rows if r["workload"] == wl.name]) for wl in wls}}

cands = {
    "HPA-default (70%, 300 s)": lambda: NativeHPA(70, 300),
    "HPA 70%, 60 s": lambda: NativeHPA(70, 60),
    "HPA 150%, 60 s": lambda: NativeHPA(150, 60),
    "HPA 250%, 60 s": lambda: NativeHPA(250, 60),
    "HPA 350%, 60 s": lambda: NativeHPA(350, 60),
    "operator + threshold 70% (v5 guards)": lambda: OperatorLoop(threshold_policy(70), Guards()),
    "operator + limit-target 0.6/0.35 (fast guards)": lambda: OperatorLoop(limit_target_policy(0.6, 0.35), Guards(max_step=3, max_scale_down_step=1, scale_up_cooldown_s=15, scale_down_cooldown_s=30, scale_down_block_cpu_pct=1e9, scale_down_block_slo_ratio=None)),
    "operator + limit-target 0.7/0.4 (fast guards)": lambda: OperatorLoop(limit_target_policy(0.7, 0.4), Guards(max_step=3, max_scale_down_step=1, scale_up_cooldown_s=15, scale_down_cooldown_s=30, scale_down_block_cpu_pct=1e9, scale_down_block_slo_ratio=None)),
    "hold at minimum (no scaling)": lambda: OperatorLoop(lambda s, o, l: np.zeros(s.n, dtype=int), Guards()),
}
base = None
print(f"{'controller':48s} repl-h   Δ%vsDef   p95   mean  fail%  sloV_s  events  osc")
for name, fac in cands.items():
    a = agg(run(fac))
    base = base or a
    print(f"{name:48s} {a['rh']:.3f}  {100*(a['rh']-base['rh'])/base['rh']:+6.1f}%  {a['p95']:5.0f} {a['mean']:5.0f}  {a['fail']:5.2f}  {a['slo']:5.1f}  {a['ev']:5.1f}  {a['osc']:4.1f}")
    print("      per-scenario repl-h:", " ".join(f"{k.split('@')[0][:8]}={v:.3f}" for k, v in a["per"].items()), "| p95:", " ".join(f"{v:.0f}" for v in a["p95per"].values()))
