"""
Pooled paired benchmark of recorded live runs (dashboard "Comparison" page, Overview verdict).

Pairing is the same as ``scripts/build_live_report.py``: every complete
FlexaScale (or Auto) run is paired with the most recent complete native-HPA run
with identical app, scenario, users and duration that started before it, and
the pair is checked with ``Lab.compare``. Runs labelled with a ``block``
(pre-registered block designs, docs/POLICY_V7.md §3.3) are paired with the
default-HPA run of the same block instead, whatever their order inside the
block. Pairs are grouped by controller and model. For each group the paired differences (candidate - HPA) are averaged and
given a 95% t-interval, and the verdict follows the rule fixed in
docs/POLICY_V6.md section 3.1 before any v6 result was seen.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# two-sided 95% Student t critical values by degrees of freedom
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}

VERDICT_RULE = ("Verdict rule (docs/POLICY_V6.md §3.1, fixed before the v6 results): beats on cost = replica-hours interval "
                "below 0 and the failure and p95 intervals include or lie below 0; beats on performance = p95 or failure "
                "interval below 0 and the replica-hours interval includes or lies below 0; worse = an interval above 0 "
                "without such a gain; otherwise on par.")


def t95(df: float) -> float:
    """Critical value for df, rounded down to the nearest tabulated df (conservative between table entries)."""
    df = int(math.floor(df))
    if df < 1:
        return float("nan")
    return _T95[max(k for k in _T95 if k <= df)]


def welch_diff(a: List[float], b: List[float]) -> Optional[Dict[str, Any]]:
    """Mean of a minus mean of b with a 95% Welch interval (unequal variances, Welch-Satterthwaite df)."""
    a = [x for x in a if x is not None and not math.isnan(x)]
    b = [x for x in b if x is not None and not math.isnan(x)]
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1) / len(a)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1) / len(b)
    se = math.sqrt(va + vb)
    if se == 0:
        return {"mean": ma - mb, "ci95": [ma - mb, ma - mb], "df": None, "n_a": len(a), "n_b": len(b)}
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    half = t95(df) * se
    return {"mean": ma - mb, "ci95": [ma - mb - half, ma - mb + half], "df": df, "n_a": len(a), "n_b": len(b)}


def mean_ci(values: List[float]) -> Optional[Dict[str, Any]]:
    v = [x for x in values if x is not None and not math.isnan(x)]
    if not v:
        return None
    m = sum(v) / len(v)
    if len(v) < 2:
        return {"mean": m, "n": 1, "ci95": None}
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    half = t95(len(v) - 1) * sd / math.sqrt(len(v))
    return {"mean": m, "n": len(v), "ci95": [m - half, m + half]}


def model_tag(run: Dict[str, Any]) -> str:
    path = ((run.get("model") or {}).get("model_path") or "")
    tag = next((p for p in Path(path).parts if p.startswith("flexascale_")), path or "unknown")
    tag = tag.replace("flexascale_", "")
    controller = run["request"]["controller"]
    if controller == "hpa_fast":
        return "Native HPA, 60 s scale-down"
    if controller == "hpa_tuned":
        req = run["request"]
        return f"Native HPA, tuned ({req.get('hpa_cpu_target_pct')}% CPU, {req.get('hpa_scale_down_window_s')} s scale-down)"
    return f"{tag} (Auto mode)" if controller == "auto" else tag


def verdict(pooled: Dict[str, Any]) -> tuple[str, str]:
    def iv(key):
        x = pooled.get(key)
        return x["ci95"] if x and x.get("ci95") else None

    cost, p95, fail = iv("replica_hours_pct"), iv("p95_pct"), iv("failure_pp")
    if not (cost and p95 and fail):
        return "Not enough pairs", "unknown"
    below = lambda i: i[1] < 0
    above = lambda i: i[0] > 0
    no_harm = lambda i: not above(i)
    if below(cost) and no_harm(p95) and no_harm(fail):
        return "Beats HPA on cost", "good"
    if (below(p95) or below(fail)) and no_harm(cost):
        return "Beats HPA on performance", "good"
    if above(cost) or above(p95) or above(fail):
        return "Worse than HPA", "critical"
    return "On par with HPA", "warning"


def benchmark(runs: List[Dict[str, Any]], compare: Callable[[str, str], Dict[str, Any]], app: Optional[str] = None) -> Dict[str, Any]:
    complete = [r for r in runs if (r.get("summary") or {}).get("complete") and (app is None or r["request"]["app"] == app)]
    keyed: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in complete:
        k = (r["request"]["app"], r["request"]["scenario"], r["request"]["users"], r["request"]["duration"])
        keyed.setdefault(k, []).append(r)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for k, group in keyed.items():
        group.sort(key=lambda r: r.get("started_at") or 0)
        for cand in (r for r in group if r["request"]["controller"] in ("flexascale", "auto", "hpa_fast", "hpa_tuned")):
            block = cand["request"].get("block")
            if block:  # block designs (docs/POLICY_V7.md §3.3): the default-HPA run of the same block, in any order
                hpa = [r for r in group if r["request"]["controller"] == "hpa" and r["request"].get("block") == block]
            else:
                hpa = [r for r in group if r["request"]["controller"] == "hpa" and not r["request"].get("block")
                       and (r.get("started_at") or 0) < (cand.get("started_at") or 0)]
            if not hpa:
                continue
            cmp = compare(hpa[-1]["id"], cand["id"])
            if not cmp.get("comparable"):
                continue
            row = {x["metric"]: x for x in cmp["rows"]}
            pct = lambda m: (row.get(m) or {}).get("pct_change")
            groups.setdefault(model_tag(cand), []).append({
                "scenario": k[1], "baseline": hpa[-1]["id"], "candidate": cand["id"], "started_at": cand.get("started_at"),
                "replica_hours_pct": pct("Replica-hours"),
                "cost_pct": pct("Estimated cost") if pct("Estimated cost") is not None else pct("Resource-cost proxy"),
                "cost_basis": "estimated (list prices)" if pct("Estimated cost") is not None else "resource-cost proxy",
                "p95_pct": pct("p95 latency (ms)"),
                "failure_pp": (row.get("Failure rate (%)") or {}).get("delta"),
                "throughput_pct": pct("Throughput (req/s)"),
            })
    models = []
    for tag, pairs in groups.items():
        pairs.sort(key=lambda p: p["started_at"] or 0)
        pooled = {k: mean_ci([p[k] for p in pairs if p[k] is not None])
                  for k in ("replica_hours_pct", "cost_pct", "p95_pct", "failure_pp", "throughput_pct")}
        text, level = verdict(pooled)
        bases = sorted({p["cost_basis"] for p in pairs})
        models.append({"model": tag, "n_pairs": len(pairs), "scenarios": len({p["scenario"] for p in pairs}),
                       "pooled": pooled, "cost_basis": " + ".join(bases), "verdict": text, "verdict_level": level, "verdict_rule": VERDICT_RULE,
                       "pairs": pairs, "latest": max(p["started_at"] or 0 for p in pairs)})
    models.sort(key=lambda m: -m["latest"])
    recent = [{"id": r["id"], "controller": r["request"]["controller"], "scenario": r["request"]["scenario"],
               "replica_hours": ((r.get("summary") or {}).get("resources") or {}).get("replica_hours"),
               "p95_ms": ((r.get("summary") or {}).get("workload") or {}).get("p95_ms")}
              for r in sorted(complete, key=lambda r: r.get("started_at") or 0)]
    return {"models": models, "recent": recent[-40:]}


def load_runs(results_dir: Path) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(results_dir.glob("*/run.json")):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return out
