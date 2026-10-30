#!/usr/bin/env python3
"""
Build reports/live_benchmark_report.md from raw Live Lab runs.

Every number is recomputed from reports/experiments/<run>/run.json (written by
the lab). Pairing, pooled statistics and verdicts come from
``flexascale.lab.benchmark`` (the code behind the dashboard's Comparison page),
so report and dashboard cannot disagree: every complete FlexaScale, Auto or
tuned-HPA run is paired with the most recent complete default-HPA run with the
same settings that started before it, and checked with ``Lab.compare``. Also
writes reports/live_benchmark_summary.csv (one row per run) for independent
checking.

    python scripts/build_live_report.py [--runs id1,id2,...]
"""

import argparse
import csv
import time
from collections import Counter
from pathlib import Path

from flexascale.lab.benchmark import VERDICT_RULE, benchmark, load_runs, welch_diff
from flexascale.lab.experiments import Lab

METRICS = [("replica_hours_pct", "Δ replica-h %", "%"), ("cost_pct", "Δ cost %", "%"), ("p95_pct", "Δ p95 %", "%"),
           ("failure_pp", "Δ failures pp", " pp"), ("throughput_pct", "Δ throughput %", "%")]


def g(d, path):
    for part in path.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    return d


def fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return str(v)


def signed(v, digits=1, unit=""):
    return "—" if v is None else f"{v:+.{digits}f}{unit}"


def ci_cell(x, unit):
    if not x:
        return "—"
    d = 2 if unit == " pp" else 1  # failure-rate differences are fractions of a point
    if not x.get("ci95"):
        return f"{signed(x['mean'], d, unit)} (n=1)"
    lo, hi = x["ci95"]
    return f"{signed(x['mean'], d, unit)} [{signed(lo, d)} … {signed(hi, d)}]"


def model_tag(run) -> str:
    path = ((run.get("model") or {}).get("model_path") or "")
    return next((p for p in Path(path).parts if p.startswith("flexascale_")), path or "unknown")


def group_kind(name: str) -> str:
    if name.startswith("Native HPA"):
        return "reference"
    return "auto" if "Auto" in name else "flexascale"


