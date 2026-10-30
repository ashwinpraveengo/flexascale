#!/usr/bin/env python3
"""
Analyse the pre-registered v7 live evaluation (docs/POLICY_V7.md §3) and apply its verdict table (§3.5).

Runs are the reports/experiments/*/run.json whose block label is "v7-bNN-<arm>". A run is valid if it
completed >= 95% of its duration from a settled start and was not host-affected (reports/host_load_by_run.csv
from scripts/check_host_load.py). Pairs are formed within a block; a block without a valid run of an arm is
missing for that arm's comparisons. Writes reports/v7/evaluation.{md,json}.
With --study spike: the confirmatory flash-sale study of §3.6 (labels "v7s-bNN-<arm>", one scenario, so the
"4 of 6 scenarios" check C7 does not apply). Writes reports/v7/spike.{md,json}.

    python scripts/check_host_load.py && python scripts/analyze_v7.py [--study spike]
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flexascale.lab.benchmark import mean_ci  # noqa: E402

LABEL = re.compile(r"^v7-b(\d+)-(.+)$")
SPIKE_LABEL = re.compile(r"^v7s-b(\d+)-(.+)$")  # confirmatory flash-sale study (§3.6, withdrawn)
REPLICATION_LABEL = re.compile(r"^v7r-b(\d+)-(.+)$")  # clock-controlled replication (§3.7)
V9_LABEL = re.compile(r"^v9-b(\d+)-(.+)$")  # second laptop, docs/POLICY_V9.md §6 (same table and parity rule as §3.7)
PARITY_TOLERANCE_PCT = 10.0  # §3.7: a candidate whose shop ran > 10% faster per request in steady_browsing gets no verdict
ARM_TITLES = {"hpa_default": "HPA-default", "hpa_tuned": "HPA-tuned", "rl": "FlexaScale-RL", "auto": "FlexaScale-Auto",
              "heuristic": "FlexaScale-heuristic"}
PCT = ("replica_hours", "cost", "p50_ms", "p95_ms", "p99_ms", "mean_ms", "throughput")
ABS = ("failure_pct", "e2e_slo_s", "svc_slo_s", "events", "oscillations", "avg_replicas", "peak_replicas", "cpu_pct")


def metrics(run: dict) -> dict:
    s = run.get("summary") or {}
    w, res, slo = s.get("workload") or {}, s.get("resources") or {}, s.get("slo") or {}
    st, rep, ut = s.get("stability") or {}, s.get("replicas") or {}, s.get("utilization") or {}
    return {"replica_hours": res.get("replica_hours"), "cost": res.get("estimated_cost"), "p50_ms": w.get("p50_ms"),
            "p95_ms": w.get("p95_ms"), "p99_ms": w.get("p99_ms"), "mean_ms": w.get("mean_latency_ms"),
            "throughput": w.get("throughput_rps"), "failure_pct": w.get("failure_rate_pct"),
            "e2e_slo_s": slo.get("e2e_violation_seconds"), "svc_slo_s": slo.get("service_violation_seconds"),
            "events": st.get("scaling_events"), "oscillations": st.get("oscillations"),
            "avg_replicas": rep.get("avg_total_desired"), "peak_replicas": rep.get("peak_total_desired"),
            "cpu_pct": ut.get("avg_cpu_pct_of_request"), "recovery_s": recovery_s(run)}


def recovery_s(run: dict):
    """Seconds from the first phase change that lowers users until total desired replicas are within 1 of the run's minimum."""
    drops = [e for e in run.get("events") or [] if e.get("kind") == "traffic"]
    prev, t_drop = None, None
    for e in drops:
        u = e.get("users")
        if prev is not None and u is not None and u < prev:
            t_drop = e["t"]
            break
        prev = u
    if t_drop is None:
        return None
    series = [(smp["t"], sum(v["desired"] for v in smp["services"].values())) for smp in run.get("samples") or [] if smp.get("services")]
    if not series:
        return None
    floor = min(v for _, v in series)
    for t, v in series:
        if t >= t_drop and v <= floor + 1:
            return round(t - t_drop, 1)
    return round(series[-1][0] - t_drop, 1)


def owners(run: dict) -> dict:
    out = defaultdict(int)
    for e in run.get("events") or []:
        if e.get("kind") == "replicas":
            who = "FlexaScale" if str(e.get("owner", "")).startswith("FlexaScale") else ("HPA" if e.get("owner") == "HPA" else "other")
            out[f"{who} {'up' if e.get('to', 0) > e.get('frm', 0) else 'down'}"] += 1
    return dict(out)


