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
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from flexascale.config.app_policy import AppPolicy
from flexascale.config.safety_config import SafetyConfig
from flexascale.discovery.workloads import (
    ANNOTATION_ORIGINAL_BEHAVIOR,
    ANNOTATION_ORIGINAL_METRICS,
    WorkloadDiscovery,
    WorkloadInfo,
)
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
    "calibration_steady": {"title": "Calibration (steady mix)", "description": "HPA-tuned calibration only (docs/POLICY_V7.md §2.1): "
                           "browsing and shopping 5:5 at constant load. Not an evaluation scenario."},
}
CONTROLLERS = ("hpa", "flexascale", "auto", "hpa_fast", "hpa_tuned")
# "hpa_fast": native HPA with only its scale-down stabilisation window shortened (default 300 s), restored after
# the run. A tuned-HPA reference; never used as the baseline of a pair.
HPA_FAST_SCALE_DOWN_S = 60
# "hpa_tuned": native HPA with a scale-down window and a CPU target (percent of request) set for the run and
# restored afterwards (docs/POLICY_V7.md §2). Values come from the request or the lab config's `hpa_tuned` block.
NATIVE_HPA_CONTROLLERS = ("hpa", "hpa_fast", "hpa_tuned")
HPA_TARGET_LIMITS = (10, 1000)
HPA_WINDOW_LIMITS = (0, 3600)
LIMITS = {"users": (1, 500), "spawn_rate": (0.1, 100.0), "duration": (30, 3600)}
TERMINAL_STATES = ("completed", "stopped", "failed", "interrupted")
OPERATOR_STALL_STEPS = 4
"""Watchdog: a live operator whose status has not advanced for this many poll intervals is treated as hung."""
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
    reset_requests: List[Dict[str, Any]] = field(default_factory=list)
    """HTTP calls made before every run so each starts from the same data (e.g. restock, empty carts)."""
    variants: Dict[str, str] = field(default_factory=dict)
    """Alternative policy files for the same application (e.g. another model), selected per run."""


