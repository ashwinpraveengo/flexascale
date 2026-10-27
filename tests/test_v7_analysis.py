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


def test_rerun_plan_moves_invalid_runs_and_lists_them_once(tmp_path, monkeypatch):
    mod = _load("rerun_plan")
    plan = [{"controller": "hpa_tuned", "block": f"cal-{t}", "hpa_cpu_target_pct": t} for t in (350, 150, 250, 70)]
    rids = [_run(tmp_path, f"r{i}", "hpa_tuned", "calibration_steady", b["block"], 100, target=b["hpa_cpu_target_pct"])
            for i, b in enumerate(plan)]
    j = json.loads((tmp_path / "runs" / "r3" / "run.json").read_text())
    j["summary"]["settled_start"] = False
    (tmp_path / "runs" / "r3" / "run.json").write_text(json.dumps(j))
    _host(tmp_path, rids, affected=("r1",))
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "plan.progress.json").write_text(json.dumps({str(i): {"id": r} for i, r in enumerate(rids)}))
    argv = ["x", str(tmp_path / "plan.json"), "--results", str(tmp_path / "runs"), "--invalid", str(tmp_path / "invalid"),
            "--host-load", str(tmp_path / "host.csv")]
    monkeypatch.setattr(sys, "argv", argv)
    assert mod.main() == 0
    reruns = json.loads((tmp_path / "plan.reruns.json").read_text())
    assert [(r["block"], r["rerun_of"]) for r in reruns] == [("cal-150", "r1"), ("cal-70", "r3")]
    assert sorted(p.name for p in (tmp_path / "invalid").iterdir()) == ["r1", "r3"]
    assert (tmp_path / "runs" / "r0").exists() and (tmp_path / "runs" / "r2").exists()
    assert mod.main() == 0  # idempotent: the moved runs are still found and listed once
    assert len(json.loads((tmp_path / "plan.reruns.json").read_text())) == 2
    monkeypatch.setattr(sys, "argv", ["x", str(tmp_path / "plan.reruns.json")] + argv[2:])
    assert mod.main() == 2  # reruns are never rerun


def test_spike_plan_is_flash_sale_only_with_three_arms_per_block():
    mod = _load("v7_plan")
    arms = json.loads((ROOT / "reports" / "v7" / "arms.json").read_text())
    plan = mod.spike(arms)
    assert len(plan) == 30 and {p["scenario"] for p in plan} == {"flash_sale"}
    for b in range(1, 11):
        names = [p["block"].split("-", 2)[2] for p in plan if p["block"].startswith(f"v7s-b{b:02d}-")]
        assert sorted(names) == ["heuristic", "hpa_tuned", "rl"]
    assert plan == mod.spike(arms)  # deterministic (seed 2710 + block)


def test_spike_verdict_has_no_six_scenario_check(tmp_path, monkeypatch):
    mod = _load("analyze_v7")
    rids = []
    for b in range(1, 11):
        rids.append(_run(tmp_path, f"t{b}", "hpa_tuned", "flash_sale", f"v7s-b{b:02d}-hpa_tuned", 700 + 10 * b, rh=1.60 + 0.01 * b))
        rids.append(_run(tmp_path, f"r{b}", "flexascale", "flash_sale", f"v7s-b{b:02d}-rl", (700 + 10 * b) * (0.70 + 0.02 * (b % 3)),
                         rh=(1.60 + 0.01 * b) * (1.0 + 0.004 * ((b % 3) - 1))))
    _host(tmp_path, rids)
    monkeypatch.setattr(sys, "argv", ["x", "--study", "spike", "--results", str(tmp_path / "runs"),
                                      "--host-load", str(tmp_path / "host.csv"), "--out", str(tmp_path / "sp")])
    mod.main()
    v = json.loads((tmp_path / "sp.json").read_text())["comparisons"]["rl vs hpa_tuned"]
    assert len(v["pairs"]) == 10 and not any(k.startswith("C7") for k in v["checks"])
    assert v["verdict"] == "Beats on performance"  # p95 -26 to -30%, replica-hours -0.4..+0.4%