def scale_events(run):
    """(owner, direction) counts of replica changes the lab recorded during the run."""
    out = Counter()
    for e in run.get("events") or []:
        if e.get("kind") == "replicas" and e.get("to") is not None and e.get("frm") is not None and e["to"] != e["frm"]:
            out[(e.get("owner") or "?", "up" if e["to"] > e["frm"] else "down")] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default="", help="restrict to these run ids (comma separated)")
    ap.add_argument("--results", default="reports/experiments")
    ap.add_argument("--out", default="reports/live_benchmark_report.md")
    ap.add_argument("--csv", default="reports/live_benchmark_summary.csv")
    ap.add_argument("--host-load", default="reports/host_load_by_run.csv,reports/v9/host_load_calibration.csv,reports/v9/host_load_evaluation.csv",
                    help="outputs of scripts/check_host_load.py, comma separated (missing files are skipped)")
    args = ap.parse_args()

    runs = load_runs(Path(args.results))
    if args.runs:
        keep = set(args.runs.split(","))
        runs = [r for r in runs if r["id"] in keep]
    by_id = {r["id"]: r for r in runs}

    # per-run CSV, recomputed from the run files
    rows = []
    for r in runs:
        s = r.get("summary") or {}
        samples = r.get("samples") or []
        last_total = next((x.get("total_requests") for x in reversed(samples) if x.get("total_requests") is not None), None)
        rows.append({
            "run": r["id"], "app": r["request"]["app"], "controller": r["request"]["controller"], "model": model_tag(r),
            "scenario": r["request"]["scenario"], "users": r["request"]["users"], "duration_s": r["request"]["duration"],
            "state": r["state"], "complete": s.get("complete"), "preliminary": s.get("preliminary"),
            "requests": g(s, "workload.total_requests"), "requests_seen_in_samples": last_total,
            "throughput_rps": g(s, "workload.throughput_rps"), "failure_pct": g(s, "workload.failure_rate_pct"),
            "p50_ms": g(s, "workload.p50_ms"), "p95_ms": g(s, "workload.p95_ms"), "p99_ms": g(s, "workload.p99_ms"),
            "e2e_slo_violation_s": g(s, "slo.e2e_violation_seconds"),
            "avg_replicas": g(s, "replicas.avg_total_desired"), "peak_replicas": g(s, "replicas.peak_total_desired"),
            "replica_hours": g(s, "resources.replica_hours"), "alloc_vcpu_h": g(s, "resources.allocated_vcpu_hours"),
            "used_vcpu_h": g(s, "resources.used_vcpu_hours"), "cpu_alloc_eff_pct": g(s, "resources.cpu_allocation_efficiency_pct"),
            "estimated_cost": g(s, "resources.estimated_cost"), "cost_proxy": g(s, "resources.resource_cost_proxy"),
            "scaling_events": g(s, "stability.scaling_events"), "oscillations": g(s, "stability.oscillations"),
            "applied_scale_requests": g(s, "decisions.applied"), "cleanup_safe": (r.get("cleanup") or {}).get("safe"),
            "settled_start": next((e.get("settled") for e in r.get("events", []) if "settled" in e), None),
        })
    Path(args.csv).parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    lab = Lab()
    bench = benchmark(runs, lab.compare)
    order = {"auto": 0, "flexascale": 1, "reference": 2}
    groups = sorted(bench["models"], key=lambda m: (order[group_kind(m["model"])], -m["latest"]))
    # pre-registered block studies have their own analysis (scripts/analyze_v7.py); summarised here, not re-analysed
    studies = [m for m in groups if m.get("study")]
    groups = [m for m in groups if not m.get("study")]
    complete = [r for r in runs if (r.get("summary") or {}).get("complete")]
    services = max((len(r.get("start_replicas") or {}) for r in complete), default=0)

    L = [
        "# Live Benchmark: native HPA vs FlexaScale and Auto mode",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/build_live_report.py` from the raw runs in `{args.results}/`. "
        f"Per-run numbers are in `{args.csv}`. Pairing, statistics and verdicts use `flexascale.lab.benchmark`, the same code "
        "as the dashboard's Comparison page.",
        "",
        f"**Setup.** Minikube (1 node), the application's own HPAs (CPU target 70% of request, 1–10 replicas; the shop has "
        f"{services} managed services in the most recent runs). Locust scenarios from `load-testing/scenarios.py` through the "
        "ingress, 25 users, 300 s. Before every run the lab resets application data and scales every service to its minimum, and "
        "waits until the previous run's HPA scale-down window has passed (comparable start). Costs are estimates (allocated vCPU "
        "and memory × AWS Fargate on-demand list prices, or a unitless resource proxy where no prices were configured), not a bill.",
        "",
        "**Pairing.** Each candidate run is paired with the most recent complete default-HPA run with identical settings that "
        "started before it. Δ = candidate − HPA; negative cost, latency and failures are better. Intervals are 95% t-intervals "
        "of the mean over pairs.",
        "",
        f"**{VERDICT_RULE.split(' (', 1)[0]}** ({VERDICT_RULE.split(' (', 1)[1]}",
        "",
        "## Summary",
        "",
        "| Candidate | Pairs | Scenarios | " + " | ".join(label for _, label, _ in METRICS) + " | Cost basis | Verdict |",
        "| :--- | ---: | ---: | " + " | ".join("---:" for _ in METRICS) + " | :--- | :--- |",
    ]
    for m in groups:
        name = m["model"] if group_kind(m["model"]) == "reference" else f"FlexaScale {m['model']}"
        n = m["n_pairs"]
        verdict = m["verdict"] if n >= 6 else f"preliminary ({n} pair{'' if n == 1 else 's'})"
        L.append(f"| {name} | {m['n_pairs']} | {m['scenarios']} | "
                 + " | ".join(ci_cell(m["pooled"].get(k), unit) for k, _, unit in METRICS) + f" | {m['cost_basis']} | {verdict} |")

    if studies:
        L += ["", "## Pre-registered block studies (against default HPA)", "",
              "Runs labelled with a block (`v7-`, `v7s-`, `v7r-`, `v9-`) belong to pre-registered studies. Each arm is paired with "
              "the default-HPA run of the same block, and the verdict follows the studies' own table (`docs/POLICY_V7.md` §3.5). "
              "Their primary reference is the *tuned* HPA, and their full analysis (validity, both references, per-scenario, "
              "excluded runs) is in `reports/v7/evaluation.md`, `reports/v7/replication.md` and `reports/v9/evaluation.md` "
              "(`scripts/analyze_v7.py`). The dashboard's Comparison page shows the same verdicts.", "",
              "| Arm · study | Pairs | Scenarios | " + " | ".join(label for _, label, _ in METRICS) + " | Verdict |",
              "| :--- | ---: | ---: | " + " | ".join("---:" for _ in METRICS) + " | :--- |"]
        for m in studies:
            L.append(f"| {m['model']} | {m['n_pairs']} | {m['scenarios']} | "
                     + " | ".join(ci_cell(m["pooled"].get(k), unit) for k, _, unit in METRICS) + f" | {m['verdict']} |")

    for m in groups:
        kind = group_kind(m["model"])
        title = m["model"] if kind == "reference" else f"FlexaScale {m['model']}"
        L += ["", f"## {title} vs native HPA", ""]
        if kind == "auto":
            L += ["Auto mode decides per service and per step whether FlexaScale or native HPA owns scaling, by ordered rules "
                  "(controller health → policy confidence → SLA risk → efficiency; `docs/POLICY_V6.md` §5).", ""]
        elif kind == "reference":
            L += ["Tuned-HPA reference (`docs/POLICY_V6.md` §5.2): native HPA with only the scale-down stabilisation window "
                  "shortened from 300 s to 60 s, each run directly after the default-HPA run it is paired with, on AC power. It "
                  "asks whether Auto's saving is more than scaling down sooner, and does not change the Auto verdict.", ""]
        per = {}
        for p in m["pairs"]:
            per.setdefault(p["scenario"], []).append(p)
        L += ["Per scenario, one value per pair in run order (✓ = all pairs agree in direction, ✗ = they disagree):", "",
              "| Scenario | Pairs | Δ replica-h % | Δ p95 % | Δ failures pp | Δ throughput % |",
              "| :--- | ---: | ---: | ---: | ---: | ---: |"]

        def cell(ps, key, unit=""):
            vals = [p[key] for p in ps if p[key] is not None]
            agree = "" if len(vals) < 2 else (" ✓" if all(v <= 0 for v in vals) or all(v >= 0 for v in vals) else " ✗")
            return " / ".join(signed(v, 1, unit) for v in vals) + agree

        for scenario, ps in sorted(per.items()):
            L.append(f"| {scenario} | {len(ps)} | {cell(ps, 'replica_hours_pct', '%')} | {cell(ps, 'p95_pct', '%')} | "
                     f"{cell(ps, 'failure_pp')} | {cell(ps, 'throughput_pct', '%')} |")

        # mechanism: replica changes by owner, recomputed from the run events
        base_ids = {p["baseline"] for p in m["pairs"]}
        cand_ids = {p["candidate"] for p in m["pairs"]}
        mech = []
        for label, ids in (("default HPA (baselines)", base_ids), (title, cand_ids)):
            c = Counter()
            for i in ids:
                c.update(scale_events(by_id[i]))
            owners = sorted({o for o, _ in c})
            mech.append(f"| {label} | {len(ids)} | " + "; ".join(f"{o}: {c[(o, 'up')]} up, {c[(o, 'down')]} down" for o in owners) + " |")
        L += ["", "Replica changes recorded during the runs, by owner of the service at the time:", "",
              "| Runs | n | Scale-ups and scale-downs |", "| :--- | ---: | :--- |"] + mech

        L += ["", "| # | Scenario | HPA run | Candidate run | Δ replica-h % | Δ cost % | Δ p95 % | Δ failures pp | Δ throughput % |",
              "| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
        for i, p in enumerate(m["pairs"], 1):
            L.append(f"| {i} | {p['scenario']} | `{p['baseline']}` | `{p['candidate']}` | {signed(p['replica_hours_pct'], 1)} | "
                     f"{signed(p['cost_pct'], 1)} | {signed(p['p95_pct'], 1)} | {signed(p['failure_pp'], 2)} | {signed(p['throughput_pct'], 1)} |")

    # Auto vs tuned HPA, through their paired differences against default HPA (rule fixed in POLICY_V6 §5.2)
    auto = next((m for m in groups if group_kind(m["model"]) == "auto"), None)
    tuned = next((m for m in groups if group_kind(m["model"]) == "reference"), None)
    if auto and tuned:
        L += ["", "## Auto mode vs tuned native HPA (indirect)", "",
              f"Both are paired differences against default HPA, so they are compared through those differences: {auto['model']} "
              f"({auto['n_pairs']} pairs) minus {tuned['model']} ({tuned['n_pairs']} pair{'' if tuned['n_pairs'] == 1 else 's'}), with a "
              "95% Welch interval. The two "
              "sets use different baseline runs at different times of day, so this is indirect, and it does not change the "
              "verdicts above. Rule fixed before the six-scenario tuned batch (`docs/POLICY_V6.md` §5.2): for replica-hours, "
              "an interval below 0 means Auto saves more than a tuned HPA, above 0 means the tuned HPA saves more, and an "
              "interval that includes 0 shows no difference. p95 and failures are descriptive.", "",
              "| Metric | Auto mean Δ | Tuned-HPA mean Δ | Auto − tuned [95% CI] | Reading |",
              "| :--- | ---: | ---: | ---: | :--- |"]
        for key, label, unit in (("replica_hours_pct", "Replica-hours", "%"), ("cost_pct", "Estimated cost", "%"),
                                 ("p95_pct", "p95 latency", "%"), ("failure_pp", "Failures", " pp")):
            d = 2 if unit == " pp" else 1
            diff = welch_diff([p[key] for p in auto["pairs"]], [p[key] for p in tuned["pairs"]])
            if not diff:
                L.append(f"| {label} | {ci_cell(auto['pooled'].get(key), unit)} | {ci_cell(tuned['pooled'].get(key), unit)} | "
                         "— (needs 2+ pairs each) | — |")
                continue
            lo, hi = diff["ci95"]
            reading = "descriptive"
            if key == "replica_hours_pct":
                reading = ("Auto saves more" if hi < 0 else "tuned HPA saves more" if lo > 0 else "no difference shown")
            L.append(f"| {label} | {signed(auto['pooled'][key]['mean'], d, unit)} | {signed(tuned['pooled'][key]['mean'], d, unit)} | "
                     f"{signed(diff['mean'], d, unit)} [{signed(lo, d)} … {signed(hi, d)}] | {reading} |")

    host = {}
    for path in args.host_load.split(","):
        if Path(path).exists():
            with open(path, newline="", encoding="utf-8") as f:
                host.update({h["run"]: h for h in csv.DictReader(f)})

    def host_cell(run_id):
        h = host.get(run_id)
        if not h:
            return "—"
        cell = f"{float(h['outside_cores']):.1f} cores" if h["outside_cores"] else "no CPU data"
        if h["battery_s"] and float(h["battery_s"]) > 0:
            cell += f", battery {float(h['battery_s']):.0f} s"
        return cell + (" ⚠" if h["host_affected"] == "True" else "")

    L += ["", "## Runs", "",
          f"*Outside load* is the host CPU used outside the Kubernetes containers during the load window, and any time on battery "
          f"(`{args.host_load.replace(',', '`, `')}`, from `scripts/check_host_load.py`; ⚠ = host-affected under "
          "`docs/POLICY_V6.md` §5.2, or `docs/POLICY_V9.md` §4 for the second laptop).", "",
          "| Run | Controller | Model | Scenario | Users | State | Req/s | Fail % | p95 | Avg repl. | Replica-h | Est. cost $ | Cleanup safe | Outside load |",
          "| :--- | :--- | :--- | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |"]
    for r in rows:
        model = r["model"] if r["controller"] in ("flexascale", "auto") else "—"
        L.append(f"| {r['run']} | {r['controller']} | {model} | {r['scenario']} | {r['users']} | "
                 f"{r['state']}{' (prelim.)' if r['preliminary'] else ''} | {fmt(r['throughput_rps'])} | {fmt(r['failure_pct'])} | "
                 f"{fmt(r['p95_ms'], 0)} | {fmt(r['avg_replicas'])} | {fmt(r['replica_hours'], 4)} | {fmt(r['estimated_cost'], 4)} | "
                 f"{r['cleanup_safe']} | {host_cell(r['run'])} |")

    unsafe = [f"`{r['run']}` ({r['state']})" for r in rows if not r["cleanup_safe"]]
    L += [
        "",
        "## Exclusions and history",
        "",
        "- Runs invalidated by infrastructure or application faults are kept, with the reason, in `reports/experiments_invalid/` "
        "(see its README): host suspends and a shutdown when the battery ran out, a host clock 5.5 h fast, and the first HPA-vs-Auto batch "
        "(2026-10-25 20:02 – 2026-10-26 04:31), in which an unbounded order-history endpoint OOM-killed order-service in both arms.",
        "- The laptop ran on battery (CPU about 1 GHz, every service about 4x slower) from 2026-10-26 11:52:05 to 13:07:42. "
        "This covered 218 s of the 314 s load window of the repeat-3 gradual_ramp Auto run (its HPA arm ran on AC) and the whole last "
        "HPA-vs-Auto pair (traffic_drop, 11:55/12:07). Both pairs are kept under the pre-registered rule; without them the Auto "
        "result is -4.9% replica-hours (95% CI -7.2 … -2.6, 16 pairs), with the same verdict. The tuned-HPA runs made on "
        "battery are excluded as not comparable.",
        "- Host load: `scripts/check_host_load.py` measures, for every run, the host CPU used outside the Kubernetes containers "
        "during the load window (`reports/host_load_by_run.csv`). Under the criterion in `docs/POLICY_V6.md` §5.2 (battery, or "
        "more than 2.0 cores outside Kubernetes) three tuned-HPA pairs run between 13:08 and 14:46, when other jobs on the laptop "
        "used up to 12 extra cores, are excluded. Two were rerun; the steady_browsing rerun ran on battery (19:25–19:34) and is "
        "reported as missing. No Auto-batch run exceeded 1.64 cores outside the battery period.",
        "- Earlier batches, checked afterwards against the laptop's charge history (Prometheus host-CPU data from before the "
        "2026-10-25 Minikube restart is gone): 5 of the 12 v5 pairs ran on battery in both arms (2026-10-25 02:00–04:30; on the 7 "
        "AC pairs v5 used +6.4% replica-hours, 95% CI -6.7 … +19.5), and 3 of the 6 v4 pairs touched a battery period (on the 3 AC "
        "pairs +3.8%, CI -11.7 … +19.3). These pairs are kept, as the rules of those batches did not cover host conditions; the "
        "learned policy does not beat native HPA either way.",
        "- Demo and rehearsal runs started from the dashboard are kept in `reports/experiments_demo/` (see its README). One "
        "Auto flash_sale rehearsal (2026-10-26 13:33) would have been a 19th pair; with it the Auto result is -3.5% "
        "replica-hours (95% CI -6.1 … -0.9), with the same verdict.",
        "- All runs before 2026-10-26 04:35 (v3, v4, v5) used that unbounded endpoint, with a smaller but growing order table; its "
        "effect on those results cannot be measured afterwards.",
        "- v3 (`models/flexascale_v3`) scaled every service up on almost every decision, also in simulation (`docs/POLICY_V4.md`). "
        "v3–v5 ran on the 7-service shop; Auto mode on the 16-service shop.",
        "",
        "## How to read the cost columns",
        "",
        "- *Replica-hours* and *allocated vCPU/GiB-hours* integrate ready replicas × requested resources over the run.",
        "- *Estimated cost* = allocated vCPU-h × $0.04048 + GiB-h × $0.004445 (AWS Fargate on-demand list prices) where prices are "
        "configured; older runs use the unitless *resource-cost proxy* (vCPU-h + 0.125 × GiB-h). Neither is a cloud bill.",
        "- Lower latency bought with more replicas is a trade-off, not a free improvement; both directions are reported.",
        "",
        "## Data checks",
        "",
        f"- Runs found: {len(runs)}; complete: {len(complete)}. Runs whose cleanup was not verified safe: "
        + (", ".join(unsafe) or "none") + ".",
        "- `requests` (Locust final stats) and `requests_seen_in_samples` (last 5 s sample) are both in the CSV; they differ only "
        "by requests completed after the last sample.",
    ]
    Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(runs)} runs, {sum(m['n_pairs'] for m in groups)} pairs in {len(groups)} groups)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