def verdict(st: dict, per_scen_rh: dict, multi_scenario: bool = True) -> tuple:
    """§3.5; with multi_scenario=False (§3.6, one scenario) the "4 of 6 scenarios" check C7 does not apply."""
    def ci(k):
        return (st.get(k) or {}).get("ci95")
    rh, p95, fail = ci("replica_hours"), ci("p95_ms"), ci("failure_pct")
    if not (rh and p95 and fail):
        return "not enough pairs", {}
    m = lambda k: st[k]["mean"]
    checks = {
        "C1 replica-h interval < 0": rh[1] < 0,
        "C2 p95 not worse (interval not > 0, mean <= +10%)": p95[0] <= 0 and m("p95_ms") <= 10,
        "C3 failures not worse (interval not > 0, mean <= +0.10 pp)": fail[0] <= 0 and m("failure_pct") <= 0.10,
        "C4 throughput mean >= -2%": m("throughput") >= -2,
        "C5 e2e SLO violation mean <= +5 s": m("e2e_slo_s") <= 5,
        "C6 oscillations mean <= +5": m("oscillations") <= 5,
    }
    if multi_scenario:
        checks["C7 replica-h lower in >= 4 of 6 scenarios"] = sum(1 for v in per_scen_rh.values() if v < 0) >= 4
    if all(checks.values()):
        return "Beats on cost", checks
    perf = (p95[1] < 0 or fail[1] < 0) and rh[0] <= 0 and m("replica_hours") <= 2 and all(
        checks[k] for k in list(checks)[2:6])
    if perf:
        return "Beats on performance", checks
    if rh[0] > 0 or p95[0] > 0 or fail[0] > 0:
        return "Worse", checks
    return "On par / inconclusive", checks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(ROOT / "reports" / "experiments"))
    ap.add_argument("--host-load", default=str(ROOT / "reports" / "host_load_by_run.csv"))
    ap.add_argument("--out")
    ap.add_argument("--study", choices=["evaluation", "spike", "replication", "v9"], default="evaluation",
                    help="evaluation: the 12-block batch (§3, v7-bNN-<arm>); spike: the flash-sale study (§3.6, v7s-bNN-<arm>); "
                         "replication: the clock-controlled replication (§3.7, v7r-bNN-<arm>)")
    args = ap.parse_args()
    spike = args.study == "spike"
    label = {"evaluation": LABEL, "spike": SPIKE_LABEL, "replication": REPLICATION_LABEL, "v9": V9_LABEL}[args.study]
    args.out = args.out or (str(ROOT / "reports" / "v9" / "evaluation") if args.study == "v9" else str(ROOT / "reports" / "v7" / args.study))
    flags, clock, app_cpu = {}, {}, {}
    if Path(args.host_load).exists():
        with open(args.host_load, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            flags = {r["run"]: (r.get("host_affected"), r.get("reason") or "") for r in rows}
            clock = {r["run"]: float(r["cpu_mhz"]) for r in rows if r.get("cpu_mhz") not in (None, "", "None")}
            app_cpu = {r["run"]: float(r["app_cpu_ms_per_request"]) for r in rows
                       if r.get("app_cpu_ms_per_request") not in (None, "", "None")}

    blocks = defaultdict(dict)      # block -> arm -> run
    excluded, scen_of = [], {}
    for p in sorted(Path(args.results).glob("*/run.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        mt = label.match(str((r.get("request") or {}).get("block") or ""))
        if not mt:
            continue
        b, arm = int(mt.group(1)), mt.group(2)
        s = r.get("summary") or {}
        why = []
        if r.get("state") != "completed" or not s.get("complete"):
            why.append(f"state {r.get('state')}")
        if s.get("settled_start") is False or s.get("reset_check_passed") is False:
            why.append("start not settled")
        hf = flags.get(r["id"])
        if hf is None:
            why.append("no host-load record (run scripts/check_host_load.py)")
        elif hf[0] == "True":
            why.append(f"host-affected: {hf[1]}")
        if why:
            excluded.append({"run": r["id"], "block": b, "arm": arm, "reason": "; ".join(why)})
            continue
        if arm in blocks[b]:  # a valid rerun after an invalid run: keep the first valid one
            excluded.append({"run": r["id"], "block": b, "arm": arm, "reason": "second valid run of this arm in the block"})
            continue
        blocks[b][arm] = r
        scen_of[b] = r["request"]["scenario"]

    arms = sorted({a for b in blocks.values() for a in b}, key=lambda a: list(ARM_TITLES).index(a) if a in ARM_TITLES else 99)
    result = {"blocks": {b: {a: r["id"] for a, r in v.items()} for b, v in sorted(blocks.items())}, "excluded": excluded,
              "comparisons": {}, "arms": {}}
    title = {"evaluation": "# v7 live evaluation (docs/POLICY_V7.md §3)", "spike": "# v7 confirmatory flash-sale study (docs/POLICY_V7.md §3.6)",
             "replication": "# v7 clock-controlled replication (docs/POLICY_V7.md §3.7)",
             "v9": "# v9 live evaluation on the second laptop (docs/POLICY_V9.md §6)"}[args.study]
    lines = [title, "",
             f"{sum(len(v) for v in blocks.values())} valid runs in {len(blocks)} blocks; {len(excluded)} excluded. "
             "Pairs are within block; Δ = candidate − reference; 95% t-intervals over pairs; d_z = mean / SD of the paired differences.", ""]

    lines += ["## Arms (means over valid runs)", "", "| Arm | runs | replica-h | cost USD | p50 ms | p95 ms | p99 ms | mean ms | failures % | req/s | e2e SLO s | events | osc |",
              "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for a in arms:
        ms = [metrics(v[a]) for v in blocks.values() if a in v]
        avg = lambda k: sum(x[k] for x in ms if x[k] is not None) / max(1, sum(1 for x in ms if x[k] is not None))
        result["arms"][a] = {k: avg(k) for k in PCT + ABS}
        lines.append(f"| {ARM_TITLES.get(a, a)} | {len(ms)} | {avg('replica_hours'):.3f} | {avg('cost'):.5f} | {avg('p50_ms'):.0f} | "
                     f"{avg('p95_ms'):.0f} | {avg('p99_ms'):.0f} | {avg('mean_ms'):.0f} | {avg('failure_pct'):.3f} | {avg('throughput'):.2f} | "
                     f"{avg('e2e_slo_s'):.1f} | {avg('events'):.1f} | {avg('oscillations'):.1f} |")

    for ref in ("hpa_tuned", "hpa_default"):
        if ref not in arms:
            continue
        lines += ["", f"## Against {ARM_TITLES[ref]}", ""]
        for cand in arms:
            if cand == ref or (ref == "hpa_default" and cand == "hpa_tuned" and False):
                continue
            pairs = []
            for b, v in sorted(blocks.items()):
                if cand in v and ref in v:
                    c, r = metrics(v[cand]), metrics(v[ref])
                    d = {"block": b, "scenario": scen_of[b], "candidate": v[cand]["id"], "reference": v[ref]["id"]}
                    for k in PCT:
                        d[k] = None if not (c[k] is not None and r[k]) else 100.0 * (c[k] - r[k]) / r[k]
                    for k in ABS:
                        d[k] = None if c[k] is None or r[k] is None else c[k] - r[k]
                    pairs.append(d)
            if not pairs:
                continue
            st = {}
            for k in PCT + ABS:
                vals = [p[k] for p in pairs if p[k] is not None]
                ci = mean_ci(vals)
                if ci and len(vals) >= 2:
                    sd = math.sqrt(sum((x - ci["mean"]) ** 2 for x in vals) / (len(vals) - 1))
                    ci["dz"] = ci["mean"] / sd if sd > 0 else None
                st[k] = ci
            per_scen = defaultdict(list)
            for p in pairs:
                per_scen[p["scenario"]].append(p)
            per_scen_rh = {s: sum(p["replica_hours"] for p in ps) / len(ps) for s, ps in per_scen.items()}
            text, checks = verdict(st, per_scen_rh, multi_scenario=not spike)
            # environment parity (§5 2026-10-27 19:19, §3.7): mean CPU clock (descriptive; it mostly counts busy cores) and the
            # shop's CPU-seconds per request in steady_browsing, where every arm keeps every service at one replica
            cm, rm = [clock.get(p["candidate"]) for p in pairs], [clock.get(p["reference"]) for p in pairs]
            clock_delta = (100.0 * (sum(cm) - sum(rm)) / sum(rm)) if pairs and None not in cm + rm else None
            steady = [p for p in pairs if p["scenario"] == "steady_browsing"]
            ca, ra = [app_cpu.get(p["candidate"]) for p in steady], [app_cpu.get(p["reference"]) for p in steady]
            parity = (100.0 * (sum(ca) - sum(ra)) / sum(ra)) if steady and None not in ca + ra else None
            if args.study in ("replication", "v9") and (parity is None or parity < -PARITY_TOLERANCE_PCT):
                text = "No verdict: environment parity " + ("not measured" if parity is None else
                                                            f"failed (shop CPU per request {parity:+.1f}% in steady_browsing)")
            result["comparisons"][f"{cand} vs {ref}"] = {"pairs": pairs, "stats": st, "verdict": text, "checks": checks,
                                                         "per_scenario_replica_hours": per_scen_rh, "cpu_clock_delta_pct": clock_delta,
                                                         "steady_app_cpu_per_request_delta_pct": parity}
            fmt = lambda k, unit="%": (f"{st[k]['mean']:+.1f}{unit} [{st[k]['ci95'][0]:+.1f} … {st[k]['ci95'][1]:+.1f}]"
                                       if st.get(k) and st[k].get("ci95") else "–")
            fmt2 = lambda k: (f"{st[k]['mean']:+.2f} pp [{st[k]['ci95'][0]:+.2f} … {st[k]['ci95'][1]:+.2f}]"
                              if st.get(k) and st[k].get("ci95") else "–")
            lines += [f"### {ARM_TITLES.get(cand, cand)} vs {ARM_TITLES[ref]}: **{text}** ({len(pairs)} pairs)", "",
                      "| Metric | Mean Δ [95% CI] | d_z |", "| :--- | :--- | ---: |"]
            for k, label, f_ in (("replica_hours", "Replica-hours", fmt), ("cost", "Estimated cost", fmt),
                                 ("p50_ms", "p50", fmt), ("p95_ms", "p95", fmt), ("p99_ms", "p99", fmt), ("mean_ms", "Mean latency", fmt),
                                 ("failure_pct", "Failures", fmt2), ("throughput", "Throughput", fmt),
                                 ("e2e_slo_s", "E2E SLO violation (s)", lambda k: fmt(k, " s")),
                                 ("oscillations", "Oscillations", lambda k: fmt(k, "")), ("events", "Scaling events", lambda k: fmt(k, ""))):
                dz = (st.get(k) or {}).get("dz")
                lines.append(f"| {label} | {f_(k)} | {'' if dz is None else f'{dz:+.2f}'} |")
            lines += ["", "Checks: " + "; ".join(f"{k}: {'yes' if ok else 'no'}" for k, ok in checks.items()), "",
                      "Environment: shop CPU per request in steady_browsing " + (f"{parity:+.1f}% (candidate vs reference)" if parity is not None
                                                                                  else "not measured")
                      + "; mean CPU clock " + (f"{sum(cm) / len(cm):.0f} vs {sum(rm) / len(rm):.0f} MHz (Δ {clock_delta:+.1f}%, mostly busy cores)"
                                               if clock_delta is not None else "not recorded") + ".", "",
                      "Per scenario (replica-h Δ% per pair; p95 Δ% per pair):", ""]
            for s, ps in sorted(per_scen.items()):
                lines.append(f"* {s}: " + " / ".join(f"{p['replica_hours']:+.1f}" for p in ps) + "  |  "
                             + " / ".join(f"{p['p95_ms']:+.1f}" if p['p95_ms'] is not None else "–" for p in ps))
            lines.append("")

    lines += ["## Recovery after load decreases (descriptive, flash_sale and traffic_drop)", "",
              "Seconds from the phase change that lowers users until total desired replicas are within 1 of the run's minimum.", "",
              "| Arm | runs | mean s | values |", "| :--- | ---: | ---: | :--- |"]
    for a in arms:
        rec = [metrics(v[a])["recovery_s"] for v in blocks.values() if a in v]
        rec = [x for x in rec if x is not None]
        result["arms"][a]["recovery_s"] = rec
        lines.append(f"| {ARM_TITLES.get(a, a)} | {len(rec)} | {(sum(rec) / len(rec)) if rec else float('nan'):.0f} | "
                     f"{', '.join(f'{x:.0f}' for x in rec) or '–'} |")
    lines += [""]

    lines += ["## Attribution (replica changes by owner during the runs)", "", "| Arm | changes by owner (sum over runs) | Auto rule decisions |", "| :--- | :--- | :--- |"]
    for a in arms:
        tot, rules = defaultdict(int), defaultdict(int)
        for v in blocks.values():
            if a in v:
                for k, n in owners(v[a]).items():
                    tot[k] += n
                for k, n in (v[a].get("auto_counts") or {}).items():
                    rules[k] += n
        result["arms"][a]["owners"] = dict(tot)
        result["arms"][a]["auto_rules"] = dict(rules)
        lines.append(f"| {ARM_TITLES.get(a, a)} | {', '.join(f'{k}: {n}' for k, n in sorted(tot.items())) or '–'} | "
                     f"{', '.join(f'{k}: {n}' for k, n in sorted(rules.items())) or '–'} |")
    if excluded:
        lines += ["", "## Excluded runs", ""] + [f"* `{e['run']}` (block {e['block']}, {e['arm']}): {e['reason']}" for e in excluded]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
