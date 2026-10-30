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
docs/POLICY_V6.md section 3.1 before any v6 result was seen. The pre-registered block studies (STUDY_SUFFIXES) use
their own table, docs/POLICY_V7.md §3.5, against either reference, and their runs' validity is the per-run rule of
§3.4 (complete, settled start), so a pair is not dropped for a duration difference alone: the same verdicts as
scripts/analyze_v7.py.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flexascale.evaluation.cost import percent_change

# two-sided 95% Student t critical values by degrees of freedom
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}

REFERENCES = {"hpa": "native HPA (default)", "hpa_tuned": "native HPA, tuned"}
SPIKE_SUFFIX = " · flash-sale study (POLICY_V7 §3.6)"
# each pre-registered study is its own group, never pooled with another (docs/POLICY_V7.md §3.6, §3.7, §5)
STUDY_SUFFIXES = {"v7s-": SPIKE_SUFFIX, "v7r-": " · clock-controlled replication (POLICY_V7 §3.7)",
                  "v7-": " · 12-block batch, CPU-clock confounded (POLICY_V7 §5)",
                  "v9-": " · second laptop, pre-registered (POLICY_V9 §6)"}
VERDICT_RULE_V7 = ("Verdict rule (docs/POLICY_V7.md §3.5, fixed before the v7 runs): beats on cost = replica-hours interval below 0, "
                   "p95 interval not entirely above 0 with mean <= +10%, failure interval not entirely above 0 with mean <= +0.10 pp, "
                   "throughput mean >= -2%, end-to-end SLO-violation mean <= +5 s, oscillations mean <= +5, and replica-hours lower "
                   "in at least 4 of 6 scenarios; beats on performance = p95 or failure interval below 0 with the replica-hours "
                   "interval not entirely above 0 and mean <= +2% (and the same failure, throughput, SLO and oscillation checks); "
                   "worse = a replica-hours, p95 or failure interval entirely above 0 without such a gain; otherwise on par.")
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
    rule = (run.get("policy") or {}).get("controller_rule") or {}
    if rule:  # a hand-written rule in place of the model (docs/POLICY_V7.md §3.2 attribution arm)
        tag = f"Rule {rule.get('type')}({rule.get('target')}/{rule.get('down')})"
        return f"{tag} (Auto mode)" if run["request"]["controller"] == "auto" else tag
    path = ((run.get("model") or {}).get("model_path") or "")
    tag = next((p for p in Path(path).parts if p.startswith("flexascale_")), path or "unknown")
    tag = tag.replace("flexascale_", "")
    controller = run["request"]["controller"]
    if controller == "hpa":
        return "Native HPA (default)"
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


def verdict_v7(pooled: Dict[str, Any], per_scenario_rh: Dict[str, float], multi_scenario: bool = True) -> tuple[str, str]:
    """docs/POLICY_V7.md §3.5 (the same table as scripts/analyze_v7.py); for the one-scenario flash-sale study (§3.6)
    the "4 of 6 scenarios" condition does not apply."""
    def iv(key):
        x = pooled.get(key)
        return x["ci95"] if x and x.get("ci95") else None

    def mean(key):
        x = pooled.get(key)
        return x["mean"] if x else None

    rh, p95, fail = iv("replica_hours_pct"), iv("p95_pct"), iv("failure_pp")
    if not (rh and p95 and fail):
        return "Not enough pairs", "unknown"
    guards = (fail[0] <= 0 and mean("failure_pp") <= 0.10 and (mean("throughput_pct") or 0) >= -2
              and (mean("e2e_slo_s") or 0) <= 5 and (mean("oscillations") or 0) <= 5)
    if rh[1] < 0 and p95[0] <= 0 and mean("p95_pct") <= 10 and guards and \
            (not multi_scenario or sum(1 for v in per_scenario_rh.values() if v < 0) >= 4):
        return "Beats on cost", "good"
    if (p95[1] < 0 or fail[1] < 0) and rh[0] <= 0 and mean("replica_hours_pct") <= 2 and guards:
        return "Beats on performance", "good"
    if rh[0] > 0 or p95[0] > 0 or fail[0] > 0:
        return "Worse", "critical"
    return "On par / inconclusive", "warning"


