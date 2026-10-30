"""Twin test sets and the graph ablation of v9 (docs/POLICY_V9.md §5), from reports/v9/training_v7.json.

The test sets were run once, after the live evaluation (scripts/train_v7.py --only-test). Reported for
every controller, whatever they show: validation reward (selection) and T1/T2/T3 aggregates. The ablation
pairs the graph run and the no-graph run of the same seed (focal_bc_s1 vs focal_bc_nograph_s1) episode by
episode (same workloads and simulator seeds); the selected run (seed 2) has no no-graph twin. 95% t-intervals.

    python scripts/analysis/v9_ablation.py   # writes reports/v9/ablation.{md,json}
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flexascale.lab.benchmark import mean_ci  # the verdict's intervals (scripts/analyze_v7.py)

REPORT = ROOT / "reports/v9"
SETS = {"T1_live_scenarios": "T1: the 6 live scenarios × 5 seeds", "T2_random_shop": "T2: 60 random shop workloads",
        "T3_random_apps": "T3: 40 random synthetic applications"}
KEYS = (("reward", "reward", "{:+.3f}"), ("replica_hours", "replica-h", "{:+.4f}"), ("p95_ms", "p95 ms", "{:+.1f}"),
        ("slo_violation_s", "SLO violation s", "{:+.2f}"))
GRAPH, NOGRAPH = "v7 (focal_bc_s1)", "v7 (focal_bc_nograph_s1)"


def main() -> int:
    s = json.loads((REPORT / "training_v7.json").read_text(encoding="utf-8"))
    test, sel = s["test"], f"v7 ({s['selected']})"
    rule = f"operator + {s['selected_rule']}"
    shown = ["HPA-default (70%, 300 s)", "HPA 350%, 60 s", rule, sel, GRAPH, NOGRAPH, "v7 (focal_bc_v5reward_s1)"]
    out = {"selected": s["selected"], "selected_rule": s["selected_rule"], "validation": {}, "test": {}, "ablation": {}}
    lines = ["# v9 twin test sets and graph ablation (docs/POLICY_V9.md §5)", "",
             f"Run once after the live evaluation (`scripts/train_v7.py --only-test`, twin `config/twin/shopping_v9.json`). "
             f"Selected model: `{s['selected']}`; selected rule: `{s['selected_rule']}`; `HPA 350%, 60 s` is HPA-tuned of the live evaluation. "
             "Reward: the v7 episode reward, higher is better. Every controller sees the same episodes.", "",
             "## Validation (selection set, 40 shop workloads)", "", "| Run | best validation reward | at step |", "| :--- | ---: | ---: |"]
    for n, r in s["runs"].items():
        b = r.get("best") or {}
        out["validation"][n] = b.get("reward")
        lines.append(f"| {n} | {b.get('reward', float('nan')):.3f} | {b.get('timesteps', 0):,} |")
    v = s["rules_validation"][s["selected_rule"]]["reward"]
    lines += [f"| rule {s['selected_rule']} | {v:.3f} | – |", ""]
    for t, title in SETS.items():
        lines += [f"## {title}", "", "| Controller | reward | replica-h | p95 ms | mean ms | SLO violation s | events | osc |",
                  "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        out["test"][t] = {}
        for c in shown:
            if c not in test[t]:
                continue
            a = test[t][c]["aggregate"]
            out["test"][t][c] = a
            lines.append(f"| {c} | {a['reward']:.3f} | {a['replica_hours']:.3f} | {a['p95_ms']:.0f} | {a['mean_latency_ms']:.0f} | "
                         f"{a['slo_violation_s']:.1f} | {a['scaling_events']:.1f} | {a['oscillations']:.1f} |")
        lines.append("")
    lines += ["## Graph ablation (seed 1: graph − no graph, paired by episode)", "",
              "| Test set | episodes | " + " | ".join(f"Δ {h} [95% CI]" for _, h, _ in KEYS) + " |",
              "| :--- | ---: | " + " | ".join(":---" for _ in KEYS) + " |"]
    for t in SETS:
        g, n = test[t].get(GRAPH), test[t].get(NOGRAPH)
        if not (g and n):
            continue
        ge, ne = g["per_episode"], n["per_episode"]
        assert [e["workload"] for e in ge] == [e["workload"] for e in ne], t
        row, cells = {}, []
        for k, _, f in KEYS:
            c = mean_ci([a[k] - b[k] for a, b in zip(ge, ne)])
            row[k] = c
            lo, hi = c["ci95"]
            cells.append(f"{f.format(c['mean'])} [{f.format(lo)} … {f.format(hi)}]")
        out["ablation"][t] = row
        lines.append(f"| {t} | {len(ge)} | " + " | ".join(cells) + " |")
    lines += ["", "Positive reward Δ favours the graph; replica-h, p95 and SLO violation Δ below 0 favour the graph."]
    (REPORT / "ablation.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    (REPORT / "ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