@dataclass
class LabConfig:
    minikube_profile: str = "flexascale"
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3000"
    results_dir: str = "reports/experiments"
    sample_interval_seconds: float = 5.0
    e2e_p95_slo_ms: float = 1000.0
    hpa_tuned: Dict[str, Any] = field(default_factory=dict)
    """Default settings of the `hpa_tuned` controller: cpu_target_pct, scale_down_window_s."""
    apps: Dict[str, LabApp] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "LabConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        apps = {
            name: LabApp(
                name=name,
                title=spec.get("title", name),
                policy_path=spec["policy"],
                url=spec.get("url", ""),
                locustfile=spec.get("locustfile", "load-testing/scenarios.py"),
                reset_requests=list(spec.get("reset_requests") or []),
                variants=dict(spec.get("variants") or {}),
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
    policy_variant: Optional[str] = None
    """One of the app's `variants` in the lab config (another policy file / model); None = the app's policy."""
    hpa_cpu_target_pct: Optional[int] = None
    """hpa_tuned only: CPU target in percent of request (default: lab config `hpa_tuned.cpu_target_pct`)."""
    hpa_scale_down_window_s: Optional[int] = None
    """hpa_tuned only: scale-down stabilisation window (default: lab config `hpa_tuned.scale_down_window_s`)."""
    block: Optional[str] = None
    """Free label recorded with the run, e.g. the block of a pre-registered design (docs/POLICY_V7.md §3.3)."""

    def hpa_tuned_settings(self, cfg: LabConfig) -> Tuple[Optional[int], Optional[int]]:
        target = self.hpa_cpu_target_pct if self.hpa_cpu_target_pct is not None else cfg.hpa_tuned.get("cpu_target_pct")
        window = (self.hpa_scale_down_window_s if self.hpa_scale_down_window_s is not None
                  else cfg.hpa_tuned.get("scale_down_window_s"))
        return (None if target is None else int(target)), (None if window is None else int(window))

    def validate(self, cfg: LabConfig) -> List[str]:
        errors = []
        if self.app not in cfg.apps:
            errors.append(f"unknown app '{self.app}'")
        elif self.policy_variant is not None and self.policy_variant not in cfg.apps[self.app].variants:
            errors.append(f"unknown policy variant '{self.policy_variant}' for app '{self.app}'")
        if self.controller not in CONTROLLERS:
            errors.append(f"controller must be one of {CONTROLLERS}")
        if self.controller == "hpa_tuned":
            target, window = self.hpa_tuned_settings(cfg)
            if target is None or not HPA_TARGET_LIMITS[0] <= target <= HPA_TARGET_LIMITS[1]:
                errors.append(f"hpa_tuned needs a CPU target between {HPA_TARGET_LIMITS[0]} and {HPA_TARGET_LIMITS[1]}%")
            if window is None or not HPA_WINDOW_LIMITS[0] <= window <= HPA_WINDOW_LIMITS[1]:
                errors.append(f"hpa_tuned needs a scale-down window between {HPA_WINDOW_LIMITS[0]} and {HPA_WINDOW_LIMITS[1]} s")
        elif self.hpa_cpu_target_pct is not None or self.hpa_scale_down_window_s is not None:
            if self.controller not in ("auto", "flexascale"):
                errors.append("hpa_cpu_target_pct / hpa_scale_down_window_s apply only to hpa_tuned, auto and flexascale")
            # auto / flexascale: the native HPA settings in force whenever HPA owns a service during the run
            if self.hpa_cpu_target_pct is not None and not HPA_TARGET_LIMITS[0] <= self.hpa_cpu_target_pct <= HPA_TARGET_LIMITS[1]:
                errors.append(f"hpa_cpu_target_pct must be between {HPA_TARGET_LIMITS[0]} and {HPA_TARGET_LIMITS[1]}")
            if (self.hpa_scale_down_window_s is not None
                    and not HPA_WINDOW_LIMITS[0] <= self.hpa_scale_down_window_s <= HPA_WINDOW_LIMITS[1]):
                errors.append(f"hpa_scale_down_window_s must be between {HPA_WINDOW_LIMITS[0]} and {HPA_WINDOW_LIMITS[1]}")
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
        with path.open(newline="", encoding="utf-8") as f:
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
        "p90_ms": _float(last.get("90%")),
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
        with path.open(newline="", encoding="utf-8") as f:
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
                        "p90_ms": _float(row.get("90%")),
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
    snapshot = run.get("start_replicas") or (run.get("initial_replicas") if controller in ("flexascale", "auto") else None)
    if snapshot:
        return all(int(v) <= floor(k) for k, v in snapshot.items())
    if first:
        return all(int(svc.get("desired") or 0) <= floor(name) for name, svc in first.items())
    return (run.get("summary") or {}).get("settled_start")


def _reachable(host: str, port: int = 80, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_app_url(app: LabApp, profile: str) -> str:
    """``minikube-ingress``: the Minikube IP if this host can reach it (Linux), else the ingress
    through ``minikube tunnel`` on 127.0.0.1 (Docker driver on Windows/macOS; fsctl start runs it)."""
    if app.url != "minikube-ingress":
        return app.url
    try:
        ip = subprocess.run(["minikube", "ip", "-p", profile], capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        ip = ""
    if ip and _reachable(ip):
        return f"http://{ip}"
    if _reachable("127.0.0.1"):
        return "http://127.0.0.1"
    return f"http://{ip}" if ip else ""


def host_snapshot() -> Dict[str, Any]:
    """Host conditions for the run's validity checks (scripts/check_host_load.py): AC power, whole-machine
    CPU in cores since the previous call (on Windows/macOS this includes the Docker VM running Minikube)
    and the current CPU clock. Values the platform does not provide are None."""
    out: Dict[str, Any] = {"on_ac": None, "battery_pct": None, "cpu_cores": None, "cpu_mhz": None}
    try:
        import psutil

        bat = psutil.sensors_battery()
        if bat is not None:
            out["on_ac"] = bat.power_plugged
            out["battery_pct"] = round(bat.percent, 1)
        out["cpu_cores"] = round(psutil.cpu_percent(None) / 100.0 * (psutil.cpu_count() or 1), 2)
        freq = psutil.cpu_freq()
        out["cpu_mhz"] = round(freq.current) if freq else None
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class Experiment:
    def __init__(self, lab: "Lab", req: ExperimentRequest) -> None:
        self.lab = lab
        self.req = req
        self.app = lab.cfg.apps[req.app]
        self.policy = lab.policy(req.app, req.policy_variant)
        self.policy_path = lab.policy_path(req.app, req.policy_variant)
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
        self._proposals: Dict[str, Dict[str, Any]] = {}
        self.auto_state: Dict[str, Dict[str, Any]] = {}
        self.auto_counts: Dict[str, int] = {}
        self.operator_failure: Optional[Dict[str, Any]] = None
        """Set when the live FlexaScale operator died or stopped stepping mid-run (the run continued under native HPA)."""
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

    def snapshot(self, max_samples: int = 720, samples_from: Optional[int] = None,
                 events_from: Optional[int] = None) -> Dict[str, Any]:
        """Incremental polling (the dashboard timeline): ``samples_from`` / ``events_from`` return only the
        entries from that index on. Both lists are append-only, so an index never skips or repeats an entry
        (a time cursor could: an event may be stamped before a sample that is appended after it)."""
        with self._lock:
            delta = samples_from is not None or events_from is not None
            samples = self.samples[max(0, samples_from or 0):] if delta else self.samples[-max_samples:]
            events = self.events[max(0, events_from or 0):] if delta else self.events
            return {
                "delta": delta,
                "samples_offset": max(0, samples_from or 0) if delta else len(self.samples) - len(samples),
                "samples_total": len(self.samples),
                "events_total": len(self.events),
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
                "events": list(events),
                "samples": list(samples),
                "sample_interval_s": self.lab.cfg.sample_interval_seconds,
                "summary": self.summary,
                "cleanup": self.cleanup,
                "model": self.model_info,
                "initial_replicas": self.initial_replicas,
                "start_replicas": self.start_replicas,
                "slo": {"e2e_p95_ms": self.lab.cfg.e2e_p95_slo_ms, "service_mean_ms": self.policy.slo_latency_ms},
                "auto_state": dict(self.auto_state),
                "auto_counts": dict(self.auto_counts),
                "operator_failure": self.operator_failure,
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
        if self.app.reset_requests:
            self._reset_app_data()
        workloads = lab.discovery(self.req.app).discover(force_refresh=True)
        if not workloads:
            raise RuntimeError(f"no eligible Deployments found in namespace '{policy.namespace}'")
        names = [w.name for w in workloads]
        self.event("preflight", f"{len(names)} eligible services: {', '.join(names)}", services=names)

        hpa_mgr = lab.hpa_manager(self.req.app)
        restored = hpa_mgr.restore_all_frozen()
        if restored:
            self.event("ownership", f"Restored HPAs left frozen by an earlier run: {', '.join(restored)}")
        restored = hpa_mgr.restore_all_behavior()
        if restored:
            self.event("ownership", f"Restored HPA scale-down behaviour left by an earlier run: {', '.join(restored)}")
        restored = hpa_mgr.restore_all_metrics()
        if restored:
            self.event("ownership", f"Restored HPA CPU targets left by an earlier run: {', '.join(restored)}")
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
        if self.req.controller in NATIVE_HPA_CONTROLLERS:
            if self.req.controller == "hpa_fast":
                changed = hpa_mgr.set_scale_down_window(HPA_FAST_SCALE_DOWN_S)
                missing = [w.hpa.name for w in workloads if w.hpa and w.hpa.name not in changed]
                if missing:
                    raise RuntimeError(f"could not set the HPA scale-down window on {', '.join(missing)}")
                self.event("ownership", f"Native HPA scale-down stabilisation window set to {HPA_FAST_SCALE_DOWN_S} s "
                                        f"(default 300 s) on {len(changed)} HPAs; restored after the run")
            elif self.req.controller == "hpa_tuned":
                target, window = self.req.hpa_tuned_settings(lab.cfg)
                with_hpa = [w.hpa.name for w in workloads if w.hpa]
                changed = hpa_mgr.set_scale_down_window(window)
                missing = [n for n in with_hpa if n not in changed]
                changed_t = hpa_mgr.set_cpu_target(target)
                missing += [n for n in with_hpa if n not in changed_t]
                if missing:
                    raise RuntimeError(f"could not apply the tuned HPA settings to {', '.join(sorted(set(missing)))}")
                self.event("ownership", f"Tuned native HPA: CPU target {target}% of request, scale-down stabilisation "
                                        f"{window} s, on {len(changed_t)} HPAs; restored after the run",
                           hpa_cpu_target_pct=target, hpa_scale_down_window_s=window)
            if without_hpa:
                self.event("ownership", f"No HPA for {', '.join(without_hpa)}: replicas stay fixed under 'HPA' mode")
            self.event("ownership", "Native HPA owns scaling; FlexaScale scaling disabled (lease free, no HPA frozen)")
            if self.req.shadow:
                self._start_operator("observe")
        else:
            # FlexaScale runs may set the native HPA that takes over on hand-back (Auto: "v7 or HPA-tuned")
            if self.req.hpa_scale_down_window_s is not None:
                if not hpa_mgr.set_scale_down_window(self.req.hpa_scale_down_window_s) and any(w.hpa for w in workloads):
                    raise RuntimeError("could not set the HPA scale-down window for this run")
            if self.req.hpa_cpu_target_pct is not None:
                if not hpa_mgr.set_cpu_target(self.req.hpa_cpu_target_pct) and any(w.hpa for w in workloads):
                    raise RuntimeError("could not set the HPA CPU target for this run")
            if self.req.hpa_scale_down_window_s is not None or self.req.hpa_cpu_target_pct is not None:
                self.event("ownership", f"Native HPA used on hand-back: CPU target {self.req.hpa_cpu_target_pct or 'unchanged'}"
                                        f"{'%' if self.req.hpa_cpu_target_pct else ''}, scale-down window "
                                        f"{self.req.hpa_scale_down_window_s if self.req.hpa_scale_down_window_s is not None else 'unchanged'}"
                                        f"{' s' if self.req.hpa_scale_down_window_s is not None else ''}; restored after the run")
            self._start_operator("live", auto=self.req.controller == "auto")

    def _reset_app_data(self) -> None:
        """Run the app's configured reset calls; a failed call refuses the run (it would not be comparable)."""
        import urllib.request

        for spec in self.app.reset_requests:
            paths = [spec["path"].format(id=i) for i in spec.get("ids", [None])] if "ids" in spec else [spec["path"]]
            for path in paths:
                body = json.dumps(spec["json"]).encode() if "json" in spec else None
                req = urllib.request.Request(self.app_url.rstrip("/") + path, data=body, method=spec.get("method", "POST"),
                                             headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        if resp.status >= 400:
                            raise RuntimeError(f"HTTP {resp.status}")
                except Exception as exc:
                    raise RuntimeError(f"app data reset failed: {spec.get('method', 'POST')} {path}: {exc}") from exc
        self.event("preflight", f"Application data reset ({len(self.app.reset_requests)} configured steps)")

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

    def _start_operator(self, mode: str, auto: bool = False) -> None:
        lab = self.lab
        status_file = lab.pm.runtime_dir / "operator_status.json"
        status_file.unlink(missing_ok=True)
        cmd = [
            sys.executable, str(ROOT / "scripts" / "run_operator.py"),
            "--policy", str(ROOT / self.policy_path),
            "--mode", mode,
            "--prometheus-url", lab.cfg.prometheus_url,
            "--decision-log", str(self.dir / "decisions.jsonl"),
            "--status-file", str(status_file),
        ] + (["--auto"] if auto else [])
        lab.pm.start("operator", cmd, cwd=str(ROOT), marker="run_operator.py", log_path=self.dir / "operator.log")
        deadline = time.time() + 90
        while time.time() < deadline:
            if not lab.pm.is_running("operator"):
                raise RuntimeError(f"operator exited during start-up (see {self.dir / 'operator.log'})")
            if status_file.is_file():
                try:
                    status = json.loads(status_file.read_text(encoding="utf-8"))
                except ValueError:
                    status = {}
                if status.get("step", 0) >= 1 or status.get("effective_mode") == mode:
                    self.model_info = status.get("model")
                    if status.get("effective_mode") != mode:
                        raise RuntimeError(f"operator could not enter {mode} mode: {status.get('model_error') or 'lease unavailable'}")
                    if mode == "live":
                        self.event("ownership", "FlexaScale operator holds the controller lease; HPAs are frozen per service before any scale",
                                   lease=(status.get("lease") or {}).get("holder"))
                        if auto:
                            self.event("auto", "Auto mode: each service is assigned to FlexaScale or native HPA by the rules "
                                               "health -> confidence -> SLA risk -> efficiency, one owner at a time")
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
            self._check_operator()
            if self._stop.is_set():
                raise InterruptedError("stop requested")
            if not self.lab.pm.is_running("locust"):
                self._sample()
                break
            if time.time() > hard_deadline:
                self.event("warning", "Workload exceeded its duration by 60 s; stopping it")
                break
            self._stop.wait(max(0.5, interval - (time.time() - t0)))

    def _check_operator(self) -> None:
        """Watchdog for FlexaScale / Auto runs: hand every service back to native HPA if the operator is unhealthy.

        The operator restores HPAs itself on SIGTERM, SIGINT or a failed step, but not when it is killed or hangs.
        It is unhealthy when its process has exited, or when its status file has not advanced for
        ``OPERATOR_STALL_STEPS`` poll intervals. The watchdog then stops it (if alive), restores every frozen HPA and
        every HPA-less Deployment's replicas, and records the failure; the run continues under native HPA.
        """
        if self.req.controller not in ("flexascale", "auto") or self.operator_failure is not None:
            return
        lab = self.lab
        now = time.time()
        reason = None
        if not lab.pm.is_running("operator"):
            reason = "operator process exited"
        else:
            status_file = lab.pm.runtime_dir / "operator_status.json"
            try:
                updated = float(json.loads(status_file.read_text(encoding="utf-8")).get("updated_at") or 0.0)
            except (OSError, ValueError, TypeError):
                updated = 0.0
            limit = OPERATOR_STALL_STEPS * self.policy.poll_interval_seconds
            if updated and now - updated > limit:
                reason = f"operator status not updated for {now - updated:.0f} s (limit {limit:.0f} s)"
        if reason is None:
            return
        stopped = lab.pm.stop("operator", timeout=20, first_signal=15) if lab.pm.is_running("operator") else None
        hpa_mgr = lab.hpa_manager(self.req.app)
        restored = hpa_mgr.restore_all_frozen() + hpa_mgr.restore_unmanaged_replicas()
        self.operator_failure = {"ts": now, "elapsed": round(now - (self.started_at or now), 1), "reason": reason,
                                 "restored": restored, "operator_stop": stopped}
        self.event("fallback", f"FlexaScale unhealthy ({reason}): every service returned to native HPA"
                               + (f" (restored {', '.join(restored)})" if restored else ""),
                   reason=reason, restored=restored)

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
            restored += (hpa_mgr.restore_all_frozen() + hpa_mgr.restore_unmanaged_replicas()
                         + hpa_mgr.restore_all_behavior() + hpa_mgr.restore_all_metrics())
            listed = lab.discovery(self.req.app).list_all(force_refresh=True)
            if lab.discovery(self.req.app).last_error is None:
                frozen_left = [w.hpa.name for w in listed if w.hpa and w.hpa.frozen]
                frozen_left += [o["metadata"]["name"] for o in lab.kube.list_items("hpa", self.policy.namespace) or []
                                if {ANNOTATION_ORIGINAL_BEHAVIOR, ANNOTATION_ORIGINAL_METRICS}
                                & set(o["metadata"].get("annotations") or {})]
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
        if self.started_at is not None or self.req.controller in ("flexascale", "auto"):
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
                "latency_p50_ms": m.latency_p50_ms if m else None,
                "latency_p90_ms": m.latency_p90_ms if m else None,
                "latency_p95_ms": m.latency_p95_ms if m else None,
                "latency_p99_ms": m.latency_p99_ms if m else None,
                "latency_capped": list(m.latency_capped) if m else [],
                "error_rate": m.error_rate if m else None,
                "no_traffic": bool(m.no_traffic) if m else False,
                "stale": bool(m.stale) if m else True,
                "missing": list(m.missing) if m else ["all"],
                **self._proposal_fields(w.name, now),
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
            "host": host_snapshot(),
            **{k: locust.get(k) for k in ("users", "rps", "fail_rps", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "total_requests", "total_failures")},
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
                who = "FlexaScale (no HPA)" if self.req.controller in ("flexascale", "auto") else "manual/other"
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

    def _proposal_fields(self, name: str, now: float) -> Dict[str, Any]:
        """The operator's latest decision for a service, if it is recent enough to belong to this sample.

        ``fs_policy`` is the policy's own proposal, ``fs_proposed`` what FlexaScale asked for after the
        safety guards (only while it owns the service), ``hpa_rule`` the native-HPA rule estimate from the
        same telemetry. Older decisions give None, so the timeline shows a gap, not a carried-over value.
        """
        d = self._proposals.get(name)
        fresh = d is not None and now - d["ts"] <= max(2.5 * self.policy.poll_interval_seconds, 2 * self.lab.cfg.sample_interval_seconds)
        if not fresh:
            return {"fs_policy": None, "fs_proposed": None, "fs_controller": None, "fs_applied": None, "hpa_rule": None}
        return {"fs_policy": d.get("policy_replicas"), "fs_proposed": d.get("proposed") if d.get("controller") == "flexascale" else None,
                "fs_controller": d.get("controller"), "fs_applied": d.get("applied"), "hpa_rule": d.get("hpa_recommendation")}

    def _decision_events(self, decisions: List[Dict[str, Any]]) -> None:
        pending: Dict[Any, List[Dict[str, Any]]] = {}
        for d in decisions:
            if d.get("type") == "decision" and d.get("service"):
                self._proposals[d["service"]] = {
                    "ts": d.get("ts") or time.time(), "policy_replicas": d.get("policy_replicas"),
                    "proposed": d.get("proposed_replicas"), "controller": d.get("controller"),
                    "applied": bool(d.get("applied")), "hpa_recommendation": d.get("hpa_recommendation")}
            if d.get("type") == "event":
                ev = d.get("event")
                if ev in ("lease_lost", "no_eligible_workloads"):
                    self.event("safety", f"Operator: {ev}", detail=d)
                continue
            pol = d.get("policy", {})
            svc = d.get("service")
            reasons = d.get("safety_reasons", [])
            auto = d.get("auto")
            if auto and d.get("mode") == "live":
                prev = self.auto_state.get(svc)
                if prev is None or prev.get("owner") != auto.get("owner"):
                    name = {"flexascale": "FlexaScale", "hpa": "native HPA"}
                    who, rule = name.get(auto["owner"], auto["owner"]), auto["rule"].replace("_", " ")
                    if auto.get("candidate") and auto["candidate"] != auto["owner"]:  # hysteresis: switch pending
                        msg = f"{svc} stays with {who}; {rule} rule chose {name.get(auto['candidate'], auto['candidate'])}: {auto['reason']}"
                    else:
                        msg = f"{svc} -> {who} ({rule}): {auto['reason']}"
                    self.event("auto", msg, service=svc, owner=auto["owner"], rule=auto["rule"])
                self.auto_state[svc] = auto
                self.auto_counts[auto["rule"]] = self.auto_counts.get(auto["rule"], 0) + 1
            if d.get("applied"):
                self.event("scale_request", f"{svc}: FlexaScale requested {d['current_replicas']} -> {d['proposed_replicas']} "
                           f"({pol.get('action_label')}, confidence {pol.get('confidence', 0):.2f}, {pol.get('mode')})",
                           service=svc, frm=d["current_replicas"], to=d["proposed_replicas"],
                           confidence=pol.get("confidence"), policy_mode=pol.get("mode"))
            elif d.get("apply_error"):
                self.event("safety", f"{svc}: scale not applied ({d['apply_error']})", service=svc)
            elif pol.get("delta", (pol.get("action") or 1) - 1) != 0:
                pending.setdefault(d.get("step"), []).append(d)
            if any(r.startswith(("scale_down_blocked", "telemetry_")) for r in reasons) and d.get("mode") == "live":
                self.event("safety", f"{svc}: {', '.join(reasons)}", service=svc)
        for step, items in pending.items():
            observe = items[0].get("mode") == "observe"
            parts = []
            for d in items:
                pol = d.get("policy", {})
                delta = pol.get("delta", (pol.get("action") or 1) - 1)
                arrow = f"{delta:+d}"
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
            for line in dpath.read_text(encoding="utf-8").splitlines():
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
        for key in ("delta", "samples_offset", "samples_total", "events_total"):  # polling metadata, not results
            snap.pop(key, None)
        snap["state"] = final_state
        snap["policy"] = self.policy.to_dict()
        (self.dir / "run.json").write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
        fields = ["t", "elapsed", "users", "rps", "fail_rps", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "e2e_slo_violation",
                  "service", "desired", "ready", "hpa_desired", "hpa_min", "hpa_max", "frozen", "cpu_pct", "memory_pct",
                  "cpu_cores", "memory_bytes", "request_rate", "latency_ms", "latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms",
                  "error_rate", "stale"]
        with (self.dir / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for s in self.samples:
                for name, svc in s["services"].items():
                    writer.writerow({**{k: s.get(k) for k in fields[:10]}, "service": name, **svc})


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
        self._runs_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        # Rolling history of /live results (only while someone polls them), for the live timeline outside experiments.
        self._history: Dict[str, "deque[Dict[str, Any]]"] = {}
        self._urls: Dict[str, str] = {}
        self.last_load_end = self._last_recorded_load_end()

    def _last_recorded_load_end(self) -> float:
        """End time of the most recent recorded run that generated load (survives server restarts)."""
        latest = 0.0
        for path in (ROOT / self.cfg.results_dir).glob("*/run.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("started_at") and data.get("ended_at"):
                latest = max(latest, float(data["ended_at"]))
        return latest

    # -- configuration ------------------------------------------------------

    def policy_path(self, app: str, variant: Optional[str] = None) -> str:
        spec = self.cfg.apps[app]
        return spec.variants[variant] if variant else spec.policy_path

    def policy(self, app: str, variant: Optional[str] = None) -> AppPolicy:
        policy = AppPolicy.load(ROOT / self.policy_path(app, variant))
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
                op_status = json.loads(status_path.read_text(encoding="utf-8"))
            except ValueError:
                op_status = None
        services = []
        for w in all_w:
            m = metrics.get(w.name)
            if w.hpa and w.hpa.frozen:
                # The lab's pre-run reset also freezes HPAs, with the lease free.
                owner = "flexascale" if lease.holder and not lease.expired else "reset"
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
                       "confidence_threshold": policy.confidence_threshold, "deactivation_threshold": policy.deactivation_threshold,
                       "model_path": policy.model_path, "poll_interval_seconds": policy.poll_interval_seconds,
                       "max_total_replicas": policy.max_total_replicas, "topology": [list(e) for e in policy.topology],
                       "cost": dataclasses.asdict(policy.cost), "auto": policy.auto, "auto_valid": not policy.validate()},
        }
        self._live_cache[app] = {"ts": time.time(), "data": data}
        self._record_history(app, data)
        return data

    def _record_history(self, app: str, data: Dict[str, Any]) -> None:
        hist = self._history.setdefault(app, deque(maxlen=720))  # 1 h at the 5 s sample interval
        t = data["timestamp"]
        if hist and t - hist[-1]["t"] < 0.8 * self.cfg.sample_interval_seconds:
            return
        services = {}
        for s in data["services"]:
            if s.get("owner") == "excluded":
                continue
            m = s.get("metrics") or {}
            hpa = s.get("hpa") or {}
            services[s["name"]] = {
                "desired": s.get("desired_replicas"), "ready": s.get("ready_replicas"),
                "hpa_desired": hpa.get("desired_replicas"), "frozen": bool(hpa.get("frozen")), "owner": s.get("owner"),
                **{k: m.get(k) for k in ("cpu_pct", "memory_pct", "request_rate", "error_rate", "latency_mean_ms",
                                         "latency_p50_ms", "latency_p90_ms", "latency_p95_ms", "latency_p99_ms", "no_traffic", "stale", "missing")},
            }
        hist.append({"t": t, "services": services, "lease_held": bool(data["lease"].get("holder")) and not data["lease"].get("expired")})

    def history(self, app: str, since: Optional[float] = None) -> Dict[str, Any]:
        """Live telemetry recorded from /live calls (empty until the dashboard has polled for a while)."""
        hist = list(self._history.get(app, ()))
        if since is not None:
            hist = [h for h in hist if h["t"] > since]
        return {"app": app, "points": hist, "sample_interval_s": self.cfg.sample_interval_seconds,
                "note": "recorded while the dashboard polls /live; not a Prometheus range query"}

    # -- experiments --------------------------------------------------------

    def start(self, req: ExperimentRequest) -> Experiment:
        errors = req.validate(self.cfg)
        if errors:
            raise ValueError("; ".join(errors))
        if req.controller == "hpa_tuned":  # record the settings actually used, even when they came from the config
            target, window = req.hpa_tuned_settings(self.cfg)
            req = dataclasses.replace(req, hpa_cpu_target_pct=target, hpa_scale_down_window_s=window)
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
        """Saved runs, newest first, with the validity facts the Experiments page shows. Rows are cached
        per run.json modification time (each file is up to ~1 MB)."""
        base = ROOT / self.cfg.results_dir
        out = []
        for path in sorted(base.glob("*/run.json"), reverse=True):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            cached = self._runs_cache.get(str(path))
            if cached and cached[0] == mtime:
                out.append(cached[1])
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            row = self._run_row(data)
            self._runs_cache[str(path)] = (mtime, row)
            out.append(row)
        return out

    @staticmethod
    def _run_row(data: Dict[str, Any]) -> Dict[str, Any]:
        s = data.get("summary") or {}
        hosts = [x.get("host") for x in data.get("samples") or [] if x.get("host")]
        on_ac = [h.get("on_ac") for h in hosts if h.get("on_ac") is not None]
        return {
            "id": data["id"], "request": data["request"], "state": data["state"],
            "started_at": data.get("started_at"), "ended_at": data.get("ended_at"),
            "complete": s.get("complete"), "preliminary": s.get("preliminary"),
            "settled_start": start_settled(data), "cleanup_safe": (data.get("cleanup") or {}).get("safe"),
            "error": data.get("error"), "block": (data.get("request") or {}).get("block"),
            "model": ((data.get("model") or {}).get("model_path")),
            "on_battery_samples": (sum(1 for x in on_ac if not x) if on_ac else None),
            "throughput_rps": (s.get("workload") or {}).get("throughput_rps"),
            "p95_ms": (s.get("workload") or {}).get("p95_ms"),
            "failure_rate_pct": (s.get("workload") or {}).get("failure_rate_pct"),
            "replica_hours": (s.get("resources") or {}).get("replica_hours"),
            "estimated_cost": (s.get("resources") or {}).get("estimated_cost"),
        }

    def run(self, run_id: str) -> Dict[str, Any]:
        if self.active is not None and self.active.id == run_id:
            return self.active.snapshot()
        path = ROOT / self.cfg.results_dir / run_id / "run.json"
        if "/" in run_id or ".." in run_id or not path.is_file():
            raise KeyError(run_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        workload = (data.get("summary") or {}).get("workload")
        if isinstance(workload, dict) and "p90_ms" not in workload:
            # Runs recorded before p90 was summarised: read it from the run's own Locust CSV (never estimated).
            workload["p90_ms"] = (read_locust_final(path.parent / "locust_stats.csv") or {}).get("p90_ms")
        return data

    def benchmark(self, app: Optional[str] = None, reference: str = "hpa") -> Dict[str, Any]:
        from flexascale.lab.benchmark import benchmark, load_runs

        return benchmark(load_runs(ROOT / self.cfg.results_dir), self.compare, app, reference)

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
            ("p90 latency (ms)", "workload.p90_ms", "lower"),
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
