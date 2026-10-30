"""
Build results/: the selected, traceable results of the project (data files and SVG charts).

Every number is recomputed from a raw run (reports/experiments/<id>/run.json and Locust's CSVs) or read from a
pre-registered analysis (reports/v9/evaluation.json, reports/v7/replication.json). Nothing is typed in by hand here;
results/RESULTS.md explains the numbers this script writes.

    python scripts/build_results.py

Outputs:
    results/data/selected_runs.csv / .json    one row per selected run (configuration + every metric)
    results/data/comparisons.csv / .json      pre-registered pooled comparisons (mean delta, 95% CI, verdict)
    results/data/v9_auto_vs_default_pairs.csv per-pair deltas, v9 Auto vs default HPA
    results/charts/*.svg                      charts used in RESULTS.md
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "reports" / "experiments"
OUT = ROOT / "results"
DATA, CHARTS = OUT / "data", OUT / "charts"

COLORS = {"hpa_default": "#2563eb", "hpa_tuned": "#0891b2", "rl": "#059669", "auto": "#7c3aed", "hpa": "#2563eb",
          "flexascale": "#059669"}
LABEL = {"hpa_default": "Native HPA (default)", "hpa_tuned": "Native HPA (tuned)", "rl": "FlexaScale (v9 RL)",
         "auto": "FlexaScale Auto (v9)", "hpa": "Native HPA (default)", "flexascale": "FlexaScale (v9 RL)"}

# The selected experiments (see results/RESULTS.md for why each one is here).
SELECTED: List[Tuple[str, str, Dict[str, str]]] = [
    ("E1", "v9 block 4, flash sale: Auto vs default and tuned HPA", {}),        # filled from evaluation.json
    ("E2", "v9 block 10, flash sale: FlexaScale RL vs default and tuned HPA", {}),
    ("E3", "v9 block 2, checkout heavy: Auto and RL vs default and tuned HPA", {}),
    ("E4", "v9 block 8, checkout heavy (repeat of E3)", {}),
]
BLOCKS = {"E1": "4", "E2": "10", "E3": "2", "E4": "8"}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def locust_percentiles(run_dir: Path) -> Dict[str, Optional[float]]:
    path = run_dir / "locust_stats.csv"
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("Name") == "Aggregated":
                return {"p50_ms": _f(row.get("50%")), "p90_ms": _f(row.get("90%")), "p95_ms": _f(row.get("95%")),
                        "p99_ms": _f(row.get("99%"))}
    return {}


def run_metrics(run_id: str) -> Dict[str, Any]:
    d = RUNS / run_id
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    s = run.get("summary") or {}
    w, res, rep, util, slo = (s.get(k) or {} for k in ("workload", "resources", "replicas", "utilization", "slo"))
    req, pol = run["request"], run.get("policy") or {}
    pct = locust_percentiles(d)
    samples = run.get("samples") or []
    hpa_bounds = sorted({(v.get("hpa_min"), v.get("hpa_max")) for x in samples[:1] for v in x["services"].values()
                         if v.get("hpa_min") is not None})
    p95 = pct.get("p95_ms") if pct.get("p95_ms") is not None else w.get("p95_ms")
    ctrl = req["controller"]
    hpa_cfg = ("CPU target 70% of request, scale-down window 300 s (Kubernetes default)" if ctrl == "hpa" else
               f"CPU target {req.get('hpa_cpu_target_pct')}% of request, scale-down window {req.get('hpa_scale_down_window_s')} s"
               if ctrl == "hpa_tuned" else
               "HPA objects at 70% / 300 s; used only for services handed back to HPA" +
               (f" (run override: target {req.get('hpa_cpu_target_pct')}%, window {req.get('hpa_scale_down_window_s')} s)"
                if req.get("hpa_cpu_target_pct") or req.get("hpa_scale_down_window_s") is not None else ""))
    fs_cfg = None
    if ctrl in ("flexascale", "auto") or req.get("shadow"):
        fs_cfg = (f"policy {'variant ' + req['policy_variant'] if req.get('policy_variant') else 'default'}; model "
                  f"{str((run.get('model') or {}).get('model_path') or pol.get('model_path')).replace(chr(92), '/')}; "
                  f"{'live' if ctrl in ('flexascale', 'auto') else 'shadow (observe only)'}"
                  f"{'; Auto rules ' + json.dumps(pol.get('auto')) if ctrl == 'auto' else ''}; guards: max step +{pol.get('max_step')}/-"
                  f"{pol.get('max_scale_down_step')}, budget {pol.get('max_total_replicas')}, cooldowns "
                  f"{pol.get('scale_up_cooldown_seconds')}/{pol.get('scale_down_cooldown_seconds')} s")
    return {
        "run_id": run_id, "block": req.get("block"), "scenario": req["scenario"], "controller": ctrl,
        "users": req["users"], "spawn_rate": req["spawn_rate"], "duration_s": req["duration"],
        "actual_duration_s": s.get("actual_duration_s"), "state": run.get("state"),
        "initial_replicas": "all services at 1" if run.get("initial_replicas") and set(run["initial_replicas"].values()) == {1}
        else json.dumps(run.get("initial_replicas")),
        "hpa_bounds": ", ".join(f"{a}-{b}" for a, b in hpa_bounds) or "n/a", "hpa_config": hpa_cfg, "flexascale_config": fs_cfg,
        "throughput_rps": w.get("throughput_rps"), "total_requests": w.get("total_requests"),
        "p50_ms": pct.get("p50_ms", w.get("p50_ms")), "p90_ms": pct.get("p90_ms"), "p95_ms": p95,
        "p99_ms": pct.get("p99_ms", w.get("p99_ms")), "mean_ms": w.get("mean_latency_ms"),
        "error_rate_pct": w.get("failure_rate_pct"),
        "avg_cpu_pct_of_request": util.get("avg_cpu_pct_of_request"), "peak_cpu_pct_of_request": util.get("peak_cpu_pct_of_request"),
        "avg_memory_pct": util.get("avg_memory_pct"),
        "avg_replicas": rep.get("avg_total_desired"), "peak_replicas": rep.get("peak_total_desired"),
        "replica_hours": res.get("replica_hours"), "estimated_cost_usd": res.get("estimated_cost"),
        "cpu_allocation_efficiency_pct": res.get("cpu_allocation_efficiency_pct"),
        "e2e_slo_violation_s": slo.get("e2e_violation_seconds"), "e2e_slo_violation_fraction": slo.get("e2e_violation_fraction"),
        "sla_status": None if p95 is None else ("met (whole-run p95 <= 1000 ms)" if p95 <= 1000 else "violated (whole-run p95 > 1000 ms)"),
        "scaling_events": (s.get("stability") or {}).get("scaling_events"),
        "cleanup_safe": (run.get("cleanup") or {}).get("safe"),
        "raw": f"reports/experiments/{run_id}/",
    }


def series(run_id: str) -> Tuple[List[float], List[float], List[Optional[float]], List[Optional[float]]]:
    """Elapsed s, total ready replicas, Locust p95 (10 s window), users, from the run's 5 s samples during the load."""
    run = json.loads((RUNS / run_id / "run.json").read_text(encoding="utf-8"))
    t0 = run.get("started_at")
    xs, ready, p95, users = [], [], [], []
    for smp in run.get("samples") or []:
        if t0 is None or smp["t"] < t0:
            continue
        xs.append(smp["t"] - t0)
        ready.append(sum(int(v.get("ready") or 0) for v in smp["services"].values()))
        p95.append(_f(smp.get("p95_ms")))
        users.append(_f(smp.get("users")))
    return xs, ready, p95, users


