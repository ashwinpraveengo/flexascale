"""
Batched, application-agnostic Prometheus telemetry for Kubernetes Deployments.

All series are fetched per pod in a handful of queries and attributed to a
Deployment only when the pod name matches ``<deployment>-<hash>-<suffix>``
exactly, so ``order`` never absorbs ``order-db`` pods.

Units match native HPA semantics:
    cpu_pct     average over pods of (CPU cores used / CPU cores requested) * 100
    memory_pct  average over pods of (working set / memory limit, or request) * 100

Metrics that are not available are reported as ``None`` and listed in
``missing``; nothing is synthesised. Application-level request metrics
(``http_requests_total`` / ``http_request_duration_seconds``) are optional:
without them FlexaScale runs in a CPU/memory-only degraded mode.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger(__name__)

POD_SUFFIX = re.compile(r"^(?P<dep>.+)-[a-z0-9]{5,10}-[a-z0-9]{5}$")
QUANTILES = (0.50, 0.95, 0.99)


@dataclass
class WorkloadMetrics:
    deployment: str
    pods: int = 0
    cpu_cores: Optional[float] = None
    cpu_pct: Optional[float] = None
    memory_bytes: Optional[float] = None
    memory_pct: Optional[float] = None
    request_rate: Optional[float] = None
    error_rate: Optional[float] = None
    latency_mean_ms: Optional[float] = None
    latency_p50_ms: Optional[float] = None
    latency_p95_ms: Optional[float] = None
    latency_p99_ms: Optional[float] = None
    sample_age_s: Optional[float] = None
    stale: bool = False
    missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 4)
        return d


def deployment_of(pod: str, deployments: Iterable[str]) -> Optional[str]:
    m = POD_SUFFIX.match(pod)
    if not m:
        return None
    dep = m.group("dep")
    return dep if dep in set(deployments) else None


def histogram_quantile(q: float, buckets: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Prometheus-style quantile from cumulative (upper_bound, count) buckets."""
    if not buckets:
        return None
    buckets = sorted(buckets, key=lambda b: b[0])
    total = buckets[-1][1]
    if total <= 0:
        return None
    rank = q * total
    prev_bound, prev_count = 0.0, 0.0
    for bound, count in buckets:
        if count >= rank:
            if bound == float("inf"):
                return prev_bound
            width = bound - prev_bound
            in_bucket = count - prev_count
            if in_bucket <= 0:
                return bound
            return prev_bound + width * (rank - prev_count) / in_bucket
        prev_bound, prev_count = bound, count
    return buckets[-1][0]


