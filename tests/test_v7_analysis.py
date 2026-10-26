"""Pre-registered v7 analyses (docs/POLICY_V7.md §2.1 calibration rule, §3.5 verdict table) on synthetic runs."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp, rid, controller, scenario, block, p95, mean=50.0, fail=0.1, rh=1.5, target=None, osc=1, slo=0.0, rps=10.0):
    d = tmp / "runs" / rid
    d.mkdir(parents=True)
    req = {"app": "shopping", "controller": controller, "scenario": scenario, "block": block}
    if target:
        req["hpa_cpu_target_pct"] = target
    (d / "run.json").write_text(json.dumps({
        "id": rid, "state": "completed", "request": req, "events": [], "samples": [],
        "summary": {"complete": True, "settled_start": True, "reset_check_passed": True,
                    "workload": {"p95_ms": p95, "p50_ms": 20, "p99_ms": 2 * p95, "mean_latency_ms": mean,
                                 "failure_rate_pct": fail, "throughput_rps": rps},
                    "resources": {"replica_hours": rh, "estimated_cost": rh * 0.005},
                    "slo": {"e2e_violation_seconds": slo, "service_violation_seconds": 0},
                    "stability": {"scaling_events": 2, "oscillations": osc},
                    "replicas": {"avg_total_desired": 17, "peak_total_desired": 20},
                    "utilization": {"avg_cpu_pct_of_request": 20}}}))
    return rid


def _host(tmp, rids, affected=()):
    with open(tmp / "host.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "host_affected", "reason"])
        w.writeheader()
        for r in rids:
            w.writerow({"run": r, "host_affected": str(r in affected), "reason": "on battery 30 s" if r in affected else ""})


def test_calibration_picks_the_highest_target_whose_lower_values_all_pass(tmp_path, monkeypatch):
    mod = _load("analyze_v7_calibration")
    vals = {70: (100, 50, 0.1), 150: (105, 52, 0.12), 250: (125, 53, 0.1), 350: (104, 51, 0.1)}  # 250 fails p95
    rids = [_run(tmp_path, f"c{t}-{k}", "hpa_tuned", "calibration_steady", f"cal-{t}", p, m, f, target=t)
            for t, (p, m, f) in vals.items() for k in range(2)]
    _host(tmp_path, rids)
    monkeypatch.setattr(sys, "argv", ["x", "--results", str(tmp_path / "runs"), "--host-load", str(tmp_path / "host.csv"),
                                      "--out", str(tmp_path / "cal")])
    mod.main()
    out = json.loads((tmp_path / "cal.json").read_text())
    assert out["selected_cpu_target_pct"] == 150  # 350 passes but 250 below it does not


def test_calibration_ignores_host_affected_runs(tmp_path, monkeypatch):
    mod = _load("analyze_v7_calibration")
    rids = [_run(tmp_path, f"c{t}-{k}", "hpa_tuned", "calibration_steady", f"cal-{t}", 100, 50, 0.1, target=t)
            for t in (70, 150, 250, 350) for k in range(2)]
    _host(tmp_path, rids, affected={"c350-1"})
    monkeypatch.setattr(sys, "argv", ["x", "--results", str(tmp_path / "runs"), "--host-load", str(tmp_path / "host.csv"),
                                      "--out", str(tmp_path / "cal")])
    mod.main()
    out = json.loads((tmp_path / "cal.json").read_text())
    assert out["incomplete_targets"] == [350] and any(e["run"] == "c350-1" for e in out["excluded"])


def _eval_runs(tmp, cand_rh, cand_p95):
    rids, b = [], 0
    for rep in range(2):
        for s in ("steady_browsing", "checkout_heavy", "payment_degradation", "flash_sale", "gradual_ramp", "traffic_drop"):
            b += 1
            rids.append(_run(tmp, f"t{b}", "hpa_tuned", s, f"v7-b{b:02d}-hpa_tuned", 100 + b, rh=1.40 + 0.01 * b))
            rids.append(_run(tmp, f"r{b}", "flexascale", s, f"v7-b{b:02d}-rl", (100 + b) * cand_p95[b % 2],
                             rh=(1.40 + 0.01 * b) * cand_rh[b % 2]))
    return rids


def test_verdict_cost_win_needs_lower_replica_hours_without_latency_harm(tmp_path, monkeypatch):
    mod = _load("analyze_v7")
    rids = _eval_runs(tmp_path, cand_rh=(0.95, 0.97), cand_p95=(0.98, 1.02))  # p95 noise around 0
    _host(tmp_path, rids)
    monkeypatch.setattr(sys, "argv", ["x", "--results", str(tmp_path / "runs"), "--host-load", str(tmp_path / "host.csv"),
                                      "--out", str(tmp_path / "ev")])
    mod.main()
    out = json.loads((tmp_path / "ev.json").read_text())
    assert out["comparisons"]["rl vs hpa_tuned"]["verdict"] == "Beats on cost"


def test_verdict_rejects_a_cost_win_bought_with_latency(tmp_path, monkeypatch):
    mod = _load("analyze_v7")
    rids = _eval_runs(tmp_path, cand_rh=(0.90, 0.92), cand_p95=(1.25, 1.30))   # cheaper but p95 +25-30%
    _host(tmp_path, rids)
    monkeypatch.setattr(sys, "argv", ["x", "--results", str(tmp_path / "runs"), "--host-load", str(tmp_path / "host.csv"),
                                      "--out", str(tmp_path / "ev")])
    mod.main()
    v = json.loads((tmp_path / "ev.json").read_text())["comparisons"]["rl vs hpa_tuned"]
    assert v["verdict"] == "Worse" and not v["checks"]["C2 p95 not worse (interval not > 0, mean <= +10%)"]


def test_invalid_runs_leave_their_block_missing(tmp_path, monkeypatch):
    mod = _load("analyze_v7")
    rids = _eval_runs(tmp_path, cand_rh=(0.95, 0.97), cand_p95=(1.0, 1.0))
    _host(tmp_path, rids, affected={"r3"})
    monkeypatch.setattr(sys, "argv", ["x", "--results", str(tmp_path / "runs"), "--host-load", str(tmp_path / "host.csv"),
                                      "--out", str(tmp_path / "ev")])
    mod.main()
    out = json.loads((tmp_path / "ev.json").read_text())
    assert len(out["comparisons"]["rl vs hpa_tuned"]["pairs"]) == 11
    assert any(e["run"] == "r3" for e in out["excluded"])
