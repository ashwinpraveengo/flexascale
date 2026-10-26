"""
Command-line helper used by scripts/start_review.sh, stop_review.sh and review_status.sh.

    python -m flexascale.lab.procctl start --marker TEXT [--log PATH] NAME -- CMD...
    python -m flexascale.lab.procctl stop NAME | stop-all
    python -m flexascale.lab.procctl status [--json]
    python -m flexascale.lab.procctl ownership [--json]
    python -m flexascale.lab.procctl safe-state [--force-release-lease]

Only processes recorded in .runtime/pids are ever signalled (see processes.py).
``safe-state`` restores every HPA that FlexaScale froze, in every namespace of
config/lab.yaml, and reports controller leases. It never deletes resources.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List

from flexascale.lab.processes import ProcessManager

STOP_ORDER = ["locust", "operator", "lab", "pf-bookstore", "pf-grafana", "pf-prometheus"]


def _ownership(config: str, force_release: bool = False, restore: bool = False) -> Dict[str, Any]:
    from flexascale.config.app_policy import AppPolicy
    from flexascale.config.safety_config import SafetyConfig
    from flexascale.discovery.workloads import WorkloadDiscovery
    from flexascale.k8s.kube import Kube
    from flexascale.lab.experiments import LabConfig
    from flexascale.safety.hpa_manager import HPAManager
    from flexascale.safety.lease import ControllerLease

    kube = Kube()
    cfg = LabConfig.load(config)
    out: Dict[str, Any] = {"apps": {}, "safe": True}
    for name, spec in cfg.apps.items():
        policy = AppPolicy.load(spec.policy_path)
        ns_ok = kube.run("get", "namespace", policy.namespace, timeout=5).ok
        if not ns_ok:
            out["apps"][name] = {"namespace": policy.namespace, "present": False}
            continue
        restored: List[str] = []
        if restore:
            hpa = HPAManager(SafetyConfig(namespace=policy.namespace, dry_run=False), kube=kube)
            restored = hpa.restore_all_frozen() + hpa.restore_unmanaged_replicas()
            restored += hpa.restore_all_behavior() + hpa.restore_all_metrics()  # lab per-run HPA overrides
        workloads = WorkloadDiscovery(policy, kube=kube).list_all(force_refresh=True)
        lease = ControllerLease(policy.namespace, policy.name, kube=kube)
        st = lease.status()
        released = False
        if force_release and st.holder and not st.expired:
            released = lease.force_release()
            st = lease.status()
        frozen = [w.hpa.name for w in workloads if w.hpa and w.hpa.frozen]
        lease_live = bool(st.holder and not st.expired)
        app_safe = not frozen and not lease_live
        out["safe"] = out["safe"] and app_safe
        out["apps"][name] = {
            "namespace": policy.namespace,
            "present": True,
            "managed_services": [w.name for w in workloads if w.eligible],
            "hpas": {w.name: (f"{w.hpa.name} {w.hpa.min_replicas}-{w.hpa.max_replicas}" + (" FROZEN" if w.hpa.frozen else "")) if w.hpa else None
                     for w in workloads if w.eligible},
            "frozen_hpas": frozen,
            "restored_hpas": restored,
            "lease_holder": st.holder if lease_live else None,
            "lease_force_released": released,
            "safe": app_safe,
        }
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="procctl")
    ap.add_argument("--runtime-dir", default=".runtime")
    ap.add_argument("--config", default="config/lab.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("name")
    s.add_argument("--marker", required=True)
    s.add_argument("--log", default=None)
    s.add_argument("command", nargs=argparse.REMAINDER)
    st = sub.add_parser("stop")
    st.add_argument("name")
    sub.add_parser("stop-all")
    stat = sub.add_parser("status")
    stat.add_argument("--json", action="store_true")
    run = sub.add_parser("running")
    run.add_argument("name")
    own = sub.add_parser("ownership")
    own.add_argument("--json", action="store_true")
    safe = sub.add_parser("safe-state")
    safe.add_argument("--force-release-lease", action="store_true")
    safe.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    pm = ProcessManager(args.runtime_dir)
    if args.cmd == "start":
        cmd = [c for c in args.command if c != "--"]
        if pm.is_running(args.name):
            rec = pm.get(args.name)
            print(f"reused {args.name} pid={rec.pid if rec else '?'}")
            return 0
        rec = pm.start(args.name, cmd, marker=args.marker, log_path=Path(args.log) if args.log else None)
        print(f"started {args.name} pid={rec.pid} log={rec.log}")
        return 0
    if args.cmd == "running":
        return 0 if pm.is_running(args.name) else 1
    if args.cmd == "stop":
        first = signal.SIGTERM if args.name in ("operator", "lab") else signal.SIGINT
        print(f"{args.name}: {pm.stop(args.name, timeout=30, first_signal=first)}")
        return 0
    if args.cmd == "stop-all":
        names = [p["name"] for p in pm.list()]
        ordered = [n for n in STOP_ORDER if n in names] + [n for n in names if n not in STOP_ORDER]
        if not ordered:
            print("no managed processes")
        for name in ordered:
            first = signal.SIGTERM if name in ("operator", "lab") else signal.SIGINT
            print(f"{name}: {pm.stop(name, timeout=30, first_signal=first)}")
        return 0
    if args.cmd == "status":
        procs = pm.list()
        if args.json:
            print(json.dumps(procs))
        else:
            for p in procs:
                print(f"{p['name']:<15} pid={p['pid']:<8} {'running' if p['running'] else 'NOT running (stale record)'}  log={p['log']}")
            if not procs:
                print("no managed processes")
        return 0
    if args.cmd in ("ownership", "safe-state"):
        restore = args.cmd == "safe-state"
        result = _ownership(args.config, force_release=getattr(args, "force_release_lease", False), restore=restore)
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
        else:
            for name, info in result["apps"].items():
                if not info.get("present"):
                    print(f"{name:<10} namespace {info['namespace']} not deployed")
                    continue
                print(f"{name:<10} namespace {info['namespace']}: {len(info['managed_services'])} managed services")
                for svc, hpa in info["hpas"].items():
                    print(f"           {svc:<20} {hpa or 'no HPA'}")
                if info["restored_hpas"]:
                    print(f"           restored HPAs: {', '.join(info['restored_hpas'])}")
                print(f"           lease: {info['lease_holder'] or 'free'}" + (" (force-released)" if info["lease_force_released"] else ""))
                print(f"           state: {'SAFE (native HPA owns scaling)' if info['safe'] else 'NOT SAFE'}")
        return 0 if result["safe"] else 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
