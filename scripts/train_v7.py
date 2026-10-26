#!/usr/bin/env python3
"""
Train, select and test the v7 graph policy on the application twin (docs/POLICY_V7.md §4).

Protocol (written into POLICY_V7 §4.3 before the first training run):

* Runs: graph policy with the v7 reward, seeds 1 and 2; ablations (seed 1): no graph
  (``use_graph=False``) and the v4–v6 reward structure (``reward kind v5``). PPO settings
  are chosen once: 8 environments, 128 steps each per update, batch 256, 10 epochs,
  lr 3e-4, gamma 0.97, GAE 0.95, clip 0.2, entropy 0.01; ``--steps`` per run.
* Selection: every ``--eval-every`` steps the deterministic policy runs the validation
  set (shop twin, 40 random workloads, seeds 10000–10039); the checkpoint with the
  highest mean v7 episode reward is kept per run, and the best run is "v7".
  The heuristic for the live attribution arm is the best of a fixed rule family on the
  same validation set.
* Test (once, after selection): T1 = the six live evaluation scenarios at 25 users
  (sim seeds 40000–40004 each), T2 = 60 random shop workloads (seeds 50000–50059),
  T3 = 40 random synthetic applications (seeds 60000–60039). Every controller sees the
  same episodes; results are reported for every controller, whichever wins.

While it trains, ``.runtime/pause_live_runs`` exists so that no live run starts
(training load would count as host noise), and training waits for an active run to end.

    python scripts/train_v7.py --steps 1500000
    python scripts/train_v7.py --only-test          # re-test saved models
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flexascale.rl import features_v3 as fv  # noqa: E402
from flexascale.simulator.twin import TICK_S, TwinSim  # noqa: E402
from flexascale.simulator.twin_control import (  # noqa: E402
    V7_GUARDS, Guards, NativeHPA, OperatorLoop, limit_target_policy, threshold_policy)
from flexascale.simulator.twin_env import (  # noqa: E402
    ACTION_DELTAS, HOLD_INDEX, N_MAX, RewardConfig, TwinEnv, episode_reward, load_shop)
from flexascale.simulator.twin_workloads import evaluation_set, random_app, random_workload  # noqa: E402

PAUSE = ROOT / ".runtime" / "pause_live_runs"
OUT = ROOT / "models" / "flexascale_v7"
REPORT = ROOT / "reports" / "v7"
PPO_KW = dict(n_steps=128, batch_size=256, n_epochs=10, learning_rate=3e-4, gamma=0.97, gae_lambda=0.95,
              clip_range=0.2, ent_coef=0.01, vf_coef=0.5, max_grad_norm=0.5)
RUNS = {
    "graph_s1": {"use_graph": True, "reward": "v7", "seed": 1},
    "graph_s2": {"use_graph": True, "reward": "v7", "seed": 2},
    "nograph_s1": {"use_graph": False, "reward": "v7", "seed": 1},
    "v5reward_s1": {"use_graph": True, "reward": "v5", "seed": 1},
}
RULES = {f"limit_target({t}/{d})": (t, d) for t in (0.4, 0.5, 0.6, 0.7) for d in (0.2, 0.3)}


# ---------------------------------------------------------------------------
# Live-run guard
# ---------------------------------------------------------------------------


def battery() -> tuple:
    """(on_battery, capacity %) of the laptop; (False, 100) when there is no battery."""
    import glob
    for d in glob.glob("/sys/class/power_supply/BAT*"):
        try:
            status = Path(d, "status").read_text().strip()
            cap = int(Path(d, "capacity").read_text().strip())
            return status == "Discharging", cap
        except (OSError, ValueError):
            pass
    return False, 100


LOW_BATTERY = 35


def wait_for_power() -> None:
    """A dead battery takes Minikube down with the laptop: below LOW_BATTERY % on battery, wait for the charger."""
    while True:
        on_bat, cap = battery()
        if not (on_bat and cap < LOW_BATTERY):
            return
        print(time.strftime("%H:%M:%S"), f"battery {cap}% and discharging: training waits for the charger", flush=True)
        time.sleep(60)


def lab_busy() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/api/lab/experiments/active", timeout=5) as r:
            a = (json.loads(r.read()) or {}).get("active") or {}
        return a.get("state") not in (None, "completed", "stopped", "failed", "interrupted")
    except OSError:
        return False


def hold_live_runs() -> None:
    PAUSE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE.write_text(f"train_v7.py pid {os.getpid()} since {time.strftime('%F %T')}\n")
    atexit.register(lambda: PAUSE.unlink(missing_ok=True))
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(1))
    while lab_busy():
        print(time.strftime("%H:%M:%S"), "a live run is active; waiting for it to finish before training", flush=True)
        time.sleep(30)


# ---------------------------------------------------------------------------
# Controllers in the twin
# ---------------------------------------------------------------------------


class ModelPolicy:
    """The trained network as an OperatorLoop policy: same features and timing as TwinEnv."""

    def __init__(self, model, n_max: int = N_MAX) -> None:
        self.model, self.n_max = model, n_max
        self.name = "v7"

    def reset(self, sim: TwinSim) -> None:
        self.tracker = fv.FeatureTracker(sim.app.names, max_replicas=int(sim.hi.max()))

    def __call__(self, sim, obs, loop) -> np.ndarray:
        if sim.t == 0:  # TwinEnv's first decision is after the first 10 s
            return np.zeros(sim.n, dtype=int)
        now = sim.t * TICK_S
        feats = {}
        for i, s in enumerate(sim.app.services):
            self.tracker.last_up[s.name] = float(loop.last_up[i])
            self.tracker.last_down[s.name] = float(loop.last_down[i])
            feats[s.name] = self.tracker.update(now, s.name, cpu_cores=float(obs["cpu_cores"][i]), ready=int(obs["ready"][i]),
                                                desired=int(obs["desired"][i]), cpu_limit=s.cpu_limit, rps=float(obs["rps"][i]),
                                                latency_ms=float(obs["latency_ms"][i]) or None)
        x = fv.pack(feats, sim.app.names, sim.app.edges, self.n_max)
        a, _ = self.model.predict(x, deterministic=True)
        return np.array([ACTION_DELTAS[int(k)] for k in np.asarray(a).ravel()[: sim.n]])


def controllers(models: Dict[str, Any], hpa_targets=(70, 150, 250, 350)) -> Dict[str, Callable[[], Any]]:
    c: Dict[str, Callable[[], Any]] = {"HPA-default (70%, 300 s)": lambda: NativeHPA(70, 300)}
    for t in hpa_targets:
        c[f"HPA {t}%, 60 s"] = (lambda t=t: NativeHPA(t, 60))
    c["operator + threshold 70% (v5 guards)"] = lambda: OperatorLoop(threshold_policy(70), Guards())
    for name, (t, d) in RULES.items():
        c[f"operator + {name}"] = (lambda t=t, d=d: OperatorLoop(limit_target_policy(t, d), V7_GUARDS))
    for name, m in models.items():
        c[name] = (lambda m=m: OperatorLoop(ModelPolicy(m), V7_GUARDS, name="v7"))
    return c


def run_set(episodes, factory, cfg: RewardConfig) -> List[Dict[str, Any]]:
    out = []
    for app, wl, seed in episodes:
        sim = TwinSim(app, wl, seed=seed)
        ctrl = factory()
        ctrl.reset(sim)
        for _ in range(wl.ticks):
            ctrl.tick(sim)
            sim.step()
        s = sim.summary()
        s["reward"] = episode_reward(sim, cfg)
        s["workload"] = wl.name
        s["floor_replica_hours"] = float(sim.lo.sum() * wl.ticks * TICK_S / 3600.0)
        out.append(s)
    return out


def episodes_validation(app, cal):
    rng = np.random.default_rng(10000)
    return [(app, random_workload(app, cal, np.random.default_rng(10000 + k)), 10000 + k) for k in range(40)]


def episodes_test(app, cal):
    t1 = [(app, wl, 40000 + k) for wl in evaluation_set(app, cal) for k in range(5)]
    t2 = [(app, random_workload(app, cal, np.random.default_rng(50000 + k)), 50000 + k) for k in range(60)]
    t3 = []
    for k in range(40):
        rng = np.random.default_rng(60000 + k)
        a, c = random_app(rng)
        t3.append((a, random_workload(a, c, rng), 60000 + k))
    return {"T1_live_scenarios": t1, "T2_random_shop": t2, "T3_random_apps": t3}


def agg(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    f = lambda k: float(np.mean([r[k] for r in rows]))
    return {"reward": f("reward"), "replica_hours": f("replica_hours"), "p95_ms": f("p95_ms"),
            "mean_latency_ms": f("mean_latency_ms"), "failure_pct": f("failure_pct"), "slo_violation_s": f("slo_violation_s"),
            "scaling_events": f("scaling_events"), "oscillations": f("oscillations"), "n": len(rows)}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def make_env(app, cal, reward_kind, rank, seed):
    def f():
        return TwinEnv(app, cal, reward=RewardConfig(kind=reward_kind), seed=seed * 1000 + rank)
    return f


def train_run(name: str, spec: Dict[str, Any], app, cal, steps: int, eval_every: int, n_envs: int, val) -> Dict[str, Any]:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.vec_env import DummyVecEnv

    from flexascale.rl.graph_policy import GraphPolicy

    torch.set_num_threads(2)
    run_dir = OUT / name
    run_dir.mkdir(parents=True, exist_ok=True)
    # The 8 environments step in this process (DummyVecEnv): a twin step costs ~1 ms, and subprocesses each load
    # PyTorch (~0.5 GB apiece), which the laptop running Minikube cannot spare. Same environments, seeds and settings.
    venv = DummyVecEnv([make_env(app, cal, spec["reward"], r, spec["seed"]) for r in range(n_envs)])
    model = PPO(GraphPolicy, venv, seed=spec["seed"], verbose=0, device="cpu",
                policy_kwargs={"n_max": N_MAX, "hidden": 64, "rounds": 2, "use_graph": spec["use_graph"],
                               "hold_index": HOLD_INDEX}, **PPO_KW)
    history = []
    stopped_early: List[int] = []
    cfg = RewardConfig()

    class Eval(BaseCallback):
        def __init__(self):
            super().__init__()
            self.next = eval_every
            self.best = -1e18

        def _on_step(self) -> bool:
            if self.num_timesteps % 8192 < self.training_env.num_envs:
                on_bat, cap = battery()
                if on_bat and cap < LOW_BATTERY:
                    print(time.strftime("%H:%M:%S"), f"{name}: battery {cap}% - stopping this run early (best checkpoint kept)", flush=True)
                    stopped_early.append(int(self.num_timesteps))
                    return False
            if self.num_timesteps >= self.next:
                self.next += eval_every
                rows = run_set(val, lambda: OperatorLoop(ModelPolicy(self.model), V7_GUARDS), cfg)
                a = agg(rows)
                history.append({"timesteps": int(self.num_timesteps), **a})
                tag = ""
                if a["reward"] > self.best:
                    self.best = a["reward"]
                    self.model.save(run_dir / "best_model")
                    tag = " *best*"
                print(f"{time.strftime('%H:%M:%S')} {name} {self.num_timesteps:>8d} val reward {a['reward']:9.2f} "
                      f"repl-h {a['replica_hours']:.3f} p95 {a['p95_ms']:6.0f} slo {a['slo_violation_s']:5.1f}{tag}", flush=True)
            return True

    t0 = time.time()
    model.learn(total_timesteps=steps, callback=Eval())
    model.save(run_dir / "final_model")
    venv.close()
    (run_dir / "history.json").write_text(json.dumps(history, indent=1))
    best = max(history, key=lambda h: h["reward"]) if history else None
    return {"name": name, **spec, "steps": steps, "minutes": round((time.time() - t0) / 60, 1), "best": best,
            "history": history, "stopped_early_at": stopped_early[0] if stopped_early else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", type=int, default=1_500_000)
    ap.add_argument("--eval-every", type=int, default=100_000)
    ap.add_argument("--n-envs", type=int, default=8)
    ap.add_argument("--runs", default=",".join(RUNS))
    ap.add_argument("--only-test", action="store_true")
    args = ap.parse_args()

    app, cal = load_shop(ROOT / "config" / "twin" / "shopping.json")
    val = episodes_validation(app, cal)
    REPORT.mkdir(parents=True, exist_ok=True)
    hold_live_runs()
    summary_path = REPORT / "training_v7.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"runs": {}}
    if not args.only_test:
        for name in args.runs.split(","):
            wait_for_power()
            print(f"=== training {name} {RUNS[name]} ({args.steps} steps)", flush=True)
            summary["runs"][name] = train_run(name, RUNS[name], app, cal, args.steps, args.eval_every, args.n_envs, val)
            summary_path.write_text(json.dumps(summary, indent=1))

    from stable_baselines3 import PPO

    models = {}
    for name in RUNS:
        p = OUT / name / "best_model.zip"
        if p.exists():
            models[name] = PPO.load(str(p), device="cpu")
    # selection among the main runs (v7 reward, with graph): highest validation reward
    main_runs = [n for n in ("graph_s1", "graph_s2") if n in summary["runs"] and summary["runs"][n].get("best")]
    chosen = max(main_runs, key=lambda n: summary["runs"][n]["best"]["reward"]) if main_runs else None
    summary["selected"] = chosen
    # heuristic arm: best rule of the fixed family on the same validation set
    cfg = RewardConfig()
    rule_val = {name: agg(run_set(val, (lambda t=t, d=d: OperatorLoop(limit_target_policy(t, d), V7_GUARDS)), cfg))
                for name, (t, d) in RULES.items()}
    summary["rules_validation"] = rule_val
    summary["selected_rule"] = max(rule_val, key=lambda n: rule_val[n]["reward"])
    print("selected model:", chosen, "| selected rule:", summary["selected_rule"], flush=True)

    tests = episodes_test(app, cal)
    named = {f"v7 ({n})": m for n, m in models.items()}
    ctrls = controllers(named)
    results: Dict[str, Dict[str, Any]] = {}
    for tname, eps in tests.items():
        results[tname] = {}
        for cname, fac in ctrls.items():
            if tname == "T3_random_apps" and cname.startswith("HPA") is False and "limit_target" in cname and cname != f"operator + {summary['selected_rule']}":
                continue
            rows = run_set(eps, fac, cfg)
            results[tname][cname] = {"aggregate": agg(rows), "per_episode": [
                {k: r[k] for k in ("workload", "reward", "replica_hours", "p95_ms", "mean_latency_ms", "failure_pct",
                                   "slo_violation_s", "scaling_events", "oscillations", "floor_replica_hours")} for r in rows]}
            a = results[tname][cname]["aggregate"]
            print(f"{tname:18s} {cname:44s} reward {a['reward']:9.2f} repl-h {a['replica_hours']:.3f} p95 {a['p95_ms']:6.0f} "
                  f"mean {a['mean_latency_ms']:5.0f} slo {a['slo_violation_s']:5.1f} ev {a['scaling_events']:5.1f} osc {a['oscillations']:4.1f}", flush=True)
    summary["test"] = results
    summary_path.write_text(json.dumps(summary, indent=1))
    print("wrote", summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
