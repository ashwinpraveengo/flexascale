"""Twin vs live on the second laptop (docs/POLICY_V9.md §5): HPA-tuned at every calibration target.

The only live runs on this laptop before training are the calibration runs (calibration_steady,
25 users, 300 s, HPA with a 60 s scale-down window at 70/150/250/350% of request). Each grid value
is simulated with 5 seeds on the v9 twin and, for reference, on v7's twin (first laptop), and
compared with the mean of its valid live runs (reports/v9/calibration.json). Reported only: no
threshold, and nothing is refitted after training starts.

    python scripts/analysis/validate_twin_v9.py   # writes reports/v9/twin_check.{md,json}
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flexascale.simulator.twin import AppSpec
from flexascale.simulator.twin_control import NativeHPA, simulate
from flexascale.simulator.twin_workloads import build

SEEDS = range(5)
TWINS = {"v9": ROOT / "config/twin/shopping_v9.json", "v7": ROOT / "config/twin/shopping.json"}
KEYS = (("replica_hours", "replica_hours"), ("p95_ms", "p95_ms"), ("mean_latency_ms", "mean_ms"))


def main() -> int:
    live = json.loads((ROOT / "reports/v9/calibration.json").read_text(encoding="utf-8"))["means"]
    out = {"seeds": len(SEEDS), "targets": {}}
    for name, path in TWINS.items():
        spec = json.loads(path.read_text(encoding="utf-8"))
        app = AppSpec.from_json(spec)
        for target, L in live.items():
            sims = [simulate(app, build(app, spec["scenarios"], "calibration_steady"), NativeHPA(float(target), 60.0), seed=k)
                    for k in SEEDS]
            row = out["targets"].setdefault(target, {"live": {k: L[lk] for k, lk in KEYS}})
            row[name] = {k: float(np.mean([s[k] for s in sims])) for k, _ in KEYS}
    lines = ["# Twin check against this laptop's calibration runs (docs/POLICY_V9.md §5)", "",
             f"HPA with a 60 s scale-down window, workload calibration_steady (25 users, 300 s); twin = mean of {len(SEEDS)} seeds, "
             "live = mean of the valid runs (2 per target). Reported only; no threshold.", "",
             "| CPU target | live replica-h | v9 twin | v7 twin | live p95 ms | v9 twin | v7 twin | live mean ms | v9 twin | v7 twin |",
             "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    errs = {n: {k: [] for k, _ in KEYS} for n in TWINS}
    for target, row in out["targets"].items():
        cells = []
        for k, _ in KEYS:
            cells.append(f"{row['live'][k]:.3f}" if k == "replica_hours" else f"{row['live'][k]:.0f}")
            for n in TWINS:
                v = row[n][k]
                errs[n][k].append(100 * (v - row["live"][k]) / row["live"][k])
                cells.append(f"{v:.3f}" if k == "replica_hours" else f"{v:.0f}")
        lines.append(f"| {target}% | " + " | ".join(cells) + " |")
    out["mean_abs_error_pct"] = {n: {k: float(np.mean(np.abs(e))) for k, e in d.items()} for n, d in errs.items()}
    lines += ["", "Mean absolute error over the four targets:", ""]
    for n, d in out["mean_abs_error_pct"].items():
        lines.append(f"* {n} twin: replica-hours {d['replica_hours']:.1f}%, p95 {d['p95_ms']:.1f}%, mean latency {d['mean_latency_ms']:.1f}%")
    (ROOT / "reports/v9/twin_check.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    (ROOT / "reports/v9/twin_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