def benchmark(runs: List[Dict[str, Any]], compare: Callable[[str, str], Dict[str, Any]], app: Optional[str] = None,
              reference: str = "hpa") -> Dict[str, Any]:
    """Paired candidates against ``reference``: 'hpa' (default HPA; the dashboard's original rule) or 'hpa_tuned'
    (POLICY_V7's fair baseline; block-labelled runs only, verdict table §3.5)."""
    if reference not in REFERENCES:
        raise ValueError(f"reference must be one of {sorted(REFERENCES)}")
    complete = [r for r in runs if (r.get("summary") or {}).get("complete") and (app is None or r["request"]["app"] == app)]
    keyed: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in complete:
        k = (r["request"]["app"], r["request"]["scenario"], r["request"]["users"], r["request"]["duration"])
        keyed.setdefault(k, []).append(r)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    studies = set()  # tags of pre-registered block studies
    for k, group in keyed.items():
        group.sort(key=lambda r: r.get("started_at") or 0)
        for cand in (r for r in group if r["request"]["controller"] in {"hpa", "flexascale", "auto", "hpa_fast", "hpa_tuned"} - {reference}):
            block = cand["request"].get("block")
            if block:  # block designs (docs/POLICY_V7.md §3.3): the reference run of the same block, in any order
                hpa = [r for r in group if r["request"]["controller"] == reference
                       and _block_id(r["request"].get("block")) == _block_id(block)]
            elif reference == "hpa":
                hpa = [r for r in group if r["request"]["controller"] == "hpa" and not r["request"].get("block")
                       and (r.get("started_at") or 0) < (cand.get("started_at") or 0)]
            else:
                hpa = []
            if not hpa:
                continue
            cmp = compare(hpa[-1]["id"], cand["id"])
            bid = str(_block_id(block) or "")
            study = next((sfx for pre, sfx in STUDY_SUFFIXES.items() if bid.startswith(pre)), "")
            if not (cmp.get("comparable") or (study and cmp.get("rows") and
                                              all(i.startswith("durations differ") for i in cmp.get("issues") or []))):
                continue
            row = {x["metric"]: x for x in cmp["rows"]}

            def pct(m):  # Lab.compare leaves pct_change empty for a flagged pair; a study pair kept above gets it here
                r = row.get(m) or {}
                if r.get("pct_change") is not None or cmp.get("comparable"):
                    return r.get("pct_change")
                p = percent_change(r.get("baseline"), r.get("candidate"))
                return round(p, 2) if p is not None else None

            tag = model_tag(cand) + study
            if study:
                studies.add(tag)
            groups.setdefault(tag, []).append({
                "scenario": k[1], "baseline": hpa[-1]["id"], "candidate": cand["id"], "started_at": cand.get("started_at"),
                "replica_hours_pct": pct("Replica-hours"),
                "cost_pct": pct("Estimated cost") if pct("Estimated cost") is not None else pct("Resource-cost proxy"),
                "cost_basis": "estimated (list prices)" if pct("Estimated cost") is not None else "resource-cost proxy",
                "p95_pct": pct("p95 latency (ms)"),
                "failure_pp": (row.get("Failure rate (%)") or {}).get("delta"),
                "throughput_pct": pct("Throughput (req/s)"),
                "e2e_slo_s": (row.get("E2E p95 SLO violation (s)") or {}).get("delta"),
                "oscillations": (row.get("Oscillations (reversals)") or {}).get("delta"),
            })
    models = []
    for tag, pairs in groups.items():
        pairs.sort(key=lambda p: p["started_at"] or 0)
        pooled = {k: mean_ci([p[k] for p in pairs if p.get(k) is not None])
                  for k in ("replica_hours_pct", "cost_pct", "p95_pct", "failure_pp", "throughput_pct", "e2e_slo_s", "oscillations")}
        table_v7 = reference == "hpa_tuned" or tag in studies
        if table_v7:
            by_scen: Dict[str, List[float]] = {}
            for p in pairs:
                if p["replica_hours_pct"] is not None:
                    by_scen.setdefault(p["scenario"], []).append(p["replica_hours_pct"])
            text, level = verdict_v7(pooled, {k: sum(v) / len(v) for k, v in by_scen.items()},
                                     multi_scenario=not tag.endswith(SPIKE_SUFFIX))
        else:
            text, level = verdict(pooled)
        bases = sorted({p["cost_basis"] for p in pairs})
        models.append({"model": tag, "study": tag in studies, "n_pairs": len(pairs), "scenarios": len({p["scenario"] for p in pairs}),
                       "pooled": pooled, "cost_basis": " + ".join(bases), "verdict": text, "verdict_level": level,
                       "verdict_rule": VERDICT_RULE_V7 if table_v7 else VERDICT_RULE,
                       "pairs": pairs, "latest": max(p["started_at"] or 0 for p in pairs)})
    models.sort(key=lambda m: -m["latest"])
    recent = [{"id": r["id"], "controller": r["request"]["controller"], "scenario": r["request"]["scenario"],
               "replica_hours": ((r.get("summary") or {}).get("resources") or {}).get("replica_hours"),
               "p95_ms": ((r.get("summary") or {}).get("workload") or {}).get("p95_ms")}
              for r in sorted(complete, key=lambda r: r.get("started_at") or 0)]
    return {"models": models, "recent": recent[-40:], "reference": reference, "reference_label": REFERENCES[reference]}


def _block_id(label: Optional[str]) -> Optional[str]:
    """'v7-b03-rl' -> 'v7-b03': arms of one block share the prefix before the arm name."""
    if not label:
        return None
    parts = str(label).split("-")
    return "-".join(parts[:2]) if len(parts) >= 3 and parts[1].startswith("b") else str(label)


def load_runs(results_dir: Path) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(results_dir.glob("*/run.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out
