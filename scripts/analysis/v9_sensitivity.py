"""Sensitivity of the v9 live comparison to the late reruns (descriptive; docs/POLICY_V9.md §8, 2026-10-30).

The pre-registered verdict is reports/v9/evaluation.md (scripts/analyze_v7.py --study v9) and is not
changed by this script. The valid reruns (01:31-02:31) ran hours after the other runs of their block,
when the laptop was under memory pressure, so this recomputes the paired differences without every pair
that contains a rerun. Same metrics and 95% t-intervals as the verdict; no check and no verdict.

    python scripts/analysis/v9_sensitivity.py   # writes reports/v9/evaluation_sensitivity.{md,json}
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flexascale.lab.benchmark import mean_ci  # the verdict's intervals (scripts/analyze_v7.py)

REPORT = ROOT / "reports/v9"
METRICS = (("replica_hours", "Replica-hours", "%"), ("p95_ms", "p95", "%"), ("mean_ms", "Mean latency", "%"),
           ("failure_pct", "Failures", " pp"), ("throughput", "Throughput", "%"), ("e2e_slo_s", "E2E SLO violation", " s"))


def ci(x):
    c = mean_ci(x)
    return (c["mean"], *(c["ci95"] or (None, None)))


def main() -> int:
    ev = json.loads((REPORT / "evaluation.json").read_text(encoding="utf-8"))
    reruns = {e["id"] for e in json.loads((REPORT / "evaluation_plan.reruns.progress.json").read_text(encoding="utf-8")).values()}
    paired = {p[k] for c in ev["comparisons"].values() for p in c["pairs"] for k in ("candidate", "reference")}
    reruns &= paired  # host-affected reruns are in no pair already
    out = {"reruns": sorted(reruns), "comparisons": {}}
    lines = ["# v9 live comparison without the late reruns (descriptive)", "",
             "Not the pre-registered verdict (that is `evaluation.md`, unchanged). The valid reruns ran at 01:53–02:31, hours after "
             "the other runs of their block and under memory pressure; every pair that contains one is left out here. "
             "Δ = candidate − reference, 95% t-intervals over the remaining pairs.", "",
             "Reruns left out: " + ", ".join(f"`{r}`" for r in sorted(reruns)), ""]
    for name, comp in ev["comparisons"].items():
        if not name.startswith(("rl ", "auto ")):
            continue
        pairs = [p for p in comp["pairs"] if p["candidate"] not in reruns and p["reference"] not in reruns]
        row = {"pairs": len(pairs), "all_pairs": len(comp["pairs"]), "blocks": [p["block"] for p in pairs]}
        lines += [f"## {name} ({len(pairs)} of {len(comp['pairs'])} pairs)", "", "| Metric | Mean Δ [95% CI] |", "| :--- | :--- |"]
        for k, title, unit in METRICS:
            m, lo, hi = ci([p[k] for p in pairs])
            row[k] = {"mean": m, "lo": lo, "hi": hi}
            lines.append(f"| {title} | {m:+.1f}{unit} [{lo:+.1f} … {hi:+.1f}] |" if lo is not None else f"| {title} | {m:+.1f}{unit} |")
        out["comparisons"][name] = row
        lines.append("")
    (REPORT / "evaluation_sensitivity.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    (REPORT / "evaluation_sensitivity.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