class WorkloadMetricsClient:
    def __init__(
        self,
        prometheus_url: str = "http://localhost:9090",
        window: str = "1m",
        timeout_seconds: float = 4.0,
        stale_after_seconds: float = 120.0,
    ) -> None:
        self.url = prometheus_url.rstrip("/")
        self.window = window
        self.timeout = timeout_seconds
        self.stale_after = stale_after_seconds
        self.last_error: Optional[str] = None

    def healthy(self) -> bool:
        try:
            return requests.get(f"{self.url}/-/ready", timeout=self.timeout).status_code == 200
        except Exception:
            return False

    def query(self, promql: str) -> Optional[List[Dict[str, Any]]]:
        try:
            r = requests.get(f"{self.url}/api/v1/query", params={"query": promql}, timeout=self.timeout)
            if r.status_code != 200:
                self.last_error = f"HTTP {r.status_code} for {promql[:80]}"
                return None
            body = r.json()
            if body.get("status") != "success":
                self.last_error = str(body.get("error"))
                return None
            return body.get("data", {}).get("result", [])
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def _by_pod(self, promql: str) -> Optional[Dict[str, float]]:
        res = self.query(promql)
        if res is None:
            return None
        out: Dict[str, float] = {}
        for item in res:
            pod = item.get("metric", {}).get("pod")
            try:
                val = float(item["value"][1])
            except (KeyError, ValueError, IndexError):
                continue
            if pod and val == val:  # drop NaN
                out[pod] = val
        return out

    def collect(
        self,
        namespace: str,
        deployments: Sequence[str],
        cpu_request_cores: Optional[Dict[str, float]] = None,
        memory_capacity_bytes: Optional[Dict[str, float]] = None,
    ) -> Dict[str, WorkloadMetrics]:
        """
        Args:
            cpu_request_cores: per-pod CPU request per deployment (from the Deployment spec).
                Falls back to kube-state-metrics requests when absent.
            memory_capacity_bytes: per-pod memory limit (or request) per deployment.
        """
        ns = namespace
        w = self.window
        result = {d: WorkloadMetrics(deployment=d) for d in deployments}
        if not deployments:
            return result

        cpu = self._by_pod(
            f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="{ns}",container!="",container!="POD"}}[{w}]))'
        )
        mem = self._by_pod(
            f'sum by (pod) (container_memory_working_set_bytes{{namespace="{ns}",container!="",container!="POD"}})'
        )
        age = self._by_pod(
            f'time() - max by (pod) (timestamp(container_cpu_usage_seconds_total{{namespace="{ns}",container!=""}}))'
        )
        ksm_cpu_req = self._by_pod(
            f'sum by (pod) (kube_pod_container_resource_requests{{namespace="{ns}",resource="cpu"}})'
        ) if not cpu_request_cores else None
        rps = self._by_pod(f'sum by (pod) (rate(http_requests_total{{namespace="{ns}"}}[{w}]))')
        err = self._by_pod(f'sum by (pod) (rate(http_requests_total{{namespace="{ns}",status=~"5.."}}[{w}]))')
        lat_sum = self._by_pod(f'sum by (pod) (rate(http_request_duration_seconds_sum{{namespace="{ns}"}}[{w}]))')
        lat_cnt = self._by_pod(f'sum by (pod) (rate(http_request_duration_seconds_count{{namespace="{ns}"}}[{w}]))')
        buckets_raw = self.query(
            f'sum by (pod, le) (rate(http_request_duration_seconds_bucket{{namespace="{ns}"}}[{w}]))'
        )

        def group(series: Optional[Dict[str, float]]) -> Dict[str, List[float]]:
            grouped: Dict[str, List[float]] = {}
            for pod, val in (series or {}).items():
                dep = deployment_of(pod, deployments)
                if dep:
                    grouped.setdefault(dep, []).append(val)
            return grouped

        cpu_g, mem_g, age_g = group(cpu), group(mem), group(age)
        rps_g, err_g, ls_g, lc_g = group(rps), group(err), group(lat_sum), group(lat_cnt)
        req_g = group(ksm_cpu_req)

        bucket_g: Dict[str, Dict[float, float]] = {}
        for item in buckets_raw or []:
            metric = item.get("metric", {})
            dep = deployment_of(metric.get("pod", ""), deployments)
            if not dep:
                continue
            le = metric.get("le")
            try:
                bound = float("inf") if le == "+Inf" else float(le)
                val = float(item["value"][1])
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            if val == val:
                bucket_g.setdefault(dep, {})
                bucket_g[dep][bound] = bucket_g[dep].get(bound, 0.0) + val

        for dep, m in result.items():
            pods_cpu = cpu_g.get(dep, [])
            m.pods = len(pods_cpu)
            if pods_cpu:
                m.cpu_cores = sum(pods_cpu)
                per_pod_req = (cpu_request_cores or {}).get(dep)
                if not per_pod_req and req_g.get(dep):
                    per_pod_req = sum(req_g[dep]) / len(req_g[dep])
                if per_pod_req and per_pod_req > 0:
                    m.cpu_pct = 100.0 * (m.cpu_cores / len(pods_cpu)) / per_pod_req
                else:
                    m.missing.append("cpu_request")
            else:
                m.missing.append("cpu")

            pods_mem = mem_g.get(dep, [])
            if pods_mem:
                m.memory_bytes = sum(pods_mem)
                cap = (memory_capacity_bytes or {}).get(dep)
                if cap and cap > 0:
                    m.memory_pct = 100.0 * (m.memory_bytes / len(pods_mem)) / cap
                else:
                    m.missing.append("memory_capacity")
            else:
                m.missing.append("memory")

            ages = age_g.get(dep, [])
            if ages:
                m.sample_age_s = max(ages)
                m.stale = m.sample_age_s > self.stale_after
            elif pods_cpu:
                m.sample_age_s = None
            if not pods_cpu:
                m.stale = True

            if rps_g.get(dep):
                m.request_rate = sum(rps_g[dep])
                m.error_rate = sum(err_g.get(dep, [0.0]))
            else:
                m.missing.append("request_rate")
            if lc_g.get(dep) and sum(lc_g[dep]) > 0:
                m.latency_mean_ms = 1000.0 * sum(ls_g.get(dep, [0.0])) / sum(lc_g[dep])
            else:
                m.missing.append("latency")
            if dep in bucket_g:
                pairs = list(bucket_g[dep].items())
                for q, attr in zip(QUANTILES, ("latency_p50_ms", "latency_p95_ms", "latency_p99_ms")):
                    v = histogram_quantile(q, pairs)
                    setattr(m, attr, None if v is None else v * 1000.0)
        return result

    @staticmethod
    def observation(m: WorkloadMetrics, replicas: int) -> List[float]:
        """Policy feature vector [cpu%, mem%, replicas, rps, latency_ms]; missing -> 0."""
        return [
            float(m.cpu_pct or 0.0),
            float(m.memory_pct or 0.0),
            float(max(1, replicas)),
            float(m.request_rate or 0.0),
            float(m.latency_mean_ms or 0.0),
        ]


def now() -> float:
    return time.time()
