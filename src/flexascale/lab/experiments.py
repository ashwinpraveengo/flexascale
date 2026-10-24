"""
Live Autoscaling Lab: experiment orchestration.

One experiment = one application x one controller x one Locust scenario.

    hpa         native Kubernetes HPA owns scaling. Optionally FlexaScale runs in
                shadow (observe-only) mode and records what it *would* do.
    flexascale  the FlexaScale operator runs in live mode: it must take the
                application's controller Lease and freezes each HPA before it
                scales. It is stopped (restoring every HPA) when the run ends.

Only one experiment can be active. Every exit path (completion, stop button,
error, server shutdown) stops Locust, stops the operator, restores frozen
HPAs and verifies the resulting ownership state. Results are written to
``reports/experiments/<run_id>/run.json`` and ``telemetry.csv``.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from flexascale.config.app_policy import AppPolicy
from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.workloads import WorkloadDiscovery, WorkloadInfo
from flexascale.evaluation.cost import percent_change, scaling_stability, summarize_resources
from flexascale.k8s.kube import Kube
from flexascale.lab.processes import ProcessManager
from flexascale.metrics.workload_metrics import WorkloadMetricsClient
from flexascale.safety.hpa_manager import HPAManager
from flexascale.safety.lease import ControllerLease

logger = logging.getLogger(__name__)

ROOT = Path(os.environ.get("FLEXASCALE_ROOT", Path.cwd()))

SCENARIOS: Dict[str, Dict[str, str]] = {
    "steady_browsing": {"title": "Steady browsing", "description": "Constant catalogue browsing with some shoppers."},
    "gradual_ramp": {"title": "Gradual ramp-up", "description": "Users grow in six steps to the peak, then plateau."},
    "flash_sale": {"title": "Flash-sale spike", "description": "20% baseline, sudden jump to peak with checkout contention, back to baseline."},
    "checkout_heavy": {"title": "Checkout-heavy", "description": "Mostly authenticated cart and checkout journeys."},
    "traffic_drop": {"title": "Traffic drop", "description": "Peak load, then a drop to 10% (tests scale-down)."},
    "payment_degradation": {"title": "Payment latency & failures", "description": "300 ms payment delays plus declined cards."},
}
CONTROLLERS = ("hpa", "flexascale")
LIMITS = {"users": (1, 500), "spawn_rate": (0.1, 100.0), "duration": (30, 3600)}
TERMINAL_STATES = ("completed", "stopped", "failed", "interrupted")
HPA_DOWNSCALE_WINDOW_S = 330  # Kubernetes default scale-down stabilisation (300 s) + margin


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LabApp:
    name: str
    title: str
    policy_path: str
    url: str
    locustfile: str


@dataclass
class LabConfig:
    minikube_profile: str = "flexascale"
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3000"
    results_dir: str = "reports/experiments"
    sample_interval_seconds: float = 5.0
    e2e_p95_slo_ms: float = 1000.0
    apps: Dict[str, LabApp] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "LabConfig":
        data = yaml.safe_load(Path(path).read_text()) or {}
        apps = {
            name: LabApp(
                name=name,
                title=spec.get("title", name),
                policy_path=spec["policy"],
                url=spec.get("url", ""),
                locustfile=spec.get("locustfile", "load-testing/scenarios.py"),
            )
            for name, spec in (data.pop("apps", {}) or {}).items()
        }
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        env_prom = os.environ.get("FLEXASCALE_PROMETHEUS_URL")
        if env_prom:
            kwargs["prometheus_url"] = env_prom
        return cls(apps=apps, **kwargs)


@dataclass
class ExperimentRequest:
    app: str
    controller: str
    scenario: str
    users: int = 40
    spawn_rate: float = 5.0
    duration: int = 300
    reset_replicas: bool = True
    shadow: bool = True
    """HPA runs only: also run FlexaScale in observe-only mode to log its proposals."""

    def validate(self, cfg: LabConfig) -> List[str]:
        errors = []
        if self.app not in cfg.apps:
            errors.append(f"unknown app '{self.app}'")
        if self.controller not in CONTROLLERS:
            errors.append(f"controller must be one of {CONTROLLERS}")
        if self.scenario not in SCENARIOS:
            errors.append(f"scenario must be one of {sorted(SCENARIOS)}")
        for key, (lo, hi) in LIMITS.items():
            val = getattr(self, key)
            if not (lo <= val <= hi):
                errors.append(f"{key} must be between {lo} and {hi}")
        return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def read_locust_history(path: Path) -> Optional[Dict[str, Any]]:
    """Last 'Aggregated' row of Locust's *_stats_history.csv (percentiles over a ~10 s window)."""
    if not path.is_file():
        return None
    last = None
    try:
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Name") == "Aggregated":
                    last = row
    except (OSError, csv.Error):
        return None
    if last is None:
        return None
    return {
        "users": int(_float(last.get("User Count")) or 0),
        "rps": _float(last.get("Requests/s")),
        "fail_rps": _float(last.get("Failures/s")),
        "p50_ms": _float(last.get("50%")),
        "p95_ms": _float(last.get("95%")),
        "p99_ms": _float(last.get("99%")),
        "total_requests": int(_float(last.get("Total Request Count")) or 0),
        "total_failures": int(_float(last.get("Total Failure Count")) or 0),
    }