def test_spike_verdict_rejects_lower_latency_at_a_consistently_higher_cost(tmp_path, monkeypatch):
    """§3.5/§3.6: a replica-hours interval entirely above 0 rules out 'beats on performance', however small."""
    mod = _load("analyze_v7")
    rids = []
    for b in range(1, 11):
        rids.append(_run(tmp_path, f"t{b}", "hpa_tuned", "flash_sale", f"v7s-b{b:02d}-hpa_tuned", 700 + 10 * b, rh=1.60 + 0.01 * b))
        rids.append(_run(tmp_path, f"r{b}", "flexascale", "flash_sale", f"v7s-b{b:02d}-rl", (700 + 10 * b) * 0.7,
                         rh=(1.60 + 0.01 * b) * (1.0 + 0.004 * (b % 2))))  # +0 / +0.4%: mean +0.2%, interval > 0
    _host(tmp_path, rids)
    monkeypatch.setattr(sys, "argv", ["x", "--study", "spike", "--results", str(tmp_path / "runs"),
                                      "--host-load", str(tmp_path / "host.csv"), "--out", str(tmp_path / "sp")])
    mod.main()
    assert json.loads((tmp_path / "sp.json").read_text())["comparisons"]["rl vs hpa_tuned"]["verdict"] == "Worse"


def test_replication_plan_has_four_arms_per_block_and_no_default_hpa():
    mod = _load("v7_plan")
    arms = json.loads((ROOT / "reports" / "v7" / "arms.json").read_text())
    plan = mod.replication(arms)
    assert len(plan) == 48 and not any(p["block"].endswith("-hpa_default") for p in plan)
    for b in range(1, 13):
        names = sorted(p["block"].split("-", 2)[2] for p in plan if p["block"].startswith(f"v7r-b{b:02d}-"))
        assert names == ["auto", "heuristic", "hpa_tuned", "rl"]
    assert plan == mod.replication(arms)


def _replication_runs(tmp, app_cpu_rl):
    """12 blocks: RL p95 -26..-30% at equal replica-hours; its shop CPU per request is app_cpu_rl x the reference's."""
    rids, cpu, b = [], {}, 0
    for rep in range(2):
        for s in ("steady_browsing", "checkout_heavy", "payment_degradation", "flash_sale", "gradual_ramp", "traffic_drop"):
            b += 1
            t = _run(tmp, f"t{b}", "hpa_tuned", s, f"v7r-b{b:02d}-hpa_tuned", 100 + b, rh=1.40 + 0.01 * b)
            r = _run(tmp, f"r{b}", "flexascale", s, f"v7r-b{b:02d}-rl", (100 + b) * (0.70 + 0.02 * (b % 3)),
                     rh=(1.40 + 0.01 * b) * (1.0 + 0.004 * ((b % 3) - 1)))
            rids += [t, r]
            cpu[t], cpu[r] = 15.0, 15.0 * app_cpu_rl
    with open(tmp / "host.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "host_affected", "reason", "cpu_mhz", "app_cpu_ms_per_request"])
        w.writeheader()
        for rid in rids:
            w.writerow({"run": rid, "host_affected": "False", "reason": "", "cpu_mhz": 2000, "app_cpu_ms_per_request": cpu[rid]})


def _replication_verdict(tmp, monkeypatch, app_cpu_rl):
    tmp.mkdir(exist_ok=True)
    _replication_runs(tmp, app_cpu_rl)
    monkeypatch.setattr(sys, "argv", ["x", "--study", "replication", "--results", str(tmp / "runs"),
                                      "--host-load", str(tmp / "host.csv"), "--out", str(tmp / "rep")])
    _load("analyze_v7").main()
    return json.loads((tmp / "rep.json").read_text())["comparisons"]["rl vs hpa_tuned"]["verdict"]


def test_replication_verdict_needs_environment_parity(tmp_path, monkeypatch):
    """§3.7: if the candidate's shop ran > 10% faster per request where replicas are identical, there is no verdict."""
    assert _replication_verdict(tmp_path / "fast", monkeypatch, 0.85).startswith("No verdict: environment parity failed (shop CPU per request -15.0%")
    assert _replication_verdict(tmp_path / "slower", monkeypatch, 1.05) == "Beats on performance"   # a slower environment only makes the test harder
    assert _replication_verdict(tmp_path / "equal", monkeypatch, 0.97) == "Beats on performance"
