#!/usr/bin/env python3
"""
Build reports/live_benchmark_report.md from raw Live Lab runs.

Every number is recomputed from reports/experiments/<run>/run.json (written by
the lab). Every complete FlexaScale run is paired with the most recent complete
HPA run with the same settings that started before it, grouped by FlexaScale
model; pairs are checked with the same comparability rules as the dashboard
(Lab.compare). Also writes
reports/live_benchmark_summary.csv (one row per run) for independent checking.

    python scripts/build_live_report.py [--runs id1,id2,...]
"""

import argparse
import csv
import json
import time
from pathlib import Path

from flexascale.lab.experiments import Lab

RESULTS = Path("reports/experiments")


def g(d, path):
    for part in path.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    return d


def model_tag(run) -> str:
    path = ((run.get("model") or {}).get("model_path") or "")
    parts = Path(path).parts
    return next((p for p in parts if p.startswith("flexascale_")), path or "unknown")


def fmt(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default="", help="restrict to these run ids (comma separated)")
    ap.add_argument("--out", default="reports/live_benchmark_report.md")
    args = ap.parse_args()

    runs = []
    for path in sorted(RESULTS.glob("*/run.json")):
        data = json.loads(path.read_text())
        if args.runs and data["id"] not in args.runs.split(","):
            continue
        runs.append(data)

    # per-run CSV + sanity checks recomputed from raw samples
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
            "cost_proxy": g(s, "resources.resource_cost_proxy"), "scaling_events": g(s, "stability.scaling_events"),
            "oscillations": g(s, "stability.oscillations"), "applied_scale_requests": g(s, "decisions.applied"),
            "cleanup_safe": (r.get("cleanup") or {}).get("safe"),
            "settled_start": next((e.get("settled") for e in r.get("events", []) if "settled" in e), None),
        })
    Path("reports/live_benchmark_summary.csv").parent.mkdir(parents=True, exist_ok=True)
    with open("reports/live_benchmark_summary.csv", "w", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    # Pair runs per (app, scenario, users, duration) and FlexaScale model: each
    # FlexaScale run is compared with the most recent complete HPA run before it.
    lab = Lab()
    complete = [r for r in runs if (r.get("summary") or {}).get("complete")]
    keyed = {}
    for r in complete:
        k = (r["request"]["app"], r["request"]["scenario"], r["request"]["users"], r["request"]["duration"])
        keyed.setdefault(k, []).append(r)
    by_model = {}
    for k, group in sorted(keyed.items()):
        group.sort(key=lambda r: r["started_at"] or 0)
        for fs in (r for r in group if r["request"]["controller"] == "flexascale"):
            hpa = [r for r in group if r["request"]["controller"] == "hpa" and (r["started_at"] or 0) < (fs["started_at"] or 0)]
            if hpa:
                cmp = lab.compare(hpa[-1]["id"], fs["id"])
                by_model.setdefault(model_tag(fs), []).append((k, hpa[-1], fs, cmp))

    L = [
        "# Live Benchmark: Native HPA vs FlexaScale",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/build_live_report.py` from the raw runs in `reports/experiments/`. "
        "Per-run numbers are also in `reports/live_benchmark_summary.csv`.",
        "",
        "**Setup.** Minikube (1 node), the application's own HPAs (shopping: seven FastAPI services, CPU request 100m, "
        "limit 500m, 70% CPU, 1-10 replicas). Locust scenarios from `load-testing/scenarios.py` through the ingress. Before every "
        "run the lab resets all services to 1 replica and checks that the HPAs stay there (comparable start). FlexaScale runs use "
        "the safety layer (confidence >= 0.70 to take ownership, < 0.60 to hand back to HPA) and the model named in each section. "
        "End-to-end SLO: Locust p95 <= 1000 ms over 10 s windows.",
        "",
        "Each FlexaScale run is paired with the most recent complete HPA run with identical settings that started before it. "
        "With one or two pairs per scenario the results are indicative, not statistically established.",
        "",
        "## Runs",
        "",
        "| Run | Controller | Model | Scenario | Users | State | Req/s | Fail % | p50 | p95 | p99 | SLO viol. s | Avg repl. | Replica-h | Cost proxy | Scale events | Cleanup safe |",
        "| :--- | :--- | :--- | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for r in rows:
        L.append(f"| {r['run']} | {r['controller']} | {r['model'] if r['controller'] == 'flexascale' else '—'} | {r['scenario']} | {r['users']} | "
                 f"{r['state']}{' (prelim.)' if r['preliminary'] else ''} | "
                 f"{fmt(r['throughput_rps'])} | {fmt(r['failure_pct'])} | {fmt(r['p50_ms'], 0)} | {fmt(r['p95_ms'], 0)} | {fmt(r['p99_ms'], 0)} | "
                 f"{fmt(r['e2e_slo_violation_s'], 0)} | {fmt(r['avg_replicas'])} | {fmt(r['replica_hours'], 4)} | {fmt(r['cost_proxy'], 5)} | "
                 f"{fmt(r['scaling_events'])} | {r['cleanup_safe']} |")

    key_metrics = ["Throughput (req/s)", "Failure rate (%)", "p50 latency (ms)", "p95 latency (ms)", "p99 latency (ms)",
                   "E2E p95 SLO violation (s)", "Avg total replicas", "Peak total replicas", "Replica-hours",
                   "Allocated vCPU-hours", "CPU allocation efficiency (%)", "Resource-cost proxy", "Scaling events",
                   "Oscillations (reversals)"]

    def pct(cmp, metric):
        row = next((x for x in cmp["rows"] if x["metric"] == metric), None)
        return row and row["pct_change"]

    if not by_model:
        L += ["", "No complete HPA/FlexaScale pair with identical settings was found."]
    for tag in sorted(by_model, reverse=True):
        pairs = by_model[tag]
        L += ["", f"## FlexaScale model `{tag}` vs native HPA", "",
              "| Scenario | Users | HPA run | FlexaScale run | Comparable | Δ p95 % | Δ throughput % | Δ failures pp | Δ SLO-violation s | Δ replica-h % | Δ cost proxy % |",
              "| :--- | ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for (app, scenario, users, duration), a, b, cmp in pairs:
            slo = next((x for x in cmp["rows"] if x["metric"] == "E2E p95 SLO violation (s)"), {})
            fail = next((x for x in cmp["rows"] if x["metric"] == "Failure rate (%)"), {})
            p = lambda m: "—" if pct(cmp, m) is None else f"{pct(cmp, m):+.1f}%"
            L.append(f"| {scenario} | {users} | `{a['id']}` | `{b['id']}` | {cmp['comparable']} | {p('p95 latency (ms)')} | "
                     f"{p('Throughput (req/s)')} | {'—' if fail.get('delta') is None else f'{fail['delta']:+.1f}'} | {fmt(slo.get('delta'), 0)} | {p('Replica-hours')} | {p('Resource-cost proxy')} |")
        ok = [(k, a, b, c) for k, a, b, c in pairs if c["comparable"]]
        if ok:
            def avg(metric):
                vals = [pct(c, metric) for *_, c in ok if pct(c, metric) is not None]
                return sum(vals) / len(vals) if vals else None
            fails = [r["delta"] for *_, c in ok for r in c["rows"] if r["metric"] == "Failure rate (%)" and r["delta"] is not None]
            fail_pp = sum(fails) / len(fails) if fails else float("nan")
            L += ["", f"Mean over {len(ok)} comparable pair(s): p95 latency {avg('p95 latency (ms)'):+.1f}%, throughput "
                  f"{avg('Throughput (req/s)'):+.1f}%, failure rate {fail_pp:+.1f} pp, replica-hours {avg('Replica-hours'):+.1f}%, resource-cost proxy "
                  f"{avg('Resource-cost proxy'):+.1f}% (negative cost = saving relative to HPA in the same scenario)."]
        for (app, scenario, users, duration), a, b, cmp in pairs:
            L += ["", f"### {tag}: {scenario} ({users} users, {duration} s)", "",
                  f"Baseline `{a['id']}` vs candidate `{b['id']}`. Comparable: **{cmp['comparable']}**"
                  + ("" if cmp["comparable"] else f" ({'; '.join(cmp['issues'])})"), "",
                  "| Metric | HPA | FlexaScale | Δ | Δ % |", "| :--- | ---: | ---: | ---: | ---: |"]
            for row in cmp["rows"]:
                if row["metric"] in key_metrics:
                    pc = row["pct_change"]
                    L.append(f"| {row['metric']} | {fmt(row['baseline'], 4)} | {fmt(row['candidate'], 4)} | {fmt(row['delta'], 4)} | "
                             f"{'—' if pc is None else f'{pc:+.1f}%'} |")

    L += ["", "## Notes on the v3 runs", "",
          "- v3 (`models/flexascale_v3`) scaled every service up on almost every decision, also in simulation; its live runs used "
          "58-98% more replica-hours without better latency. The cause (simulator and reward defects) and the v4 redesign are in "
          "`docs/POLICY_V4.md`.",
          "- Earlier 40-user runs (2026-10-22 23:36 and 23:47) are excluded: the FlexaScale run started unsettled and exhausted "
          "node memory (45 replicas, 42.6% failures, API server down). That incident led to the app-wide replica budget.",
          "",
          "## Notes on the v4 runs", "",
          "- v4 (`models/flexascale_v4/best_model`, selection in `docs/POLICY_V4.md`) ran all six scenarios on 2026-10-24, "
          "alternating with HPA, 25 users, 300 s, with `scale_up_cooldown_seconds: 30`.",
          "- The per-scenario differences point in both directions (e.g. p95 −49% but failures +10 pp under payment degradation; "
          "p95 +50% under steady browsing). With one run per arm they cannot be separated from run-to-run noise.",
          "- One HPA checkout_heavy run (2026-10-24 15:45) was invalidated by a host suspend and moved to "
          "`reports/experiments_invalid/` with the reason; it was rerun.",
          ""]
    L += [
        "## How to read the cost rows",
        "",
        "- *Replica-hours* and *allocated vCPU/GiB-hours* integrate the ready replicas x requested resources over the run.",
        "- *CPU allocation efficiency* = observed CPU (cAdvisor) / allocated CPU.",
        "- *Resource-cost proxy* = vCPU-h + 0.125 x GiB-h of requested resources (no prices are configured for the shop). "
        "It is unitless and not a cloud bill. A negative Δ% is a saving relative to HPA in the same scenario only.",
        "- Lower latency bought with more replicas is a trade-off, not a free improvement; both directions are reported.",
        "",
        "## Data checks",
        "",
        f"- Runs found: {len(runs)}; complete: {len(complete)}. Runs whose cleanup was not verified safe: "
        + (", ".join(f"`{r['run']}` ({r['state']})" for r in rows if not r["cleanup_safe"]) or "none")
        + ". Failed runs never started load (preflight refusals); the completed one is the excluded 40-user incident run.",
        "- `requests` (Locust final stats) and `requests_seen_in_samples` (last 5 s sample) are both listed in the CSV; "
        "they differ only by requests completed after the last sample.",
    ]
    Path(args.out).write_text("\n".join(L) + "\n")
    print(f"Wrote {args.out} ({len(runs)} runs, {sum(len(v) for v in by_model.values())} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