def read_locust_final(path: Path) -> Optional[Dict[str, Any]]:
    """'Aggregated' row of Locust's *_stats.csv (whole-run statistics)."""
    if not path.is_file():
        return None
    try:
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("Name") == "Aggregated":
                    req = int(_float(row.get("Request Count")) or 0)
                    fail = int(_float(row.get("Failure Count")) or 0)
                    return {
                        "total_requests": req,
                        "total_failures": fail,
                        "failure_rate_pct": (100.0 * fail / req) if req else None,
                        "throughput_rps": _float(row.get("Requests/s")),
                        "mean_latency_ms": _float(row.get("Average Response Time")),
                        "p50_ms": _float(row.get("50%")),
                        "p95_ms": _float(row.get("95%")),
                        "p99_ms": _float(row.get("99%")),
                        "max_ms": _float(row.get("Max Response Time")),
                    }
    except (OSError, csv.Error):
        return None
    return None


def start_settled(run: Dict[str, Any]) -> Optional[bool]:
    """
    Did the run start from minimum replicas at controller handoff?

    Handoff is the moment just before the controller under test acts: for
    FlexaScale runs the replica snapshot taken before the operator starts
    (``start_replicas`` / ``initial_replicas``), for HPA runs the first workload
    sample (HPA is in control throughout). Minimums are the HPA's real minimum,
    or the policy minimum for services without an HPA.
    """
    policy_min = int((run.get("policy") or {}).get("min_replicas") or 1)
    samples = run.get("samples") or []
    first = samples[0]["services"] if samples and samples[0].get("services") else {}

    def floor(name: str) -> int:
        svc = first.get(name) or {}
        if svc.get("hpa_min") is not None and not svc.get("frozen"):
            return int(svc["hpa_min"])
        return policy_min

    controller = (run.get("request") or {}).get("controller")
    snapshot = run.get("start_replicas") or (run.get("initial_replicas") if controller == "flexascale" else None)
    if snapshot:
        return all(int(v) <= floor(k) for k, v in snapshot.items())
    if first:
        return all(int(svc.get("desired") or 0) <= floor(name) for name, svc in first.items())
    return (run.get("summary") or {}).get("settled_start")


