"""v9 tooling (docs/POLICY_V9.md): run plans, the Windows host-load rule, the v9 study label."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_calibration_plan_is_deterministic_and_labelled_for_this_laptop():
    plan = _script("v9_plan").calibration()
    assert len(plan) == 8 and all(p["block"] == f"v9cal-{p['hpa_cpu_target_pct']}" for p in plan)
    assert sorted(p["hpa_cpu_target_pct"] for p in plan) == [70, 70, 150, 150, 250, 250, 350, 350]
    assert plan == _script("v9_plan").calibration()
    assert all(p["hpa_scale_down_window_s"] == 60 and p["users"] == 25 and p["duration"] == 300 for p in plan)


def test_evaluation_plan_has_every_arm_once_per_block():
    arms = {"hpa_default": {"controller": "hpa"}, "hpa_tuned": {"controller": "hpa_tuned", "hpa_cpu_target_pct": 150},
            "rl": {"controller": "flexascale"}, "auto": {"controller": "auto"}}
    plan = _script("v9_plan").evaluation(arms)
    assert len(plan) == 48
    blocks = {}
    for p in plan:
        b, arm = p["block"].split("-", 2)[1], p["block"].split("-", 2)[2]
        blocks.setdefault(b, []).append(arm)
    assert len(blocks) == 12 and all(sorted(v) == sorted(arms) for v in blocks.values())


def test_host_samples_give_mean_cores_and_battery_seconds():
    hl = _script("check_host_load")
    run = {"sample_interval_s": 5, "samples": [
        {"elapsed": -1, "host": {"cpu_cores": 99, "on_ac": False}},  # preparation: not in the load window
        {"elapsed": 0, "host": {"cpu_cores": 2.0, "on_ac": True}},
        {"elapsed": 5, "host": {"cpu_cores": 4.0, "on_ac": False}},
        {"elapsed": 10}]}
    cores, battery = hl.host_samples(run)
    assert cores == 3.0 and battery == 5
    assert hl.host_samples({"samples": [{"elapsed": 0}]}) == (None, None)
    assert hl.classify(3.0, 0, limit=4.5) == (False, "") and hl.classify(5.0, 0, limit=4.5)[0] is True
    assert hl.classify(1.0, 5, limit=4.5)[0] is True  # any battery time makes a run host-affected


def test_v9_study_label_is_separate_from_v7():
    an = _script("analyze_v7")
    assert an.V9_LABEL.match("v9-b03-auto").groups() == ("03", "auto")
    assert an.V9_LABEL.match("v7-b03-auto") is None and an.LABEL.match("v9-b03-auto") is None
