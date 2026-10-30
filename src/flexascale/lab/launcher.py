"""
FlexaScale review / demo launcher (Linux, macOS and Windows).

    fsctl start  [--demo] [--check]        preflight, port-forwards, ingress access, dashboard
    fsctl stop   [--force-release-lease]   stop managed processes, restore HPA ownership, verify
    fsctl status                           read-only health report

(``fsctl`` / ``fsctl.cmd`` in the repository root run ``python -m flexascale.lab.launcher``.)

``start`` works with the installed cluster: it starts the existing Minikube profile
if it is stopped, but never creates a profile, rebuilds images, reinstalls charts,
retrains or downloads anything. Safe to repeat: healthy processes it started before
are reused, and it refuses to touch a port held by a process it did not start.

``stop`` stops only processes recorded in ``.runtime/pids`` (never by port), asks a
running experiment to stop first, restores every HPA FlexaScale froze and verifies
that no FlexaScale lease is held. Minikube, Deployments, Helm releases, volumes and
database data are left untouched.

With the Docker driver on Windows and macOS the Minikube IP is not reachable from the
host, so ``start`` runs ``minikube tunnel`` (a managed process) and the shop and Locust
use http://127.0.0.1/ through the cluster's ingress, the same path as the Minikube IP.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import yaml

from flexascale.lab.processes import ProcessManager

ROOT = Path(os.environ.get("FLEXASCALE_ROOT", Path(__file__).resolve().parents[3]))
RUNTIME = ROOT / ".runtime"
PY = sys.executable


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


LAB_PORT = _env_int("FLEXASCALE_LAB_PORT", 8090)
PROM_PORT = _env_int("FLEXASCALE_PROMETHEUS_PORT", 9090)
GRAFANA_PORT = _env_int("FLEXASCALE_GRAFANA_PORT", 3000)
BOOKSTORE_PORT = _env_int("FLEXASCALE_BOOKSTORE_PORT", 18081)
MON_NS = os.environ.get("FLEXASCALE_MONITORING_NS", "flexascale-monitoring")
PROM_SVC = os.environ.get("FLEXASCALE_PROMETHEUS_SVC", "monitoring-kube-prometheus-prometheus")
GRAFANA_SVC = os.environ.get("FLEXASCALE_GRAFANA_SVC", "monitoring-grafana")
STOP_ORDER = ["locust", "operator", "lab", "tunnel", "pf-bookstore", "pf-grafana", "pf-prometheus"]

# ------------------------------------------------------------------ output

_TTY = sys.stdout.isatty()
if os.name == "nt" and _TTY:
    os.system("")  # enables ANSI escape sequences in the Windows console
C_B, C_OK, C_WARN, C_ERR, C_0 = (("\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[0m") if _TTY else ("",) * 5)


class Abort(Exception):
    pass


def step(title: str) -> None:
    print(f"\n{C_B}== {title}{C_0}", flush=True)


def ok(msg: str) -> None:
    print(f"  {C_OK}[ OK ]{C_0} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  {C_WARN}[WARN]{C_0} {msg}", flush=True)


def err(msg: str) -> None:
    print(f"  {C_ERR}[FAIL]{C_0} {msg}", flush=True)


def die(msg: str, fix: str = "") -> None:
    err(msg)
    if fix:
        print(f"         Fix: {fix}")
    raise Abort(msg)


# ------------------------------------------------------------------ helpers


def run(cmd: Sequence[str], timeout: float = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def http_json(url: str, timeout: float = 5.0, method: str = "GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for(check: Callable[[], bool], seconds: float, interval: float = 1.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(interval)
    return check()


def lab_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "lab.yaml").read_text(encoding="utf-8"))


def profile() -> str:
    return os.environ.get("FLEXASCALE_MINIKUBE_PROFILE") or lab_cfg().get("minikube_profile", "flexascale")


def app_namespace(app: str = "shopping") -> str:
    spec = lab_cfg()["apps"][app]
    return yaml.safe_load((ROOT / spec["policy"]).read_text(encoding="utf-8"))["namespace"]


def minikube_ip() -> str:
    return run(["minikube", "ip", "-p", profile()], timeout=20).stdout.strip()


def ingress_url() -> Optional[str]:
    """The URL through which this host reaches the cluster ingress, or None."""
    ip = minikube_ip()
    if ip and port_open(80, ip, timeout=1.0):
        return f"http://{ip}"
    if port_open(80):
        return "http://127.0.0.1"
    return None


def pm() -> ProcessManager:
    return ProcessManager(RUNTIME)


def start_managed(name: str, port: Optional[int], health_url: str, cmd: List[str], marker: str,
                  wait_s: float = 30, health: Optional[Callable[[], bool]] = None) -> None:
    """Start (or reuse) a managed process and wait until it is healthy."""
    procs = pm()
    healthy = health or (lambda: http_ok(health_url, 3))
    if procs.is_running(name):
        if healthy():
            ok(f"{name} already running (reused)")
            return
        warn(f"{name} is running but not healthy; restarting it")
        procs.stop(name, timeout=10)
    if port is not None and port_open(port):
        die(f"port {port} is used by a process FlexaScale did not start", f"free the port or set FLEXASCALE_*_PORT (see RUNNING.md)")
    rec = procs.start(name, cmd, cwd=str(ROOT), marker=marker, log_path=RUNTIME / "logs" / f"{name}.log")
    if wait_for(lambda: healthy() or not procs.is_running(name), wait_s) and healthy():
        ok(f"{name} started (pid {rec.pid})")
    else:
        die(f"{name} did not become healthy within {wait_s:.0f} s", f"see {rec.log}")


def port_forward(name: str, ns: str, target: str, ports: str, health_url: str) -> None:
    start_managed(name, int(ports.split(":")[0]), health_url,
                  [PY, "-m", "flexascale.lab.portforward", ns, target, ports],
                  marker="flexascale.lab.portforward", wait_s=40)


def prom_query(q: str) -> Optional[float]:
    try:
        r = http_json(f"http://localhost:{PROM_PORT}/api/v1/query?" + urllib.parse.urlencode({"query": q}))["data"]["result"]
        return float(r[0]["value"][1]) if r else 0.0
    except Exception:
        return None



def ownership(restore: bool, force_release: bool = False) -> dict:
    from flexascale.lab.procctl import _ownership

    return _ownership(str(ROOT / "config" / "lab.yaml"), force_release=force_release, restore=restore)


def print_ownership(result: dict) -> None:
    for name, info in result["apps"].items():
        if not info.get("present"):
            print(f"  {name:<10} namespace {info['namespace']} not deployed")
            continue
        frozen = info["frozen_hpas"]
        print(f"  {name:<10} {info['namespace']}: {len(info['managed_services'])} managed services, "
              f"lease {info['lease_holder'] or 'free'}, frozen HPAs: {', '.join(frozen) if frozen else 'none'}"
              + (f", restored: {', '.join(info['restored_hpas'])}" if info["restored_hpas"] else ""))


def policy_model() -> str:
    from flexascale.config.app_policy import AppPolicy

    return AppPolicy.load(str(ROOT / "config" / "apps" / "shopping.yaml")).model_path


# ------------------------------------------------------------------ commands


def cmd_start(mode: str) -> int:
    t0 = time.time()
    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    prof = profile()
    app_ns = app_namespace()
    print(f"{C_B}FlexaScale startup ({mode}){C_0}  profile={prof}  repo={ROOT}")

    step("1/8 Tools")
    for tool in ("docker", "minikube", "kubectl"):
        ok(tool) if shutil.which(tool) else die(f"{tool} not found on PATH", "install it (RUNNING.md section A/C)")
    ok("helm") if shutil.which("helm") else warn("helm not found (only needed for installation)")
    # Two processes: locust monkey-patches ssl (gevent), which recurses if ssl is already imported.
    if all(run([PY, "-c", f"import {m}"], timeout=60).returncode == 0 for m in ("flexascale.lab.server", "locust")):
        ok(f"Python environment ({PY}) with flexascale and locust")
    else:
        die("flexascale or locust not importable", "pip install -r requirements.txt && pip install -e .")

    step("2/8 Docker and Minikube")
    if run(["docker", "info"], timeout=30).returncode != 0:
        die("Docker is not running", "start Docker (Docker Desktop on Windows/macOS) and re-run")
    ok("Docker daemon reachable")
    if f'"Name":"{prof}"' not in run(["minikube", "profile", "list", "-o", "json"], timeout=60).stdout.replace(" ", ""):
        die(f"Minikube profile '{prof}' does not exist", "full installation is separate: RUNNING.md sections C-E")
    state = run(["minikube", "status", "-p", prof, "--format", "{{.Host}}/{{.APIServer}}"], timeout=60).stdout.strip()
    if state != "Running/Running":
        if mode == "check":
            die(f"Minikube profile '{prof}' is not running ({state or 'stopped'})", "fsctl start (without --check) starts it")
        warn(f"Minikube profile '{prof}' is {state or 'stopped'}; starting the existing profile (2-4 min)...")
        with (RUNTIME / "logs" / "minikube-start.log").open("w", encoding="utf-8") as fh:
            if subprocess.run(["minikube", "start", "-p", prof], stdout=fh, stderr=subprocess.STDOUT).returncode != 0:
                die("minikube start failed", f"see .runtime/logs/minikube-start.log; try: minikube start -p {prof}")
    ok(f"Minikube profile '{prof}' running")
    ctx = run(["kubectl", "config", "current-context"]).stdout.strip()
    if ctx != prof:
        if mode == "check":
            warn(f"kubectl context is '{ctx}', not '{prof}' (run without --check to switch)")
        else:
            run(["kubectl", "config", "use-context", prof])
            warn(f"switched kubectl context from '{ctx}' to '{prof}'")
    if run(["kubectl", "get", "--raw", "/readyz"]).returncode != 0:
        die("Kubernetes API not reachable", f"minikube status -p {prof}")
    ok("Kubernetes API ready")

    step("3/8 Namespaces and workloads")
    for ns in (app_ns, MON_NS):
        ok(f"namespace {ns}") if run(["kubectl", "get", "ns", ns]).returncode == 0 else \
            die(f"namespace {ns} missing", "install the stack first (RUNNING.md sections D-F)")
    failed = False
    deploys = run(["kubectl", "-n", app_ns, "get", "deploy", "-o", "jsonpath={.items[*].metadata.name}"]).stdout.split()
    for d in deploys:
        if run(["kubectl", "-n", app_ns, "rollout", "status", f"deploy/{d}", "--timeout=180s"], timeout=200).returncode == 0:
            ok(f"{app_ns}/{d} ready")
        else:
            err(f"{app_ns}/{d} not ready after 180 s")
            failed = True
    for w in (f"deploy/{GRAFANA_SVC}", "deploy/monitoring-kube-state-metrics", f"statefulset/prometheus-{PROM_SVC}"):
        if run(["kubectl", "-n", MON_NS, "rollout", "status", w, "--timeout=180s"], timeout=200).returncode == 0:
            ok(f"{MON_NS}/{w.split('/')[1]} ready")
        else:
            err(f"{MON_NS}/{w.split('/')[1]} not ready after 180 s")
            failed = True
    if failed:
        die("some pods are not ready", "kubectl get pods -A | findstr /v Running  (or grep -v Running); kubectl -n <ns> describe pod <pod>")
    bookstore = run(["kubectl", "get", "ns", "flexascale-bookstore"]).returncode == 0

    step("4/8 Shopping application (ingress)")
    url = ingress_url()
    if url is None and mode != "check":
        warn("the Minikube IP is not reachable from this host (Docker driver on Windows/macOS); starting `minikube tunnel`")
        start_managed("tunnel", 80, "http://127.0.0.1/", ["minikube", "tunnel", "-p", prof], marker="tunnel", wait_s=60)
        url = ingress_url()
    if url is None:
        die("the shop's ingress is not reachable from this host",
            f"Linux: check `minikube ip -p {prof}`; Windows/macOS: fsctl start (runs minikube tunnel)")
    shop = url + "/"
    ok(f"storefront {shop}") if wait_for(lambda: http_ok(shop, 5), 60, 3) else \
        die(f"storefront not reachable at {shop}", f"kubectl -n ingress-nginx get pods; kubectl -n {app_ns} get ingress")
    ok("API gateway -> catalog via ingress") if http_ok(f"{url}/api/products?limit=1", 8) else \
        die(f"API not reachable at {url}/api/products", f"kubectl -n {app_ns} logs deploy/api-gateway --tail=50")

    if mode == "check":
        step("5/8 Monitoring and model (check only)")
        ok("Prometheus service present") if run(["kubectl", "-n", MON_NS, "get", "svc", PROM_SVC]).returncode == 0 else err("Prometheus service missing")
        model = policy_model()
        ok(f"trained model {model}") if (ROOT / model).is_file() else err(f"model missing: {model}")
        print(f"\n{C_OK}Preflight passed{C_0} in {time.time() - t0:.0f} s. Nothing was started or changed.")
        return 0

    step("5/8 Port-forwards (Prometheus, Grafana)")
    port_forward("pf-prometheus", MON_NS, f"svc/{PROM_SVC}", f"{PROM_PORT}:9090", f"http://localhost:{PROM_PORT}/-/ready")
    port_forward("pf-grafana", MON_NS, f"svc/{GRAFANA_SVC}", f"{GRAFANA_PORT}:80", f"http://localhost:{GRAFANA_PORT}/api/health")
    if bookstore:
        port_forward("pf-bookstore", "flexascale-bookstore", "svc/storefront", f"{BOOKSTORE_PORT}:8080", f"http://localhost:{BOOKSTORE_PORT}/healthz")

    step("6/8 Prometheus targets and metrics")
    up = prom_query(f'count(up{{namespace="{app_ns}"}} == 1)') or 0
    ok(f"{up:.0f} application scrape targets up") if up >= 7 else warn(f"only {up:.0f} application scrape targets up (expected >= 7); metrics may lag after a restart")
    ksm = prom_query(f'count(kube_deployment_spec_replicas{{namespace="{app_ns}"}})') or 0
    ok("kube-state-metrics series present") if ksm >= 1 else warn("kube-state-metrics series missing")

    step("7/8 FlexaScale prerequisites and controller ownership")
    model = policy_model()
    ok(f"trained PPO+GNN model: {model}") if (ROOT / model).is_file() else err(f"policy model missing: {model} (FlexaScale live runs will be refused)")
    if run([PY, str(ROOT / "scripts" / "run_operator.py"), "--policy", str(ROOT / "config/apps/shopping.yaml"), "--validate-only"], timeout=120).returncode == 0:
        ok("shopping policy valid (mode: observe by default)")
    else:
        err("config/apps/shopping.yaml invalid")
    own = ownership(restore=True)
    (RUNTIME / "logs" / "ownership.json").write_text(json.dumps(own, indent=2), encoding="utf-8")
    if own["safe"]:
        ok("native HPA owns all managed Deployments; no FlexaScale lease held")
    else:
        print_ownership(own)
        die("controller-ownership problem", "fsctl stop  (restores HPAs; add --force-release-lease if a dead controller still holds the lease)")
    ready = run(["kubectl", "-n", "flexascale-system", "get", "deploy", "flexascale-operator", "-o", "jsonpath={.status.readyReplicas}"]).stdout.strip()
    if ready and ready != "0":
        warn("an in-cluster FlexaScale operator is running in flexascale-system; make sure its policy mode is 'observe'")

    step("8/8 FlexaScale control center (dashboard)")
    start_managed("lab", LAB_PORT, f"http://127.0.0.1:{LAB_PORT}/api/lab/health",
                  [PY, str(ROOT / "scripts" / "run_lab.py"), "--host", "127.0.0.1", "--port", str(LAB_PORT),
                   "--config", str(ROOT / "config" / "lab.yaml"), "--runtime-dir", str(RUNTIME)],
                  marker="run_lab.py", wait_s=60)
    ok("dashboard UI served") if (ROOT / "src/flexascale/lab/static/index.html").is_file() and http_ok(f"http://127.0.0.1:{LAB_PORT}/", 5) \
        else warn("dashboard API is up but the UI bundle is missing (cd dashboard && npm ci && npm run build)")

    urls = {"DASHBOARD_URL": f"http://127.0.0.1:{LAB_PORT}/", "SHOP_URL": shop,
            "PROMETHEUS_URL": f"http://localhost:{PROM_PORT}/", "GRAFANA_URL": f"http://localhost:{GRAFANA_PORT}/"}
    (RUNTIME / "urls.env").write_text("".join(f"{k}={v}\n" for k, v in urls.items()), encoding="utf-8")
    print(f"\n{C_B}{C_OK}READY{C_0}{C_B} in {time.time() - t0:.0f} s{C_0}")
    print(f"  Control center : {C_B}{urls['DASHBOARD_URL']}{C_0}")
    print(f"  Shop           : {C_B}{shop}{C_0}   (demo login: demo@flexascale.io / CustomerPass123!)")
    print(f"  Prometheus     : {urls['PROMETHEUS_URL']}")
    print(f"  Grafana        : {urls['GRAFANA_URL']}")
    if bookstore:
        print(f"  Bookstore      : http://localhost:{BOOKSTORE_PORT}/")
    print("  Status         : fsctl status        Stop safely: fsctl stop")
    if mode == "demo":
        print(f"\n{C_B}Demo sequence{C_0} (docs/FINAL_DEMO_RUNBOOK.md)\n"
              "  1. Overview: cluster, services, live telemetry.  2. Live lab: Native HPA, a scenario, 300 s -> Start.\n"
              "  3. Same scenario with FlexaScale, then Auto.      4. Watch the Live Autoscaling Timeline.\n"
              "  5. Comparison and Experiments pages.             6. fsctl stop when finished.")
    return 0


def cmd_stop(force_release: bool) -> int:
    print(f"{C_B}FlexaScale shutdown{C_0}")
    procs = pm()
    step("1/4 Active experiment")
    base = f"http://127.0.0.1:{LAB_PORT}/api/lab"
    if procs.is_running("lab") and http_ok(f"{base}/health", 3):
        try:
            http_json(f"{base}/experiments/stop", method="POST")
            ok("stop requested for the running experiment")
        except Exception:
            ok("no experiment running")
        state = "none"
        for _ in range(60):
            try:
                active = http_json(f"{base}/experiments/active").get("active")
                state = active["state"] if active else "none"
            except Exception:
                state = "unknown"
            if state in ("none", "completed", "stopped", "failed", "interrupted", "unknown"):
                break
            time.sleep(2)
        ok(f"experiment state: {state}")
    else:
        ok("dashboard not running (nothing to stop)")

    step("2/4 Managed processes (Locust, operator, dashboard, tunnel, port-forwards)")
    names = [p["name"] for p in procs.list()]
    ordered = [n for n in STOP_ORDER if n in names] + [n for n in names if n not in STOP_ORDER]
    if not ordered:
        print("  no managed processes")
    for name in ordered:
        print(f"  {name}: {procs.stop(name, timeout=30, first_signal=15 if name in ('operator', 'lab') else 2)}")

    step("3/4 Restore native HPA ownership")
    rc = 0
    if run(["kubectl", "get", "--raw", "/readyz"]).returncode == 0:
        own = ownership(restore=True, force_release=force_release)
        print_ownership(own)
        if own["safe"]:
            ok("native HPA owns every managed Deployment; FlexaScale holds no lease")
        else:
            err("ownership not fully restored (see above)")
            print("         A live lease means another controller is running (e.g. the in-cluster operator):\n"
                  "           kubectl -n flexascale-system scale deploy/flexascale-operator --replicas=0\n"
                  "         or, if that controller is dead: fsctl stop --force-release-lease")
            rc = 1
    else:
        warn("Kubernetes API not reachable; HPA state not verified (Minikube stopped?)")
        rc = 1

    step("4/4 Summary")
    left = [p for p in procs.list() if p["running"]]
    print("  managed processes still running: " + (", ".join(p["name"] for p in left) if left else "none"))
    ok("Minikube, Deployments, Helm releases, volumes and database data were left untouched")
    return rc


def cmd_status() -> int:
    prof = profile()
    app_ns = app_namespace()
    print(f"{C_B}FlexaScale status{C_0}  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    step("Minikube")
    st = run(["minikube", "status", "-p", prof, "--format", "host={{.Host}} apiserver={{.APIServer}}"], timeout=60).stdout.strip()
    if "apiserver=Running" not in st:
        err(f"profile {prof}: {st or 'not running'}  (fsctl start)")
        return 1
    ok(f"profile {prof}: {st}")
    step("Pods")
    for ns in (app_ns, MON_NS, "flexascale-bookstore"):
        out = run(["kubectl", "-n", ns, "get", "pods", "--no-headers"]).stdout.splitlines()
        if not out:
            continue
        ready = sum(1 for line in out if line.split()[1].split("/")[0] == line.split()[1].split("/")[1] and "Running" in line)
        (ok if ready == len(out) else warn)(f"{ns}: {ready}/{len(out)} pods ready")
    step("Shopping application")
    url = ingress_url()
    if url and http_ok(url + "/", 5):
        ok(f"storefront {url}/")
        ok("API via ingress") if http_ok(f"{url}/api/products?limit=1", 8) else err("API via ingress unreachable")
    else:
        err("storefront unreachable from this host (fsctl start sets up access)")
    step("Monitoring")
    ok(f"Prometheus http://localhost:{PROM_PORT}/") if http_ok(f"http://localhost:{PROM_PORT}/-/ready") else warn("Prometheus port-forward not up")
    ok(f"Grafana http://localhost:{GRAFANA_PORT}/") if http_ok(f"http://localhost:{GRAFANA_PORT}/api/health") else warn("Grafana port-forward not up")
    step("Controller ownership")
    own = ownership(restore=False)
    print_ownership(own)
    (ok if own["safe"] else warn)("native HPA owns scaling" if own["safe"] else "FlexaScale lease held or HPAs frozen (expected only during a FlexaScale/Auto run)")
    step("Model and dashboard")
    model = policy_model()
    ok(f"model {model}") if (ROOT / model).is_file() else err(f"model {model} missing")
    ok(f"dashboard http://127.0.0.1:{LAB_PORT}/") if http_ok(f"http://127.0.0.1:{LAB_PORT}/api/lab/health") else warn("dashboard not running (fsctl start)")
    step("Managed processes")
    procs = pm().list()
    for p in procs:
        print(f"  {p['name']:<14} pid={p['pid']:<8} {'running' if p['running'] else 'NOT running (stale record)'}")
    if not procs:
        print("  no managed processes")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="fsctl", description="FlexaScale review/demo launcher")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="preflight, port-forwards, ingress access and the dashboard")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--demo", action="store_true", help="also print the demo sequence")
    g.add_argument("--check", action="store_true", help="preflight only: start nothing, change nothing")
    t = sub.add_parser("stop", help="stop managed processes and restore native HPA ownership")
    t.add_argument("--force-release-lease", action="store_true")
    sub.add_parser("status", help="read-only health report")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    try:
        if args.cmd == "start":
            return cmd_start("check" if args.check else "demo" if args.demo else "review")
        if args.cmd == "stop":
            return cmd_stop(args.force_release_lease)
        return cmd_status()
    except Abort:
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