# ------------------------------------------------------------------ SVG helpers


def svg(w: int, h: int, body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="Inter, Segoe UI, '
            f'Helvetica, Arial, sans-serif" font-size="12"><title>{title}</title><rect width="{w}" height="{h}" fill="#ffffff"/>'
            f'<text x="16" y="24" font-size="15" font-weight="600" fill="#111827">{title}</text>{body}</svg>\n')


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def forest(rows: Sequence[Dict[str, Any]], metric: str, title: str, unit: str = "%") -> str:
    """Mean and 95% CI per comparison; dashed zero line; negative = candidate lower."""
    W, L, R, T, RH = 900, 360, 150, 66, 30
    H = T + RH * len(rows) + 40
    vals = [v for r in rows for v in ([r[metric]["mean"]] + list(r[metric]["ci95"] or []))]
    lo, hi = min(vals + [0]), max(vals + [0])
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    X = lambda v: L + (v - lo) / (hi - lo) * (W - L - R)
    b = [f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{T - 8}" y2="{H - 30}" stroke="#6b7280" stroke-dasharray="4 3"/>']
    for i, r in enumerate(rows):
        y = T + RH * i + RH / 2
        m, ci = r[metric]["mean"], r[metric]["ci95"]
        col = "#059669" if ci and ci[1] < 0 else "#dc2626" if ci and ci[0] > 0 else "#6b7280"
        b.append(f'<text x="16" y="{y + 4:.1f}" fill="#111827">{esc(r["label"])}</text>')
        if ci:
            b.append(f'<line x1="{X(ci[0]):.1f}" x2="{X(ci[1]):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="2.5"/>')
        b.append(f'<circle cx="{X(m):.1f}" cy="{y:.1f}" r="5" fill="{col}"/>')
        txt = f'{m:+.1f}{unit}' + (f'  [{ci[0]:+.1f} … {ci[1]:+.1f}]' if ci else '')
        b.append(f'<text x="{W - R + 8}" y="{y + 4:.1f}" fill="#374151">{txt}</text>')
    for v in (lo + (hi - lo) * k / 4 for k in range(5)):
        b.append(f'<text x="{X(v):.1f}" y="{H - 14}" text-anchor="middle" fill="#6b7280">{v:+.0f}{unit}</text>')
    b.append(f'<text x="{L}" y="{T - 14}" fill="#6b7280">← candidate lower (better for cost/latency)</text>')
    return svg(W, H, "".join(b), title)


def lines(series_: Sequence[Tuple[str, str, List[float], List[Optional[float]]]], title: str, ylab: str, W: int = 900,
          H: int = 320, ymax: Optional[float] = None, phases: Sequence[Tuple[float, float, str]] = ()) -> str:
    L, R, T, B = 60, 20, 44, 58
    xs_all = [x for _, _, xs, _ in series_ for x in xs]
    ys_all = [y for _, _, _, ys in series_ for y in ys if y is not None]
    xmax = max(xs_all) if xs_all else 1
    ytop = ymax or (max(ys_all) * 1.1 if ys_all else 1)
    X = lambda v: L + v / xmax * (W - L - R)
    Y = lambda v: T + (1 - min(v, ytop) / ytop) * (H - T - B)
    b = []
    for a, z, name in phases:
        b.append(f'<rect x="{X(a):.1f}" y="{T}" width="{X(z) - X(a):.1f}" height="{H - T - B}" fill="#fef3c7" opacity="0.6"/>'
                 f'<text x="{X(a) + 4:.1f}" y="{T + 12}" fill="#92400e" font-size="11">{esc(name)}</text>')
    for k in range(5):
        v = ytop * k / 4
        b.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e5e7eb"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="#6b7280">{v:.0f}</text>')
    for k in range(0, int(xmax) + 1, 60):
        b.append(f'<text x="{X(k):.1f}" y="{H - B + 16}" text-anchor="middle" fill="#6b7280">{k // 60}:{k % 60:02d}</text>')
    b.append(f'<text x="{L}" y="{T - 8}" fill="#6b7280">{esc(ylab)}</text>')
    for i, (name, col, xs, ys) in enumerate(series_):
        segs, cur = [], []
        for x, y in zip(xs, ys):
            if y is None:  # a gap is drawn as a gap, never interpolated
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append(f"{X(x):.1f},{Y(y):.1f}")
        if cur:
            segs.append(cur)
        for sg in segs:
            b.append(f'<polyline points="{" ".join(sg)}" fill="none" stroke="{col}" stroke-width="2"/>')
        lx = L + i * 210
        b.append(f'<rect x="{lx}" y="{H - 22}" width="14" height="4" fill="{col}"/><text x="{lx + 20}" y="{H - 16}" fill="#374151">{esc(name)}</text>')
    b.append(f'<text x="{W - R}" y="{H - B + 32}" text-anchor="end" fill="#6b7280">time since load start (m:ss)</text>')
    return svg(W, H, "".join(b), title)


def bars(groups: Sequence[str], series_: Sequence[Tuple[str, str, List[Optional[float]]]], title: str, ylab: str,
         fmt: str = "{:.0f}", W: int = 900, H: int = 320) -> str:
    L, R, T, B = 60, 20, 44, 58
    vals = [v for _, _, vs in series_ for v in vs if v is not None]
    lo, hi = min(vals + [0]), max(vals + [0])
    span = (hi - lo) * 1.15 or 1
    hi, lo = hi + (hi - lo) * 0.15 if hi > 0 else 0, lo - (hi - lo) * 0.15 if lo < 0 else 0
    Y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    gw = (W - L - R) / len(groups)
    bw = gw * 0.8 / len(series_)
    b = [f'<line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#6b7280"/>',
         f'<text x="{L}" y="{T - 8}" fill="#6b7280">{esc(ylab)}</text>']
    for gi, g in enumerate(groups):
        gx = L + gi * gw + gw * 0.1
        b.append(f'<text x="{L + gi * gw + gw / 2:.1f}" y="{H - B + 16}" text-anchor="middle" fill="#374151">{esc(g)}</text>')
        for si, (_, col, vs) in enumerate(series_):
            v = vs[gi]
            if v is None:
                continue
            x = gx + si * bw
            y0, y1 = sorted((Y(0), Y(v)))
            b.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw - 3:.1f}" height="{max(1, y1 - y0):.1f}" fill="{col}" rx="2"/>'
                     f'<text x="{x + (bw - 3) / 2:.1f}" y="{(Y(v) - 4 if v >= 0 else Y(v) + 12):.1f}" text-anchor="middle" '
                     f'font-size="10" fill="#374151">{fmt.format(v)}</text>')
    for i, (name, col, _) in enumerate(series_):
        lx = L + i * 210
        b.append(f'<rect x="{lx}" y="{H - 22}" width="14" height="8" fill="{col}"/><text x="{lx + 20}" y="{H - 14}" fill="#374151">{esc(name)}</text>')
    return svg(W, H, "".join(b), title)


