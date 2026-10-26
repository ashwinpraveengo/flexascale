"""In-memory fakes for kubectl-backed FlexaScale components (no cluster needed)."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Sequence

from flexascale.k8s.kube import Kube, KubeResult


def deployment(name: str, replicas: int = 1, ready: Optional[int] = None, image: str = "app:1",
               cpu: str = "100m", mem_req: str = "64Mi", mem_lim: str = "128Mi",
               labels: Optional[Dict[str, str]] = None, cpu_lim: Optional[str] = None) -> Dict[str, Any]:
    limits = {"memory": mem_lim, **({"cpu": cpu_lim} if cpu_lim else {})}
    return {
        "metadata": {"name": name, "labels": labels or {"app": name}},
        "spec": {
            "replicas": replicas,
            "template": {"spec": {"containers": [{
                "name": name, "image": image,
                "resources": {"requests": {"cpu": cpu, "memory": mem_req}, "limits": limits},
            }]}},
        },
        "status": {"readyReplicas": replicas if ready is None else ready,
                   "availableReplicas": replicas if ready is None else ready},
    }


def hpa(name: str, target: str, lo: int = 1, hi: int = 10, annotations: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {
        "metadata": {"name": name, "annotations": annotations or {}},
        "spec": {"scaleTargetRef": {"kind": "Deployment", "name": target}, "minReplicas": lo, "maxReplicas": hi},
        "status": {"currentReplicas": lo, "desiredReplicas": lo},
    }


class FakeCluster:
    """Holds deployments, HPAs and leases for one namespace; records every mutation."""

    def __init__(self, namespace: str = "demo") -> None:
        self.namespace = namespace
        self.deployments: Dict[str, Dict[str, Any]] = {}
        self.hpas: Dict[str, Dict[str, Any]] = {}
        self.leases: Dict[str, Dict[str, Any]] = {}
        self.configmaps: Dict[str, Dict[str, Any]] = {}
        self.mutations: List[List[str]] = []
        self._rv = 1

    def add(self, *objs: Dict[str, Any], kind: str = "deployment") -> "FakeCluster":
        for o in objs:
            target = self.deployments if kind == "deployment" else self.hpas
            target[o["metadata"]["name"]] = copy.deepcopy(o)
        return self

    def kube(self) -> Kube:
        return Kube(runner=self.run)

    # -- kubectl emulation ------------------------------------------------

    def _store(self, kind: str) -> Dict[str, Dict[str, Any]]:
        return {"deployments": self.deployments, "deployment": self.deployments, "hpa": self.hpas,
                "lease": self.leases, "configmap": self.configmaps}[kind]

    def run(self, args: Sequence[str], stdin: Optional[str], timeout: float) -> KubeResult:
        args = list(args)
        verb = args[0]
        if verb == "get":
            kind = args[1]
            name = args[2] if len(args) > 2 and not args[2].startswith("-") else ""
            if kind == "namespace":
                return KubeResult(True, "{}")
            store = self._store(kind)
            if name:
                if name not in store:
                    return KubeResult(False, "", f'{kind} "{name}" not found')
                return KubeResult(True, json.dumps(store[name]))
            return KubeResult(True, json.dumps({"items": list(store.values())}))
        self.mutations.append(args)
        if verb == "patch":
            kind, name = args[1], args[2]
            store = self._store(kind)
            if name not in store:
                return KubeResult(False, "", "not found")
            patch = json.loads(args[args.index("-p") + 1])
            _merge(store[name], patch)
            return KubeResult(True, "patched")
        if verb == "scale":
            name = args[1].split("/", 1)[1]
            reps = int(args[2].split("=", 1)[1])
            dep = self.deployments[name]
            dep["spec"]["replicas"] = reps
            dep["status"]["readyReplicas"] = reps
            return KubeResult(True, "scaled")
        if verb in ("create", "replace", "apply"):
            obj = json.loads(stdin or "{}")
            kind = obj.get("kind", "").lower()
            store = self._store(kind)
            name = obj["metadata"]["name"]
            if verb == "create" and name in store:
                return KubeResult(False, "", "AlreadyExists")
            if verb == "replace":
                if name not in store:
                    return KubeResult(False, "", "NotFound")
                if obj["metadata"].get("resourceVersion") != store[name]["metadata"].get("resourceVersion"):
                    return KubeResult(False, "", "Conflict: the object has been modified")
            self._rv += 1
            obj["metadata"]["resourceVersion"] = str(self._rv)
            store[name] = obj
            return KubeResult(True, "ok")
        return KubeResult(False, "", f"unsupported verb {verb}")


def _merge(target: Dict[str, Any], patch: Dict[str, Any]) -> None:
    for k, v in patch.items():
        if v is None:
            target.pop(k, None)
        elif isinstance(v, dict):
            node = target.setdefault(k, {})
            if node is None:
                target[k] = node = {}
            _merge(node, v)
        else:
            target[k] = v