def resolve_app_url(app: LabApp, profile: str) -> str:
    if app.url != "minikube-ingress":
        return app.url
    try:
        ip = subprocess.run(["minikube", "ip", "-p", profile], capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        ip = ""
    return f"http://{ip}" if ip else ""


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class Experiment:
    def __init__(self, lab: "Lab", req: ExperimentRequest) -> None:
        self.lab = lab
        self.req = req
        self.app = lab.cfg.apps[req.app]
        self.policy = lab.policy(req.app)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.id = f"{stamp}-{req.app}-{req.controller}-{req.scenario}"
        self.dir = ROOT / lab.cfg.results_dir / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state = "preparing"
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.error: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self.samples: List[Dict[str, Any]] = []
        self.summary: Optional[Dict[str, Any]] = None
        self.cleanup: Optional[Dict[str, Any]] = None
        self.model_info: Optional[Dict[str, Any]] = None
        self.initial_replicas: Optional[Dict[str, int]] = None
        self.settled_start: Optional[bool] = None
        self.start_replicas: Optional[Dict[str, int]] = None
        self._final_state = "running"
        self.app_url = ""
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._decision_offset = 0
        self._locust_log_offset = 0
        self._prev: Dict[str, Dict[str, Any]] = {}
        self._e2e_violating = False
        self.thread = threading.Thread(target=self._run, name=f"experiment-{self.id}", daemon=True)

    # -- bookkeeping ---------------------------------------------------------

    def event(self, kind: str, message: str, **data: Any) -> None:
        now = time.time()
        ev = {"t": now, "elapsed": round(now - self.started_at, 1) if self.started_at else None,
              "kind": kind, "message": message}
        ev.update(data)
        with self._lock:
            self.events.append(ev)
        logger.info("[LAB] %s: %s", kind, message)

    def snapshot(self, max_samples: int = 720) -> Dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "request": dataclasses.asdict(self.req),
                "app_title": self.app.title,
                "namespace": self.policy.namespace,
                "app_url": self.app_url,
                "state": self.state,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "error": self.error,
                "events": list(self.events),
                "samples": list(self.samples[-max_samples:]),
                "summary": self.summary,
                "cleanup": self.cleanup,
                "model": self.model_info,
                "initial_replicas": self.initial_replicas,
                "start_replicas": self.start_replicas,
                "slo": {"e2e_p95_ms": self.lab.cfg.e2e_p95_slo_ms, "service_mean_ms": self.policy.slo_latency_ms},
            }

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        final = "completed"
        try:
            self._prepare()
            if self._stop.is_set():
                raise InterruptedError("stopped during preparation")
            self._start_workload()
            self._sample_loop()
        except InterruptedError as exc:
            final = "stopped"
            self.event("experiment", f"Stopped: {exc}")
        except Exception as exc:
            logger.exception("[LAB] experiment failed")
            final = "failed"
            self.error = f"{type(exc).__name__}: {exc}"
            self.event("error", self.error)
        finally:
            # Results and cleanup are finished before a terminal state becomes visible.
            self.state = "stopping"
            self._teardown()
            self.ended_at = time.time()
            self._final_state = final
            try:
                self._finalize()
            except Exception as exc:
                logger.exception("[LAB] finalize failed")
                self.error = (self.error or "") + f" | finalize: {exc}"
            self.event("experiment", f"Experiment {final}", state=final)
            self._write_files(final)
            self.state = final

    # -- phases --------------------------------------------------------------

    def _prepare(self) -> None:
        lab, policy = self.lab, self.policy
        self.app_url = resolve_app_url(self.app, lab.cfg.minikube_profile)
        if not self.app_url:
            raise RuntimeError("could not resolve the application URL")
        self.event("preflight", f"Target {self.app.title} at {self.app_url} (namespace {policy.namespace})")

        if not lab.metrics.healthy():
            raise RuntimeError(f"Prometheus not reachable at {lab.cfg.prometheus_url}")
        workloads = lab.discovery(self.req.app).discover(force_refresh=True)
        if not workloads:
            raise RuntimeError(f"no eligible Deployments found in namespace '{policy.namespace}'")
        names = [w.name for w in workloads]
        self.event("preflight", f"{len(names)} eligible services: {', '.join(names)}", services=names)

        hpa_mgr = lab.hpa_manager(self.req.app)
        restored = hpa_mgr.restore_all_frozen()
        if restored:
            self.event("ownership", f"Restored HPAs left frozen by an earlier run: {', '.join(restored)}")
        lease = ControllerLease(policy.namespace, policy.name, kube=lab.kube)
        st = lease.status()
        if st.holder and not st.expired:
            raise RuntimeError(f"controller lease '{lease.name}' is held by '{st.holder}'; stop that controller first")
        if lab.pm.is_running("operator"):
            raise RuntimeError("a FlexaScale operator started by the lab is still running")

        if self.req.reset_replicas:
            self._reset_replicas(workloads, hpa_mgr)

        workloads = lab.discovery(self.req.app).discover(force_refresh=True)
        self.start_replicas = {w.name: w.desired_replicas for w in workloads}  # state at controller handoff
        without_hpa = [w.name for w in workloads if w.hpa is None]
        if self.req.controller == "hpa":
            if without_hpa:
                self.event("ownership", f"No HPA for {', '.join(without_hpa)}: replicas stay fixed under 'HPA' mode")
            self.event("ownership", "Native HPA owns scaling; FlexaScale scaling disabled (lease free, no HPA frozen)")
            if self.req.shadow:
                self._start_operator("observe")
        else:
            self._start_operator("live")

    def _reset_replicas(self, workloads: List[WorkloadInfo], hpa_mgr: HPAManager) -> None:
        """
        Bring every managed Deployment to its minimum so runs start comparably.

        A plain ``kubectl scale`` is undone by the HPA's scale-down stabilisation
        window, so HPAs are briefly frozen at their minimum (original bounds are
        recorded on the HPA), the Deployments are scaled and become ready, the
        HPAs are restored, and the result is verified. If an HPA still pushes
        replicas back up, wait (max 6 min) for it to settle on its own.
        """
        lab, policy = self.lab, self.policy
        targets = {}
        for w in workloads:
            lo, _ = policy.bounds_for(w.name)
            targets[w.name] = w.hpa.min_replicas if w.hpa else lo
            if w.hpa:
                hpa_mgr.freeze_hpa(w.name, targets[w.name])
            if w.desired_replicas != targets[w.name]:
                lab.kube.scale(w.name, policy.namespace, targets[w.name])
        self.event("preflight", "Resetting replicas to minimum (HPAs held at their minimum during the reset)")
        try:
            deadline = time.time() + 180
            while time.time() < deadline and not self._stop.is_set():
                current = lab.discovery(self.req.app).discover(force_refresh=True)
                if all(w.ready_replicas == w.desired_replicas == targets.get(w.name, w.desired_replicas) for w in current):
                    break
                time.sleep(3)
            else:
                if not self._stop.is_set():
                    raise RuntimeError("Deployments did not reach their minimum within 180 s")
            wait_until = lab.last_load_end + HPA_DOWNSCALE_WINDOW_S
            if time.time() < wait_until:
                self.event("preflight", f"Holding HPAs at their minimum for {wait_until - time.time():.0f} s more: the HPA "
                                        "downscale window since the previous load must expire for a comparable start")
                while time.time() < wait_until and not self._stop.is_set():
                    time.sleep(2)
        finally:
            restored = hpa_mgr.restore_all_frozen()
            if restored:
                self.event("ownership", f"HPAs restored to their original bounds after the reset: {', '.join(restored)}")

        def settled() -> bool:
            cur = lab.discovery(self.req.app).discover(force_refresh=True)
            return all(w.desired_replicas == targets.get(w.name, w.desired_replicas) and w.ready_replicas == w.desired_replicas for w in cur)

        verify_until = time.time() + 30
        stable = True
        while time.time() < verify_until and not self._stop.is_set():
            if not settled():
                stable = False
                break
            time.sleep(3)
        if not stable:
            self.event("preflight", "HPA scaled back up from its stabilisation window; waiting for it to settle (max 6 min)")
            deadline = time.time() + 360
            while time.time() < deadline and not self._stop.is_set():
                if settled():
                    stable = True
                    break
                time.sleep(5)
        initial = {w.name: w.desired_replicas for w in lab.discovery(self.req.app).discover(force_refresh=True)}
        self.initial_replicas = initial
        self.settled_start = stable
        self.event("preflight", ("Comparable start: " if stable else "WARNING: start not fully settled: ")
                   + ", ".join(f"{k}={v}" for k, v in initial.items()), initial_replicas=initial, settled=stable)
        self._stop.wait(10)  # let CPU rate windows reflect the idle state

    def _start_operator(self, mode: str) -> None:
        lab = self.lab
        status_file = lab.pm.runtime_dir / "operator_status.json"
        status_file.unlink(missing_ok=True)
        cmd = [
            sys.executable, str(ROOT / "scripts" / "run_operator.py"),
            "--policy", str(ROOT / self.app.policy_path),
            "--mode", mode,
            "--prometheus-url", lab.cfg.prometheus_url,
            "--decision-log", str(self.dir / "decisions.jsonl"),
            "--status-file", str(status_file),
        ]
        lab.pm.start("operator", cmd, cwd=str(ROOT), marker="run_operator.py", log_path=self.dir / "operator.log")
        deadline = time.time() + 90
        while time.time() < deadline:
            if not lab.pm.is_running("operator"):
                raise RuntimeError(f"operator exited during start-up (see {self.dir / 'operator.log'})")
            if status_file.is_file():
                try:
                    status = json.loads(status_file.read_text())
                except ValueError:
                    status = {}
                if status.get("step", 0) >= 1 or status.get("effective_mode") == mode:
                    self.model_info = status.get("model")
                    if status.get("effective_mode") != mode:
                        raise RuntimeError(f"operator could not enter {mode} mode: {status.get('model_error') or 'lease unavailable'}")
                    if mode == "live":
                        self.event("ownership", "FlexaScale operator holds the controller lease; HPAs are frozen per service before any scale",
                                   lease=(status.get("lease") or {}).get("holder"))
                    else:
                        self.event("ownership", "FlexaScale shadow mode: proposals are logged, cluster is not modified")
                    if not self.model_info:
                        self.event("warning", f"Trained model unavailable: {status.get('model_error')}")
                    return
            time.sleep(1)
        raise RuntimeError("operator did not report ready within 90 s")

    def _start_workload(self) -> None:
        req = self.req
        env = {
            "FLEXASCALE_SCENARIO": req.scenario,
            "FLEXASCALE_USERS": str(req.users),
            "FLEXASCALE_SPAWN_RATE": str(req.spawn_rate),
            "FLEXASCALE_DURATION": str(req.duration),
        }
        cmd = [
            sys.executable, "-m", "locust",
            "-f", str(ROOT / self.app.locustfile),
            "--headless", "--host", self.app_url,
            "--csv", str(self.dir / "locust"), "--csv-full-history",
            "--loglevel", "WARNING", "--stop-timeout", "5",
        ]
        self.lab.pm.start("locust", cmd, env=env, cwd=str(ROOT), marker="locust", log_path=self.dir / "locust.log")
        self.started_at = time.time()
        self.state = "running"
        self.event("workload", f"Workload started: {SCENARIOS[req.scenario]['title']}, {req.users} users peak, "
                               f"spawn {req.spawn_rate}/s, {req.duration}s", scenario=req.scenario)

    def _sample_loop(self) -> None:
        interval = self.lab.cfg.sample_interval_seconds
        hard_deadline = (self.started_at or time.time()) + self.req.duration + 60
        while True:
            t0 = time.time()
            self._sample()
            if self._stop.is_set():
                raise InterruptedError("stop requested")
            if not self.lab.pm.is_running("locust"):
                self._sample()
                break
            if time.time() > hard_deadline:
                self.event("warning", "Workload exceeded its duration by 60 s; stopping it")
                break
            self._stop.wait(max(0.5, interval - (time.time() - t0)))

    def _teardown(self) -> None:
        lab = self.lab
        result: Dict[str, Any] = {}
        result["locust"] = lab.pm.stop("locust", timeout=15)
        result["operator"] = lab.pm.stop("operator", timeout=30, first_signal=15)
        if self.started_at is not None:
            lab.last_load_end = time.time()
        hpa_mgr = lab.hpa_manager(self.req.app)
        restored: List[str] = []
        frozen_left: List[str] = ["unknown"]
        deadline = time.time() + 180
        while True:
            restored += hpa_mgr.restore_all_frozen() + hpa_mgr.restore_unmanaged_replicas()
            listed = lab.discovery(self.req.app).list_all(force_refresh=True)
            if lab.discovery(self.req.app).last_error is None:
                frozen_left = [w.hpa.name for w in listed if w.hpa and w.hpa.frozen]
            if not frozen_left or time.time() > deadline:
                break
            self.event("warning", "HPA restore incomplete (Kubernetes API slow?); retrying")
            time.sleep(10)
        result["hpas_restored"] = restored
        lease = ControllerLease(self.policy.namespace, self.policy.name, kube=lab.kube)
        st = lease.status()
        result["lease_holder_after"] = st.holder if not st.expired else None
        result["frozen_hpas_after"] = frozen_left
        result["safe"] = not frozen_left and (st.expired or not st.holder) and not lab.pm.is_running("operator")
        self.cleanup = result
        if self.started_at is not None or self.req.controller == "flexascale":
            self.event("ownership", "Cleanup: " + ("native HPA ownership verified" if result["safe"] else "WARNING - verify ownership manually"), cleanup=result)

    # -- sampling ------------------------------------------------------------

    def _read_new_lines(self, path: Path, offset_attr: str) -> List[str]:
        if not path.is_file():
            return []
        offset = getattr(self, offset_attr)
        with path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            data = f.read()
            setattr(self, offset_attr, f.tell())
        return [line for line in data.splitlines() if line.strip()]

    def _sample(self) -> None:
        lab = self.lab
        now = time.time()
        workloads = lab.discovery(self.req.app).discover(force_refresh=True)
        names = [w.name for w in workloads]
        metrics = lab.metrics.collect(
            self.policy.namespace, names,
            {w.name: w.cpu_request_cores for w in workloads},
            {w.name: (w.memory_limit_bytes or w.memory_request_bytes) for w in workloads},
        )
        locust = read_locust_history(self.dir / "locust_stats_history.csv") or {}

        for line in self._read_new_lines(self.dir / "locust.log", "_locust_log_offset"):
            if line.startswith("FLEXASCALE_PHASE"):
                parts = line.split()
                if len(parts) >= 3:
                    self.event("traffic", f"Traffic phase '{parts[1]}' -> {parts[2]} users", phase=parts[1], users=int(parts[2]))
        decisions = []
        for line in self._read_new_lines(self.dir / "decisions.jsonl", "_decision_offset"):
            try:
                decisions.append(json.loads(line))
            except ValueError:
                continue
        self._decision_events(decisions)

        services: Dict[str, Dict[str, Any]] = {}
        for w in workloads:
            m = metrics.get(w.name)
            svc = {
                "desired": w.desired_replicas,
                "ready": w.ready_replicas,
                "hpa": w.hpa.name if w.hpa else None,
                "hpa_min": w.hpa.min_replicas if w.hpa else None,
                "hpa_max": w.hpa.max_replicas if w.hpa else None,
                "hpa_desired": w.hpa.desired_replicas if w.hpa else None,
                "frozen": bool(w.hpa and w.hpa.frozen),
                "cpu_request_cores": w.cpu_request_cores,
                "memory_request_bytes": w.memory_request_bytes,
                "cpu_pct": m.cpu_pct if m else None,
                "memory_pct": m.memory_pct if m else None,
                "cpu_cores": m.cpu_cores if m else None,
                "memory_bytes": m.memory_bytes if m else None,
                "request_rate": m.request_rate if m else None,
                "latency_ms": m.latency_mean_ms if m else None,
                "latency_p95_ms": m.latency_p95_ms if m else None,
                "stale": bool(m.stale) if m else True,
                "missing": list(m.missing) if m else ["all"],
            }
            services[w.name] = svc
            self._replica_events(w.name, svc)
        p95 = locust.get("p95_ms")
        e2e_violation = p95 is not None and p95 > lab.cfg.e2e_p95_slo_ms
        if e2e_violation != self._e2e_violating and locust:
            self.event("metric", ("End-to-end p95 above" if e2e_violation else "End-to-end p95 back below")
                       + f" SLO ({p95:.0f} ms vs {lab.cfg.e2e_p95_slo_ms:.0f} ms)", p95_ms=p95)
            self._e2e_violating = e2e_violation
        sample = {
            "t": now,
            "elapsed": round(now - (self.started_at or now), 1),
            **{k: locust.get(k) for k in ("users", "rps", "fail_rps", "p50_ms", "p95_ms", "p99_ms", "total_requests", "total_failures")},
            "e2e_slo_violation": e2e_violation,
            "services": services,
        }
        with self._lock:
            self.samples.append(sample)

    def _replica_events(self, name: str, svc: Dict[str, Any]) -> None:
        prev = self._prev.get(name)
        self._prev[name] = {"desired": svc["desired"], "ready": svc["ready"], "cpu_pct": svc["cpu_pct"],
                            "pending": (prev or {}).get("pending", False)}
        if prev is None:
            return
        if svc["desired"] != prev["desired"]:
            if svc["frozen"]:
                who = "FlexaScale"
            elif svc["hpa"]:
                who = "HPA"
            else:
                who = "FlexaScale (no HPA)" if self.req.controller == "flexascale" else "manual/other"
            self.event("replicas", f"{name}: desired replicas {prev['desired']} -> {svc['desired']} (owner: {who})",
                       service=name, frm=prev["desired"], to=svc["desired"], owner=who)
            self._prev[name]["pending"] = True
        if self._prev[name]["pending"] and svc["ready"] == svc["desired"]:
            self.event("ready", f"{name}: {svc['ready']}/{svc['desired']} replicas ready", service=name, ready=svc["ready"])
            self._prev[name]["pending"] = False
        target = self.policy.cpu_target_pct
        after = svc["cpu_pct"]
        above = (prev or {}).get("cpu_above", False)
        if after is not None:
            if not above and after >= target + 5:
                above = True
                self.event("metric", f"{name}: CPU above {target:.0f}% target ({after:.0f}% of request)",
                           service=name, cpu_pct=round(after, 1))
            elif above and after <= target - 10:
                above = False
                self.event("metric", f"{name}: CPU back below target ({after:.0f}% of request)",
                           service=name, cpu_pct=round(after, 1))
        self._prev[name]["cpu_above"] = above

    def _decision_events(self, decisions: List[Dict[str, Any]]) -> None:
        pending: Dict[Any, List[Dict[str, Any]]] = {}
        for d in decisions:
            if d.get("type") == "event":
                ev = d.get("event")
                if ev in ("lease_lost", "no_eligible_workloads"):
                    self.event("safety", f"Operator: {ev}", detail=d)
                continue
            pol = d.get("policy", {})
            svc = d.get("service")
            reasons = d.get("safety_reasons", [])
            if d.get("applied"):
                self.event("scale_request", f"{svc}: FlexaScale requested {d['current_replicas']} -> {d['proposed_replicas']} "
                           f"({pol.get('action_label')}, confidence {pol.get('confidence', 0):.2f}, {pol.get('mode')})",
                           service=svc, frm=d["current_replicas"], to=d["proposed_replicas"],
                           confidence=pol.get("confidence"), policy_mode=pol.get("mode"))
            elif d.get("apply_error"):
                self.event("safety", f"{svc}: scale not applied ({d['apply_error']})", service=svc)
            elif pol.get("action") != 1:
                pending.setdefault(d.get("step"), []).append(d)
            if any(r.startswith(("scale_down_blocked", "telemetry_")) for r in reasons) and d.get("mode") == "live":
                self.event("safety", f"{svc}: {', '.join(reasons)}", service=svc)
        for step, items in pending.items():
            observe = items[0].get("mode") == "observe"
            parts = []
            for d in items:
                pol = d.get("policy", {})
                arrow = "+1" if pol.get("action") == 2 else "-1"
                owner = "FS" if d.get("controller") == "flexascale" else "HPA"
                parts.append(f"{d.get('service')} {arrow} ({pol.get('confidence', 0):.2f}, {owner})")
            verb = "would propose" if observe else "proposed (not applied)"
            self.event("decision", f"Policy step {step} {verb}: " + "; ".join(parts),
                       step=step, mode=items[0].get("mode"), policy_mode=items[0].get("policy", {}).get("mode"),
                       proposals=[{"service": d.get("service"), "action": d.get("policy", {}).get("action_label"),
                                   "confidence": d.get("policy", {}).get("confidence"),
                                   "controller": d.get("controller"), "reasons": d.get("safety_reasons")} for d in items])

    # -- results -------------------------------------------------------------

    def _finalize(self) -> None:
        final = read_locust_final(self.dir / "locust_stats.csv") or {}
        samples = self.samples
        interval_slo_s = 0.0
        svc_slo_s = 0.0
        slo_ms = self.policy.slo_latency_ms
        for cur, nxt in zip(samples, samples[1:]):
            dt = nxt["t"] - cur["t"]
            if cur.get("e2e_slo_violation"):
                interval_slo_s += dt
            if slo_ms and any((s.get("latency_ms") or 0) > slo_ms for s in cur["services"].values()):
                svc_slo_s += dt
        windows = [s for s in samples if s.get("p95_ms") is not None]
        desired_series: Dict[str, List[int]] = {}
        for s in samples:
            for name, svc in s["services"].items():
                desired_series.setdefault(name, []).append(int(svc["desired"]))
        resources = summarize_resources(
            [{"t": s["t"], "services": s["services"]} for s in samples if s.get("services")], self.policy.cost
        ) if len(samples) > 1 else None
        cpu_vals = [svc["cpu_pct"] for s in samples for svc in s["services"].values() if svc.get("cpu_pct") is not None]
        mem_vals = [svc["memory_pct"] for s in samples for svc in s["services"].values() if svc.get("memory_pct") is not None]
        decisions = []
        dpath = self.dir / "decisions.jsonl"
        if dpath.is_file():
            for line in dpath.read_text().splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") == "decision":
                    decisions.append(d)
        actual = (self.ended_at or time.time()) - (self.started_at or self.created_at)
        complete = self._final_state == "completed" and actual >= 0.95 * self.req.duration
        self.summary = {
            "complete": complete,
            "settled_start": start_settled({"samples": samples, "start_replicas": self.start_replicas,
                                            "request": dataclasses.asdict(self.req),
                                            "policy": {"min_replicas": self.policy.min_replicas}}),
            "reset_check_passed": self.settled_start,
            "preliminary": (not complete) or self.req.duration < 300,
            "actual_duration_s": round(actual, 1),
            "samples": len(samples),
            "workload": final,
            "slo": {
                "e2e_p95_slo_ms": self.lab.cfg.e2e_p95_slo_ms,
                "e2e_violation_seconds": round(interval_slo_s, 1),
                "e2e_violation_fraction": round(sum(1 for s in windows if s["e2e_slo_violation"]) / len(windows), 4) if windows else None,
                "service_mean_slo_ms": slo_ms,
                "service_violation_seconds": round(svc_slo_s, 1),
            },
            "utilization": {
                "avg_cpu_pct_of_request": round(sum(cpu_vals) / len(cpu_vals), 2) if cpu_vals else None,
                "peak_cpu_pct_of_request": round(max(cpu_vals), 2) if cpu_vals else None,
                "avg_memory_pct": round(sum(mem_vals) / len(mem_vals), 2) if mem_vals else None,
            },
            "replicas": {
                "avg_total_desired": round(sum(sum(v[i] for v in desired_series.values()) for i in range(len(samples))) / len(samples), 2) if samples and desired_series else None,
                "peak_total_desired": max((sum(v[i] for v in desired_series.values()) for i in range(len(samples))), default=None) if desired_series else None,
            },
            "stability": scaling_stability(desired_series),
            "resources": resources.to_dict() if resources else None,
            "decisions": {
                "total": len(decisions),
                "applied": sum(1 for d in decisions if d.get("applied")),
                "proposed_changes": sum(1 for d in decisions if d.get("policy", {}).get("action") != 1),
                "flexascale_owned": sum(1 for d in decisions if d.get("controller") == "flexascale"),
                "hpa_fallbacks": sum(1 for d in decisions if d.get("controller") != "flexascale"),
                "policy_modes": sorted({d.get("policy", {}).get("mode") for d in decisions if d.get("policy")}),
            },
        }

    def _write_files(self, final_state: str) -> None:
        snap = self.snapshot(max_samples=10 ** 6)
        snap["state"] = final_state
        snap["policy"] = self.policy.to_dict()
        (self.dir / "run.json").write_text(json.dumps(snap, indent=2, default=str))
        fields = ["t", "elapsed", "users", "rps", "fail_rps", "p50_ms", "p95_ms", "p99_ms", "e2e_slo_violation",
                  "service", "desired", "ready", "hpa_desired", "hpa_min", "hpa_max", "frozen", "cpu_pct", "memory_pct",
                  "cpu_cores", "memory_bytes", "request_rate", "latency_ms", "latency_p95_ms", "stale"]
        with (self.dir / "telemetry.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for s in self.samples:
                for name, svc in s["services"].items():
                    writer.writerow({**{k: s.get(k) for k in fields[:9]}, "service": name, **svc})


# ---------------------------------------------------------------------------
# Lab facade
# ---------------------------------------------------------------------------


class Lab:
    def __init__(self, config_path: str | Path = "config/lab.yaml", runtime_dir: str | Path = ".runtime",
                 kube: Optional[Kube] = None) -> None:
        self.config_path = Path(config_path)
        self.cfg = LabConfig.load(self.config_path)
        self.kube = kube or Kube()
        self.pm = ProcessManager(runtime_dir)
        self.metrics = WorkloadMetricsClient(self.cfg.prometheus_url)
        self.active: Optional[Experiment] = None
        self._lock = threading.Lock()
        self._discoveries: Dict[str, WorkloadDiscovery] = {}
        self._live_cache: Dict[str, Any] = {}
        self._urls: Dict[str, str] = {}
        self.last_load_end = self._last_recorded_load_end()

    def _last_recorded_load_end(self) -> float:
        """End time of the most recent recorded run that generated load (survives server restarts)."""
        latest = 0.0
        for path in (ROOT / self.cfg.results_dir).glob("*/run.json"):
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if data.get("started_at") and data.get("ended_at"):
                latest = max(latest, float(data["ended_at"]))
        return latest

    # -- configuration ------------------------------------------------------

    def policy(self, app: str) -> AppPolicy:
        spec = self.cfg.apps[app]
        policy = AppPolicy.load(ROOT / spec.policy_path)
        return dataclasses.replace(policy, prometheus_url=self.cfg.prometheus_url)

    def discovery(self, app: str) -> WorkloadDiscovery:
        if app not in self._discoveries:
            self._discoveries[app] = WorkloadDiscovery(self.policy(app), kube=self.kube)
        return self._discoveries[app]

    def hpa_manager(self, app: str) -> HPAManager:
        p = self.policy(app)
        return HPAManager(SafetyConfig(namespace=p.namespace, dry_run=False), mock=False, kube=self.kube,
                          holder=f"flexascale-{p.name}")

    def app_url(self, app: str) -> str:
        """Application URL, resolved once (``minikube ip`` is slow) and cached."""
        if app not in self._urls or not self._urls[app]:
            self._urls[app] = resolve_app_url(self.cfg.apps[app], self.cfg.minikube_profile)
        return self._urls[app]

    def apps(self) -> List[Dict[str, Any]]:
        out = []
        for name, spec in self.cfg.apps.items():
            try:
                p = self.policy(name)
                out.append({"name": name, "title": spec.title, "namespace": p.namespace, "mode": p.mode,
                            "policy": spec.policy_path, "valid": not p.validate(),
                            "url": self.app_url(name)})
            except Exception as exc:
                out.append({"name": name, "title": spec.title, "error": str(exc), "valid": False})
        return out

    # -- live state ---------------------------------------------------------

    def cluster_health(self) -> Dict[str, Any]:
        ctx = self.kube.run("config", "current-context", timeout=5)
        nodes = self.kube.get_json("nodes", "default") if ctx.ok else None
        ready_nodes = 0
        for n in (nodes or {}).get("items", []):
            for c in n.get("status", {}).get("conditions", []):
                if c.get("type") == "Ready" and c.get("status") == "True":
                    ready_nodes += 1
        return {
            "kubectl": ctx.ok,
            "context": ctx.stdout.strip() if ctx.ok else None,
            "nodes_ready": ready_nodes,
            "nodes_total": len((nodes or {}).get("items", [])),
            "prometheus": self.metrics.healthy(),
            "prometheus_url": self.cfg.prometheus_url,
            "grafana_url": self.cfg.grafana_url,
            "error": None if ctx.ok else ctx.stderr,
        }

    def live(self, app: str) -> Dict[str, Any]:
        cached = self._live_cache.get(app)
        if cached and time.time() - cached["ts"] < 2.0:
            return cached["data"]
        policy = self.policy(app)
        disc = self.discovery(app)
        all_w = disc.list_all(force_refresh=True)
        eligible = [w for w in all_w if w.eligible]
        metrics = self.metrics.collect(
            policy.namespace, [w.name for w in eligible],
            {w.name: w.cpu_request_cores for w in eligible},
            {w.name: (w.memory_limit_bytes or w.memory_request_bytes) for w in eligible},
        )
        lease = ControllerLease(policy.namespace, policy.name, kube=self.kube).status()
        op_status = None
        status_path = self.pm.runtime_dir / "operator_status.json"
        if self.pm.is_running("operator") and status_path.is_file():
            try:
                op_status = json.loads(status_path.read_text())
            except ValueError:
                op_status = None
        services = []
        for w in all_w:
            m = metrics.get(w.name)
            if w.hpa and w.hpa.frozen:
                owner = "flexascale"
            elif w.hpa:
                owner = "hpa"
            else:
                owner = "none"
            services.append({
                **w.to_dict(),
                "owner": owner if w.eligible else "excluded",
                "metrics": m.to_dict() if m else None,
            })
        data = {
            "app": app,
            "namespace": policy.namespace,
            "timestamp": time.time(),
            "discovery_error": disc.last_error,
            "prometheus_error": None if self.metrics.last_error is None else self.metrics.last_error,
            "services": services,
            "lease": lease.to_dict(),
            "operator": op_status,
            "policy": {"mode": policy.mode, "slo_latency_ms": policy.slo_latency_ms, "cpu_target_pct": policy.cpu_target_pct,
                       "min_replicas": policy.min_replicas, "max_replicas": policy.max_replicas,
                       "confidence_threshold": policy.confidence_threshold, "model_path": policy.model_path,
                       "topology": [list(e) for e in policy.topology]},
        }
        self._live_cache[app] = {"ts": time.time(), "data": data}
        return data

    # -- experiments --------------------------------------------------------

    def start(self, req: ExperimentRequest) -> Experiment:
        errors = req.validate(self.cfg)
        if errors:
            raise ValueError("; ".join(errors))
        with self._lock:
            if self.active is not None and self.active.state not in TERMINAL_STATES:
                raise RuntimeError(f"experiment {self.active.id} is still {self.active.state}")
            if self.pm.is_running("locust"):
                raise RuntimeError("a Locust process from an earlier run is still running; use scripts/stop_review.sh")
            exp = Experiment(self, req)
            self.active = exp
            exp.start()
            return exp

    def stop(self) -> Optional[Experiment]:
        exp = self.active
        if exp is not None and exp.state not in TERMINAL_STATES:
            exp.stop()
        return exp

    def shutdown(self) -> None:
        exp = self.active
        if exp is not None and exp.state not in TERMINAL_STATES:
            exp.stop()
            exp.thread.join(timeout=90)

    def runs(self) -> List[Dict[str, Any]]:
        base = ROOT / self.cfg.results_dir
        out = []
        for path in sorted(base.glob("*/run.json"), reverse=True):
            try:
                data = json.loads(path.read_text())
            except ValueError:
                continue
            s = data.get("summary") or {}
            out.append({
                "id": data["id"], "request": data["request"], "state": data["state"],
                "started_at": data.get("started_at"), "complete": s.get("complete"), "preliminary": s.get("preliminary"),
                "throughput_rps": (s.get("workload") or {}).get("throughput_rps"),
                "p95_ms": (s.get("workload") or {}).get("p95_ms"),
                "replica_hours": (s.get("resources") or {}).get("replica_hours"),
            })
        return out

    def run(self, run_id: str) -> Dict[str, Any]:
        if self.active is not None and self.active.id == run_id:
            return self.active.snapshot()
        path = ROOT / self.cfg.results_dir / run_id / "run.json"
        if "/" in run_id or ".." in run_id or not path.is_file():
            raise KeyError(run_id)
        return json.loads(path.read_text())

    def compare(self, baseline_id: str, candidate_id: str) -> Dict[str, Any]:
        a, b = self.run(baseline_id), self.run(candidate_id)
        ra, rb = a["request"], b["request"]
        sa, sb = a.get("summary") or {}, b.get("summary") or {}
        issues = []
        for key in ("app", "scenario", "users", "spawn_rate"):
            if ra.get(key) != rb.get(key):
                issues.append(f"different {key}: {ra.get(key)} vs {rb.get(key)}")
        da, db = sa.get("actual_duration_s") or 0, sb.get("actual_duration_s") or 0
        if max(da, db) > 0 and abs(da - db) / max(da, db) > 0.10:
            issues.append(f"durations differ by more than 10% ({da:.0f}s vs {db:.0f}s)")
        if not (sa.get("complete") and sb.get("complete")):
            issues.append("at least one run is incomplete")
        if start_settled(a) is False or start_settled(b) is False:
            issues.append("at least one run did not start from settled minimum replicas")
        if ra.get("controller") == rb.get("controller"):
            issues.append("both runs use the same controller")
        comparable = not issues

        def g(s: Dict[str, Any], path: str) -> Any:
            cur: Any = s
            for part in path.split("."):
                cur = (cur or {}).get(part) if isinstance(cur, dict) else None
            return cur

        rows_spec = [
            ("Throughput (req/s)", "workload.throughput_rps", "higher"),
            ("Total requests", "workload.total_requests", "higher"),
            ("Failure rate (%)", "workload.failure_rate_pct", "lower"),
            ("p50 latency (ms)", "workload.p50_ms", "lower"),
            ("p95 latency (ms)", "workload.p95_ms", "lower"),
            ("p99 latency (ms)", "workload.p99_ms", "lower"),
            ("E2E p95 SLO violation (s)", "slo.e2e_violation_seconds", "lower"),
            ("E2E p95 SLO violation (fraction of windows)", "slo.e2e_violation_fraction", "lower"),
            ("Service latency SLO violation (s)", "slo.service_violation_seconds", "lower"),
            ("Avg CPU (% of request)", "utilization.avg_cpu_pct_of_request", "context"),
            ("Avg memory (%)", "utilization.avg_memory_pct", "context"),
            ("Avg total replicas", "replicas.avg_total_desired", "lower"),
            ("Peak total replicas", "replicas.peak_total_desired", "lower"),
            ("Replica-hours", "resources.replica_hours", "lower"),
            ("Allocated vCPU-hours", "resources.allocated_vcpu_hours", "lower"),
            ("Allocated GiB-hours", "resources.allocated_gib_hours", "lower"),
            ("Used vCPU-hours (observed)", "resources.used_vcpu_hours", "context"),
            ("CPU allocation efficiency (%)", "resources.cpu_allocation_efficiency_pct", "higher"),
            ("Resource-cost proxy", "resources.resource_cost_proxy", "lower"),
            ("Estimated cost", "resources.estimated_cost", "lower"),
            ("Scaling events", "stability.scaling_events", "context"),
            ("Oscillations (reversals)", "stability.oscillations", "lower"),
        ]
        rows = []
        for label, path, better in rows_spec:
            va, vb = g(sa, path), g(sb, path)
            pct = percent_change(va, vb) if comparable and isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
            rows.append({"metric": label, "baseline": va, "candidate": vb,
                         "delta": (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None,
                         "pct_change": round(pct, 2) if pct is not None else None, "better": better})
        return {
            "baseline": {"id": a["id"], "request": ra, "preliminary": sa.get("preliminary")},
            "candidate": {"id": b["id"], "request": rb, "preliminary": sb.get("preliminary")},
            "comparable": comparable,
            "issues": issues,
            "cost_label": (sb.get("resources") or sa.get("resources") or {}).get("cost_label"),
            "rows": rows,
        }
