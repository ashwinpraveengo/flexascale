"""
Thin, testable wrapper around ``kubectl``.

FlexaScale talks to Kubernetes through kubectl so the same code path works on a
developer laptop (kubeconfig) and inside the cluster (service-account token,
which kubectl picks up automatically). Every call has a timeout and returns a
structured result instead of raising, so control loops can fail safe.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class KubeResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""

    def json(self) -> Any:
        return json.loads(self.stdout) if self.stdout else None


Runner = Callable[[Sequence[str], Optional[str], float], KubeResult]


def _subprocess_runner(args: Sequence[str], stdin: Optional[str], timeout: float) -> KubeResult:
    try:
        res = subprocess.run(
            ["kubectl", *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return KubeResult(res.returncode == 0, res.stdout, res.stderr.strip())
    except FileNotFoundError:
        return KubeResult(False, "", "kubectl not found on PATH")
    except subprocess.TimeoutExpired:
        return KubeResult(False, "", f"kubectl timed out after {timeout:.0f}s")


class Kube:
    """kubectl facade. Inject ``runner`` in tests to avoid a real cluster."""

    def __init__(self, runner: Optional[Runner] = None, timeout: float = 10.0) -> None:
        self._runner = runner or _subprocess_runner
        self.timeout = timeout

    @staticmethod
    def available() -> bool:
        return shutil.which("kubectl") is not None

    def run(self, *args: str, stdin: Optional[str] = None, timeout: Optional[float] = None) -> KubeResult:
        return self._runner(list(args), stdin, timeout or self.timeout)

    def get_json(self, kind: str, namespace: str, name: str = "", selector: str = "") -> Optional[Any]:
        args = ["get", kind]
        if name:
            args.append(name)
        args += ["-n", namespace, "-o", "json"]
        if selector:
            args += ["-l", selector]
        res = self.run(*args)
        if not res.ok:
            logger.debug("kubectl get %s %s failed: %s", kind, name, res.stderr)
            return None
        try:
            return res.json()
        except json.JSONDecodeError:
            return None

    def list_items(self, kind: str, namespace: str, selector: str = "") -> Optional[List[Dict[str, Any]]]:
        data = self.get_json(kind, namespace, selector=selector)
        if data is None:
            return None
        return list(data.get("items", []))

    def patch(self, kind: str, name: str, namespace: str, patch: Dict[str, Any], patch_type: str = "merge") -> KubeResult:
        return self.run(
            "patch", kind, name, "-n", namespace, f"--type={patch_type}", "-p", json.dumps(patch)
        )

    def scale(self, deployment: str, namespace: str, replicas: int) -> KubeResult:
        return self.run("scale", f"deployment/{deployment}", f"--replicas={int(replicas)}", "-n", namespace)

    def apply(self, manifest: Dict[str, Any]) -> KubeResult:
        return self.run("apply", "-f", "-", stdin=json.dumps(manifest))

    def create(self, manifest: Dict[str, Any]) -> KubeResult:
        return self.run("create", "-f", "-", stdin=json.dumps(manifest))

    def replace(self, manifest: Dict[str, Any]) -> KubeResult:
        """Replace honours metadata.resourceVersion, giving optimistic concurrency."""
        return self.run("replace", "-f", "-", stdin=json.dumps(manifest))


def parse_cpu(quantity: Optional[str]) -> float:
    """Kubernetes CPU quantity -> cores."""
    if not quantity:
        return 0.0
    q = str(quantity)
    if q.endswith("m"):
        return float(q[:-1]) / 1000.0
    if q.endswith("n"):
        return float(q[:-1]) / 1e9
    if q.endswith("u"):
        return float(q[:-1]) / 1e6
    return float(q)


_MEM_SUFFIX = {
    "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
    "K": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4,
    "k": 1000,
}


def parse_memory(quantity: Optional[str]) -> float:
    """Kubernetes memory quantity -> bytes."""
    if not quantity:
        return 0.0
    q = str(quantity)
    for suffix in sorted(_MEM_SUFFIX, key=len, reverse=True):
        if q.endswith(suffix):
            return float(q[: -len(suffix)]) * _MEM_SUFFIX[suffix]
    return float(q)
