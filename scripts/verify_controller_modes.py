"""
End-to-end verification of the three controller modes on the live cluster (results/verification/).

Every scenario is an ordinary Live-lab experiment started through the lab's HTTP API (the same path as the
dashboard's Start button). Faults are injected from outside, the way they would happen in reality:

    hpa            native HPA owns scaling; FlexaScale runs in shadow mode (proposals logged, never applied)
    flexascale     the v9 GNN+PPO policy owns every service through the safety layer
    auto           Auto mode with the default policy
    auto_sla       Auto mode with the controlled SLA-risk variant (config/apps/shopping_verify_sla.yaml)
    auto_outage    Auto mode; the Prometheus port-forward is stopped for OUTAGE_S seconds mid-run (telemetry unavailable)
    auto_crash     Auto mode; the operator process is killed with SIGKILL mid-run (FlexaScale unhealthy)
    flexascale_v7  FlexaScale with the v7 model (fitted to this laptop), so the policy's own scale changes are applied
    flexascale_v7_25u  the same at 25 users (the evaluations' load)
    auto_v7        Auto mode with the v7 model

After each run the evidence is taken from the run's own files (decisions.jsonl = what the operator decided and
applied; run.json samples = what Kubernetes reported every 5 s) plus kubectl snapshots, and written to
results/verification/<scenario>.json. ``--report`` (also run at the end) rebuilds results/verification/README.md.

    python scripts/verify_controller_modes.py [--scenarios hpa,flexascale,...] [--users 40] [--duration 300]
    python scripts/verify_controller_modes.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "verification"
LAB = os.environ.get("FLEXASCALE_LAB_URL", "http://127.0.0.1:8090")
PY = sys.executable
NS = "flexascale-apps"
FAULT_AT_S = 100
OUTAGE_S = 60

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "hpa": {"controller": "hpa", "title": "Native HPA (FlexaScale in shadow mode)"},
    "flexascale": {"controller": "flexascale", "title": "FlexaScale (v9 GNN + PPO) owns every service"},
    "auto": {"controller": "auto", "title": "Auto mode, default policy"},
    "auto_sla": {"controller": "auto", "variant": "verify_sla_risk",
                 "title": "Auto mode, controlled SLA-risk configuration (CPU risk 60%)"},
    "auto_outage": {"controller": "auto", "fault": "telemetry_outage",
                    "title": f"Auto mode, Prometheus unavailable for {OUTAGE_S} s from +{FAULT_AT_S} s"},
    "auto_crash": {"controller": "auto", "fault": "operator_kill",
                   "title": f"Auto mode, FlexaScale operator killed (SIGKILL) at +{FAULT_AT_S} s"},
    # v7 = the graph policy trained in the twin fitted to THIS laptop (v9's twin was fitted to the second laptop and
    # holds every service at 40 users here, so its runs above contain no FlexaScale scale changes).
    "flexascale_v7": {"controller": "flexascale", "variant": "v7", "title": "FlexaScale (v7 GNN + PPO, this laptop's model) owns every service"},
    "auto_v7": {"controller": "auto", "variant": "v7", "title": "Auto mode with the v7 policy (this laptop's model)"},
    # 25 users: the evaluations' load. At 40 users order-service is latency-bound (event loop), not CPU-bound, and
    # both learned policies hold; at 25 users the flash-sale spike pushes CPU past v7's scale-up point.
    "flexascale_v7_25u": {"controller": "flexascale", "variant": "v7", "users": 25,
                          "title": "FlexaScale (v7) owns every service, 25 users"},
}


# ------------------------------------------------------------------ lab API and cluster


def api(path: str, body: Optional[dict] = None, timeout: float = 30) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(LAB + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def kubectl_json(*args: str) -> Any:
    out = subprocess.run(["kubectl", *args, "-o", "json"], capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout) if out.returncode == 0 else {"error": out.stderr.strip()}


def cluster_snapshot(label: str) -> Dict[str, Any]:
    """Deployments (spec / ready replicas) and HPAs (bounds, FlexaScale freeze annotations) right now."""
    deps = kubectl_json("-n", NS, "get", "deployments")
    hpas = kubectl_json("-n", NS, "get", "hpa")
    lease = kubectl_json("-n", NS, "get", "lease", "flexascale-shopping")
    return {
        "label": label, "t": time.time(),
        "deployments": {d["metadata"]["name"]: {"spec": d["spec"].get("replicas"), "ready": d["status"].get("readyReplicas", 0)}
                        for d in deps.get("items", [])},
        "hpas": {h["metadata"]["name"]: {"min": h["spec"].get("minReplicas"), "max": h["spec"]["maxReplicas"],
                                         "desired": (h.get("status") or {}).get("desiredReplicas"),
                                         "flexascale_annotations": sorted(k for k in (h["metadata"].get("annotations") or {})
                                                                          if "flexascale" in k)}
                 for h in hpas.get("items", [])},
        "lease_holder": ((lease.get("spec") or {}).get("holderIdentity")) if "error" not in lease else None,
    }


def wait_idle() -> None:
    while True:
        a = api("/api/lab/experiments/active").get("active")
        if a is None or a["state"] in ("completed", "stopped", "failed", "interrupted"):
            return
        time.sleep(10)


def procctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "flexascale.lab.procctl", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def prometheus_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:9090/-/ready", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def inject(fault: str, log: List[Dict[str, Any]]) -> None:
    if fault == "telemetry_outage":
        log.append({"t": time.time(), "action": "stop Prometheus port-forward", "result": procctl("stop", "pf-prometheus").stdout.strip()})
        log.append({"t": time.time(), "action": "check", "prometheus_reachable": prometheus_up()})
        log.append({"t": time.time(), **cluster_snapshot("outage start")})
        time.sleep(OUTAGE_S)
        log.append({"t": time.time(), **cluster_snapshot("outage end (before restore)")})
        cmd = [PY, "-m", "flexascale.lab.portforward", "flexascale-monitoring", "svc/monitoring-kube-prometheus-prometheus", "9090:9090"]
        res = procctl("start", "--marker", "flexascale.lab.portforward", "--log", str(ROOT / ".runtime/logs/pf-prometheus.log"),
                      "pf-prometheus", "--", *cmd)
        for _ in range(30):
            if prometheus_up():
                break
            time.sleep(1)
        log.append({"t": time.time(), "action": "restart Prometheus port-forward", "result": (res.stdout or res.stderr).strip()[-300:],
                    "prometheus_reachable": prometheus_up()})
    elif fault == "operator_kill":
        rec = json.loads((ROOT / ".runtime/pids/operator.json").read_text(encoding="utf-8"))
        log.append({"t": time.time(), **cluster_snapshot("before kill")})
        os.killpg(int(rec["pgid"]), signal.SIGKILL)
        log.append({"t": time.time(), "action": f"SIGKILL operator process group {rec['pgid']} (no graceful hand-back possible)"})
        time.sleep(3)
        log.append({"t": time.time(), **cluster_snapshot("3 s after kill (before the watchdog's next check)")})
        time.sleep(30)
        log.append({"t": time.time(), **cluster_snapshot("33 s after kill")})


def run_scenario(name: str, users: int, duration: int) -> Dict[str, Any]:
    spec = SCENARIOS[name]
    wait_idle()
    before = cluster_snapshot("before run")
    users = spec.get("users", users)
    body = {"app": "shopping", "controller": spec["controller"], "scenario": "flash_sale", "users": users,
            "spawn_rate": 5, "duration": duration, "reset_replicas": True, "shadow": True,
            "policy_variant": spec.get("variant"), "block": f"verify-{name}"}
    started = api("/api/lab/experiments", body)
    run_id = started["id"]
    print(f"[{time.strftime('%H:%M:%S')}] {name}: started {run_id}", flush=True)
    faults: List[Dict[str, Any]] = []
    mid: List[Dict[str, Any]] = []
    fault_done = False
    while True:
        a = api("/api/lab/experiments/active?samples_from=1000000&events_from=1000000").get("active") or {}
        if a.get("state") in ("completed", "stopped", "failed", "interrupted"):
            break
        if a.get("state") == "running" and a.get("started_at"):
            el = time.time() - a["started_at"]
            if not mid and el > 0.6 * duration:
                mid.append(cluster_snapshot(f"mid-run (+{el:.0f} s)"))
            if spec.get("fault") and not fault_done and el >= FAULT_AT_S:
                fault_done = True
                print(f"[{time.strftime('%H:%M:%S')}] {name}: injecting {spec['fault']} at +{el:.0f} s", flush=True)
                faults.append({"t": time.time(), "elapsed": round(el, 1), "fault": spec["fault"]})
                inject(spec["fault"], faults)
        time.sleep(5)
    after = cluster_snapshot("after cleanup")
    ev = evidence(run_id)
    ev.update({"scenario": name, "title": spec["title"], "request": body, "faults": faults,
               "snapshots": [before, *mid, after]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")
    print(f"[{time.strftime('%H:%M:%S')}] {name}: {ev['run']['state']}, cleanup safe={ev['run']['cleanup_safe']}, "
          f"applied={ev['totals']['applied']}", flush=True)
    return ev


# ------------------------------------------------------------------ evidence


def owner_of(decision: Dict[str, Any]) -> str:
    """Who actually controlled the service in this step. Observe (shadow) decisions control nothing."""
    return decision.get("controller") if decision.get("mode") == "live" else "native HPA (FlexaScale shadow only)"


def evidence(run_id: str) -> Dict[str, Any]:
    d = ROOT / "reports" / "experiments" / run_id
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    decisions, events = [], []
    if (d / "decisions.jsonl").is_file():
        for line in (d / "decisions.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            (decisions if rec.get("type") == "decision" else events).append(rec)
    live = [x for x in decisions if x.get("mode") == "live"]
    samples = run.get("samples") or []
    t0 = run.get("started_at") or (samples[0]["t"] if samples else 0)
    per: Dict[str, Dict[str, Any]] = {}
    for svc in sorted({x["service"] for x in decisions} | {n for s in samples for n in s.get("services", {})}):
        mine = [x for x in decisions if x.get("service") == svc]
        owners = Counter(owner_of(x) for x in mine)
        rules = Counter((x.get("auto") or {}).get("rule") for x in mine if x.get("auto"))
        reasons = Counter(r for x in mine for r in x.get("safety_reasons", []))
        applied = []
        for x in mine:
            if not x.get("applied"):
                continue
            target = x["proposed_replicas"]
            after = [s for s in samples if s["t"] >= x["ts"] and svc in s["services"]]
            desired_at = next((s for s in after if s["services"][svc]["desired"] == target), None)
            ready_at = next((s for s in after if s["services"][svc]["ready"] == target
                             and s["services"][svc]["desired"] == target), None)
            applied.append({
                "elapsed": round(x["ts"] - t0, 1), "from": x["current_replicas"], "policy_proposed": x.get("policy_replicas"),
                "approved": target, "policy_mode": x["policy"]["mode"], "action": x["policy"]["action_label"],
                "confidence": x["policy"]["confidence"], "hpa_note": x.get("hpa_note"),
                "auto_rule": (x.get("auto") or {}).get("rule"), "safety_reasons": x.get("safety_reasons"),
                "desired_confirmed_after_s": round(desired_at["t"] - x["ts"], 1) if desired_at else None,
                "ready_confirmed_after_s": round(ready_at["t"] - x["ts"], 1) if ready_at else None,
            })
        series = [s["services"][svc] for s in samples if svc in s.get("services", {})]
        last = mine[-1] if mine else {}
        per[svc] = {
            "owner_steps": dict(owners), "auto_rules": dict(rules), "safety_reasons": dict(reasons),
            "policy_modes": sorted({x["policy"]["mode"] for x in mine}),
            "applied": applied,
            "proposal_changes": sum(1 for x in mine if x.get("policy_replicas") not in (None, x.get("current_replicas"))),
            "desired_min": min((s["desired"] for s in series), default=None),
            "desired_max": max((s["desired"] for s in series), default=None),
            "ready_max": max((s["ready"] for s in series), default=None),
            "frozen_samples": sum(1 for s in series if s.get("frozen")),
            "hpa_desired_max": max((s.get("hpa_desired") or 0 for s in series), default=None),
            "last_decision": {k: last.get(k) for k in ("controller", "current_replicas", "policy_replicas", "proposed_replicas",
                                                          "ready_replicas", "applied", "safety_reasons", "auto")} if last else None,
        }
    # Exclusivity: FlexaScale only scales a service it owns, after freezing that service's HPA.
    violations = [f"{x['service']} applied while owner={x.get('controller')}" for x in live
                  if x.get("applied") and x.get("controller") != "flexascale"]
    violations += [f"{x['service']} applied without an HPA freeze note" for x in live
                   if x.get("applied") and x.get("hpa") and not x.get("hpa_note")]
    # A frozen HPA in a sample while the operator is not running would mean a hand-back failed.
    fb = run.get("operator_failure")
    if fb:
        stuck = [n for s in samples if s["t"] > fb["ts"] + 15 for n, v in s["services"].items() if v.get("frozen")]
        if stuck:
            violations.append(f"HPAs still frozen >15 s after the fallback: {sorted(set(stuck))}")
    summ = run.get("summary") or {}
    return {
        "run": {"id": run_id, "state": run["state"], "controller": run["request"]["controller"],
                "policy_variant": run["request"].get("policy_variant"), "users": run["request"]["users"],
                "duration": run["request"]["duration"], "model": (run.get("model") or {}).get("model_path"),
                "model_sha256": (run.get("model") or {}).get("sha256"),
                "cleanup_safe": (run.get("cleanup") or {}).get("safe"), "cleanup": run.get("cleanup"),
                "operator_failure": fb, "workload": summ.get("workload"), "replicas": summ.get("replicas"),
                "resources": {k: (summ.get("resources") or {}).get(k) for k in ("replica_hours", "estimated_cost")}},
        "totals": {"decisions": len(decisions), "live_decisions": len(live),
                   "applied": sum(1 for x in decisions if x.get("applied")),
                   "apply_errors": Counter(x.get("apply_error") for x in decisions if x.get("apply_error")),
                   "owner_steps": dict(Counter(owner_of(x) for x in decisions)),
                   "auto_rules": dict(Counter((x.get("auto") or {}).get("rule") for x in decisions if x.get("auto"))),
                   "policy_modes": sorted({x["policy"]["mode"] for x in decisions})},
        "operator_events": [{k: e.get(k) for k in ("event", "result", "reason", "restored_hpas", "lease_identity", "ts")} for e in events],
        "lab_events": [{k: e.get(k) for k in ("elapsed", "kind", "message")} for e in run.get("events", [])
                       if e.get("kind") in ("ownership", "auto", "scale_request", "fallback", "safety", "replicas", "ready", "warning", "error")],
        "per_service": per,
        "exclusivity_violations": violations,
    }


# ------------------------------------------------------------------ report


def owner_label(steps: Dict[str, int]) -> str:
    parts = [f"{'FlexaScale' if k == 'flexascale' else 'HPA' if k == 'hpa' else 'no HPA (fixed)' if k == 'none' else k} {v}" for k, v in sorted(steps.items(), key=lambda kv: -kv[1])]
    return ", ".join(parts) or "—"


def scenario_table(ev: Dict[str, Any]) -> List[str]:
    rows = ["| Service | Selected owner (operator steps) | Decision reason (rule: steps) | Policy invoked | Action applied (approved, confirmed by Kubernetes) | Actual replicas (desired min–max / ready max) |",
            "|---|---|---|---|---|---|"]
    for svc, p in ev["per_service"].items():
        if not p["owner_steps"]:
            continue
        rules = ", ".join(f"{k}: {v}" for k, v in p["auto_rules"].items()) or ", ".join(
            f"{k}: {v}" for k, v in sorted(p["safety_reasons"].items(), key=lambda kv: -kv[1])[:2])
        acts = "; ".join(f"+{a['elapsed']:.0f}s {a['from']}→{a['approved']} (desired {a['desired_confirmed_after_s']} s, ready {a['ready_confirmed_after_s']} s)"
                         for a in p["applied"][:4])
        if len(p["applied"]) > 4:
            acts += f"; … {len(p['applied'])} in total"
        rows.append(f"| {svc} | {owner_label(p['owner_steps'])} | {rules or '—'} | {', '.join(p['policy_modes'])} | {acts or 'none'} | "
                    f"{p['desired_min']}–{p['desired_max']} / {p['ready_max']} |")
    return rows


def mixed_steps(run_id: str) -> tuple[int, int, Dict[str, str]]:
    """Operator steps in which some services were owned by FlexaScale and others by HPA at the same time."""
    by_step: Dict[int, Dict[str, str]] = defaultdict(dict)
    path = ROOT / "reports" / "experiments" / run_id / "decisions.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        d = json.loads(line)
        if d.get("type") == "decision" and d.get("mode") == "live":
            by_step[d["step"]][d["service"]] = d["controller"]
    mixed = [st for st, owners in sorted(by_step.items()) if len(set(owners.values())) > 1]
    return len(mixed), len(by_step), (by_step[mixed[len(mixed) // 2]] if mixed else {})


def key_evidence(evs: Dict[str, Dict[str, Any]]) -> List[str]:
    out = []
    for n, ev in evs.items():
        acts = sorted(((a, svc) for svc, p in ev["per_service"].items() for a in p["applied"]), key=lambda x: x[0]["elapsed"])
        if acts:
            a, svc = acts[0]
            out.append(f"* **{ev['title']}** — first applied FlexaScale action: {svc} {a['from']}→{a['approved']} at +{a['elapsed']:.0f} s "
                       f"(policy `{a['policy_mode']}` {a['action']}, confidence {a['confidence']:.2f}"
                       f"{', Auto rule ' + a['auto_rule'] if a.get('auto_rule') else ''}; safety: {', '.join(a.get('safety_reasons') or [])}; "
                       f"HPA {a['hpa_note']}); Kubernetes desired after "
                       f"{a['desired_confirmed_after_s']} s, ready after {a['ready_confirmed_after_s']} s; {len(acts)} applied in total.")
        if ev["run"]["controller"] == "auto":
            m, total, example = mixed_steps(ev["run"]["id"])
            if m:
                hpa = sorted(k for k, v in example.items() if v == "hpa")
                out.append(f"* **{ev['title']}** — mixed ownership in {m} of {total} operator steps; e.g. HPA owned {', '.join(hpa)} while "
                           f"FlexaScale owned the other {len(example) - len(hpa)} services in the same step.")
        if ev["run"].get("operator_failure"):
            of = ev["run"]["operator_failure"]
            out.append(f"* **{ev['title']}** — watchdog fallback at +{of['elapsed']} s ({of['reason']}): {len(of['restored'])} HPAs restored.")
    return out or ["* (no runs yet)"]


def build_report() -> None:
    evs = {}
    for n in SCENARIOS:
        path = OUT / f"{n}.json"
        if not path.is_file():
            continue
        ev = json.loads(path.read_text(encoding="utf-8"))
        ev.update(evidence(ev["run"]["id"]))  # always re-extracted from the raw run files
        path.write_text(json.dumps(ev, indent=2, default=str), encoding="utf-8")
        evs[n] = ev
    lines = ["# Controller-mode verification (live cluster)", "",
             f"Generated by `scripts/verify_controller_modes.py --report` on {time.strftime('%Y-%m-%d %H:%M %Z')}. "
             "Each scenario is a normal Live-lab experiment (flash-sale spike) started through the lab API; the raw run is in "
             "`reports/experiments/<run id>/` and the extracted evidence in `<scenario>.json` next to this file.", "",
             "Terms used below: **proposed** = the policy's own replica count (`policy_replicas`); **approved** = what the safety "
             "layer let through (`proposed_replicas` of a FlexaScale-owned decision); **desired** = the Deployment's "
             "`spec.replicas` as Kubernetes reports it; **ready** = `status.readyReplicas`; **owner** = the controller that "
             "actually held the service in that operator step (FlexaScale only with the Lease and a frozen HPA). A proposal is "
             "never counted as an action: *Action applied* lists only scale requests that Kubernetes accepted, with the time until "
             "the new desired and ready counts were observed.", ""]
    lines += ["## Key evidence", ""] + key_evidence(evs) + [""]
    lines += ["## Summary", "", "| Scenario | Run | State / cleanup | Policy | Operator steps by owner | Auto rules | Applied scale requests | Exclusivity |",
              "|---|---|---|---|---|---|---|---|"]
    for n, ev in evs.items():
        r, t = ev["run"], ev["totals"]
        lines.append(f"| {ev['title']} | `{r['id']}` | {r['state']} / {'safe' if r['cleanup_safe'] else 'NOT SAFE'} | "
                     f"{', '.join(t['policy_modes'])} | {owner_label(t['owner_steps'])} | "
                     f"{', '.join(f'{k} {v}' for k, v in t['auto_rules'].items()) or '—'} | {t['applied']} | "
                     f"{'no violation' if not ev['exclusivity_violations'] else '; '.join(ev['exclusivity_violations'])} |")
    for n, ev in evs.items():
        r = ev["run"]
        w = r.get("workload") or {}
        lines += ["", f"## {ev['title']}", "",
                  f"Run `{r['id']}` · controller `{r['controller']}`{' · variant `' + r['policy_variant'] + '`' if r['policy_variant'] else ''} · "
                  f"{r['users']} users, {r['duration']} s · model `{r['model']}` · cleanup {'verified safe' if r['cleanup_safe'] else 'NOT SAFE'}.",
                  f"Workload: {w.get('total_requests')} requests, {w.get('throughput_rps') and round(w['throughput_rps'], 2)} req/s, "
                  f"p50/p90/p95/p99 {w.get('p50_ms')}/{w.get('p90_ms')}/{w.get('p95_ms')}/{w.get('p99_ms')} ms, failures "
                  f"{w.get('failure_rate_pct') and round(w['failure_rate_pct'], 2)}%; peak total desired replicas "
                  f"{(r.get('replicas') or {}).get('peak_total_desired')}; replica-hours {r['resources'].get('replica_hours')}.", ""]
        if ev["faults"]:
            lines += ["Fault injection:", ""]
            for f in ev["faults"]:
                if "action" in f:
                    lines.append(f"* {time.strftime('%H:%M:%S', time.localtime(f['t']))} {f['action']}"
                                 + (f" → Prometheus reachable: {f['prometheus_reachable']}" if "prometheus_reachable" in f else ""))
                elif "label" in f:
                    frozen = sorted(n for n, h in f["hpas"].items() if h["flexascale_annotations"])
                    lines.append(f"* {time.strftime('%H:%M:%S', time.localtime(f['t']))} cluster ({f['label']}): lease holder "
                                 f"`{f['lease_holder']}`, HPAs frozen by FlexaScale: {len(frozen)}")
            if r.get("operator_failure"):
                of = r["operator_failure"]
                lines.append(f"* Lab watchdog at +{of['elapsed']} s: {of['reason']} → restored {len(of['restored'])} HPAs to native control")
            lines.append("")
        lines += scenario_table(ev)
        key = [e for e in ev["lab_events"] if e["kind"] in ("fallback", "auto", "ownership", "safety")][:14]
        if key:
            lines += ["", "Key events (lab log):", ""]
            lines += [f"* +{e['elapsed']} s [{e['kind']}] {e['message']}" if e.get("elapsed") is not None else f"* [{e['kind']}] {e['message']}" for e in key]
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'README.md'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--users", type=int, default=40)
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--report", action="store_true", help="only rebuild README.md from the saved evidence")
    args = ap.parse_args()
    if not args.report:
        for name in [s for s in args.scenarios.split(",") if s]:
            if name not in SCENARIOS:
                ap.error(f"unknown scenario {name}")
            run_scenario(name, args.users, args.duration)
    build_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