# ------------------------------------------------------------------ build


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)
    v9 = json.loads((ROOT / "reports/v9/evaluation.json").read_text(encoding="utf-8"))
    v7 = json.loads((ROOT / "reports/v7/replication.json").read_text(encoding="utf-8"))

    # 1. selected runs
    rows = []
    for key, title, _ in SELECTED:
        for arm, run_id in sorted(v9["blocks"][BLOCKS[key]].items()):
            rows.append({"experiment": key, "experiment_title": title, "arm": arm, **run_metrics(run_id)})
    ver = OUT / "verification"
    for name in ("hpa", "flexascale", "auto", "auto_sla", "auto_outage", "auto_crash", "flexascale_v7", "auto_v7", "flexascale_v7_25u"):
        p = ver / f"{name}.json"
        if p.is_file():
            rid = json.loads(p.read_text(encoding="utf-8"))["run"]["id"]
            rows.append({"experiment": "V", "experiment_title": f"verification run '{name}' (this laptop, 40 users; not a benchmark pair)",
                         "arm": name, **run_metrics(rid)})
    write_csv(DATA / "selected_runs.csv", rows)
    (DATA / "selected_runs.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    # 2. pre-registered pooled comparisons
    comps = []
    for study, src, data, names in (("v9 (second laptop, POLICY_V9 §6)", "reports/v9/evaluation.json", v9,
                                     ["hpa_tuned vs hpa_default", "rl vs hpa_default", "auto vs hpa_default",
                                      "rl vs hpa_tuned", "auto vs hpa_tuned"]),
                                    ("v7 replication (first laptop, POLICY_V7 §3.7)", "reports/v7/replication.json", v7,
                                     ["rl vs hpa_tuned", "auto vs hpa_tuned", "heuristic vs hpa_tuned"])):
        for n in names:
            c = data["comparisons"][n]
            st = c["stats"]
            comps.append({"study": study, "comparison": n, "pairs": st["replica_hours"]["n"], "verdict": c["verdict"],
                          "replica_hours": st["replica_hours"], "p95_ms": st["p95_ms"], "cost": st.get("cost"),
                          "failure_pct": st.get("failure_pct"), "throughput": st.get("throughput"), "source": src})
    (DATA / "comparisons.json").write_text(json.dumps(comps, indent=2), encoding="utf-8")
    flat = [{"study": c["study"], "comparison": c["comparison"], "pairs": c["pairs"], "verdict": c["verdict"],
             **{f"{m}_mean": (c[m] or {}).get("mean") for m in ("replica_hours", "cost", "p95_ms", "failure_pct", "throughput")},
             **{f"{m}_ci95": json.dumps([round(x, 3) for x in ((c[m] or {}).get("ci95") or [])]) for m in ("replica_hours", "p95_ms")},
             "source": c["source"]} for c in comps]
    write_csv(DATA / "comparisons.csv", flat)
    pairs = v9["comparisons"]["auto vs hpa_default"]["pairs"]
    write_csv(DATA / "v9_auto_vs_default_pairs.csv", [{k: p[k] for k in ("block", "scenario", "candidate", "reference",
                                                                           "replica_hours", "cost", "p95_ms", "p99_ms",
                                                                           "failure_pct", "throughput")} for p in pairs])

    # 3. charts
    nice = lambda n: (n.replace("hpa_default", "default HPA").replace("hpa_tuned", "tuned HPA").replace("rl", "FlexaScale RL")
                      .replace("auto", "FlexaScale Auto").replace("heuristic", "rule (no model)"))
    fr = [{"label": f"{'v9' if c['study'].startswith('v9') else 'v7'} · {nice(c['comparison'])} ({c['pairs']} pairs)",
           "replica_hours": c["replica_hours"], "p95_ms": c["p95_ms"]} for c in comps]
    (CHARTS / "forest_replica_hours.svg").write_text(forest(fr, "replica_hours", "Replica-hours: mean Δ with 95% CI (pre-registered)"), encoding="utf-8")
    (CHARTS / "forest_p95.svg").write_text(forest(fr, "p95_ms", "End-to-end p95 latency: mean Δ with 95% CI (pre-registered)"), encoding="utf-8")

    arms = v9["arms"]
    order = ["hpa_default", "hpa_tuned", "rl", "auto"]
    (CHARTS / "v9_arms.svg").write_text(bars(
        ["replica-hours ×100", "p95 ms", "p99 ms ÷10", "failures % ×100"],
        [(LABEL[a], COLORS[a], [arms[a]["replica_hours"] * 100, arms[a]["p95_ms"], arms[a]["p99_ms"] / 10, arms[a]["failure_pct"] * 100])
         for a in order], "v9 evaluation: mean per arm over all valid runs (scaled to share one axis)", "value (see scaling in the group label)"),
        encoding="utf-8")

    scen = sorted({p["scenario"] for p in pairs})
    per = lambda key: [sum(p[key] for p in pairs if p["scenario"] == s) / max(1, sum(1 for p in pairs if p["scenario"] == s)) for s in scen]
    (CHARTS / "v9_auto_vs_default_by_scenario.svg").write_text(bars(
        [s.replace("_", " ") for s in scen],
        [("Δ replica-hours %", "#7c3aed", per("replica_hours")), ("Δ p95 %", "#f59e0b", per("p95_ms"))],
        "v9: FlexaScale Auto − default HPA, mean of the pairs per scenario (negative = Auto lower)", "Δ %", fmt="{:+.0f}"),
        encoding="utf-8")

    def flash_chart(block: str, arms_: Sequence[str], name: str, title: str) -> None:
        ids = v9["blocks"][block]
        ser_r, ser_p = [], []
        dur = 300.0
        for a in arms_:
            xs, ready, p95, _ = series(ids[a])
            ser_r.append((LABEL[a], COLORS[a], xs, ready))
            ser_p.append((LABEL[a], COLORS[a], xs, p95))
        ph = [(0.25 * dur, 0.65 * dur, "flash-sale spike (peak users)")]
        (CHARTS / f"{name}_replicas.svg").write_text(lines(ser_r, f"{title}: ready replicas (all 16 services)", "ready replicas", phases=ph), encoding="utf-8")
        (CHARTS / f"{name}_p95.svg").write_text(lines(ser_p, f"{title}: end-to-end p95 (Locust, ~10 s window)", "p95 ms", phases=ph, ymax=3000), encoding="utf-8")

    flash_chart("4", ["hpa_default", "hpa_tuned", "auto"], "e1_flash_sale_b04", "E1 flash sale (v9 block 4)")
    flash_chart("10", ["hpa_default", "hpa_tuned", "rl"], "e2_flash_sale_b10", "E2 flash sale (v9 block 10)")

    vser = []
    for name, col in (("hpa", "#2563eb"), ("flexascale_v7", "#059669"), ("auto_v7", "#7c3aed"), ("auto_sla", "#db2777")):
        p = ver / f"{name}.json"
        if p.is_file():
            xs, ready, _, _ = series(json.loads(p.read_text(encoding="utf-8"))["run"]["id"])
            vser.append((name, col, xs, ready))
    if vser:
        (CHARTS / "verification_replicas.svg").write_text(lines(vser, "Verification runs (this laptop, flash sale, 40 users): ready replicas",
                                                                "ready replicas (16 services)", phases=[(75, 195, "spike")]), encoding="utf-8")
    print(f"wrote {len(rows)} runs, {len(comps)} comparisons, charts in {CHARTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
