"""
Prometheus Metrics Client for FlexaScale.

Wraps queries to Prometheus with 5-second sampling intervals to extract
live telemetry and constructs normalized, schema-compliant ServiceState objects.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List
import requests

try:
    from prometheus_api_client import PrometheusConnect
    _HAS_PROM_CLIENT = True
except ImportError:
    _HAS_PROM_CLIENT = False

from flexascale.data.schema import ServiceState, StateSource

logger = logging.getLogger(__name__)


class MetricsClient:
    """
    Client wrapper for querying live Prometheus telemetry and returning
    standardized, fully validated ServiceState instances.
    """

    def __init__(
        self,
        url: str = "http://localhost:9090",
        sampling_interval_seconds: int = 5,
        disable_ssl: bool = True,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.sampling_interval_seconds = sampling_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.prom = PrometheusConnect(url=url, disable_ssl=disable_ssl) if _HAS_PROM_CLIENT else None

    def _series_exists(self, selector: str) -> bool:
        """True when Prometheus holds at least one series for ``selector``."""
        try:
            r = requests.get(
                f"{self.url}/api/v1/query",
                params={"query": f"count({selector})"},
                timeout=self.timeout_seconds,
            )
            return r.status_code == 200 and bool(r.json().get("data", {}).get("result"))
        except Exception:
            return False

    def is_connected(self) -> bool:
        """Check if Prometheus instance is reachable."""
        try:
            r = requests.get(f"{self.url}/-/healthy", timeout=self.timeout_seconds)
            return r.status_code == 200
        except Exception:
            return False

    def _safe_query_metric(self, query: str, default: float = 0.0) -> tuple[float, bool]:
        """Execute a PromQL query and extract the float value and success status safely with timeout."""
        try:
            if self.prom is not None or requests:
                params = {"query": query}
                r = requests.get(
                    f"{self.url}/api/v1/query",
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if r.status_code == 200:
                    payload = r.json()
                    results = payload.get("data", {}).get("result", [])
                    if results and len(results) > 0 and "value" in results[0]:
                        val = results[0]["value"][1]
                        if val not in ("NaN", "Inf", "-Inf", None):
                            return float(val), True
        except Exception as exc:
            logger.debug("PromQL query failed: %s (error: %s)", query, exc)
        return default, False

    def _safe_query_value(self, query: str, default: float = 0.0) -> float:
        """Execute a PromQL query and extract the float value safely with timeout."""
        val, _ = self._safe_query_metric(query, default=default)
        return val

    def get_service_state(
        self,
        service_id: str,
        namespace: str = "flexascale-apps",
    ) -> ServiceState:
        """
        Queries Prometheus for the last telemetry window for a service.
        Calculates raw, normalized, and derived metrics and returns a validated ServiceState.

        Args:
            service_id: Service identifier (e.g. 'api-gateway', 'cart-service', etc.).
            namespace: Kubernetes namespace where microservices reside.

        Returns:
            Validated ServiceState object tagged with StateSource.LIVE and missing-telemetry tracking.
        """
        window = f"{max(60, self.sampling_interval_seconds * 3)}s"
        current_ts = int(time.time())
        missing_metrics: list[str] = []
        # Pods of Deployment <service_id> are named <service_id>-<rs-hash>-<suffix>.
        pods = f"^{service_id}-[a-z0-9]+-[a-z0-9]+$"  # DNS-1123 names need no escaping
        telemetry_status: dict[str, bool] = {}

        # 1. CPU Utilization (percentage: 0 to 100)
        # CPU as percent of the pods' CPU request (same semantics as native HPA).
        cpu_query = (
            f'100 * sum(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", '
            f'pod=~"{pods}", container!="", container!="POD"}}[{window}])) / '
            f'sum(kube_pod_container_resource_requests{{namespace="{namespace}", '
            f'pod=~"{pods}", resource="cpu"}})'
        )
        cpu_util, cpu_ok = self._safe_query_metric(cpu_query, default=0.0)
        telemetry_status["cpu_utilization"] = cpu_ok
        if not cpu_ok:
            missing_metrics.append("cpu_utilization")

        # 2. Memory Utilization (percentage: 0 to 100)
        mem_query = (
            f'avg(container_memory_working_set_bytes{{namespace="{namespace}", '
            f'pod=~"{pods}", container!=""}} / '
            f'container_spec_memory_limit_bytes{{namespace="{namespace}", '
            f'pod=~"{pods}", container!=""}}) * 100'
        )
        mem_util, mem_ok = self._safe_query_metric(mem_query, default=0.0)
        if not mem_ok or mem_util <= 0.0:
            # No memory limit: express usage relative to the memory request instead.
            raw_mem_query = (
                f'100 * sum(container_memory_working_set_bytes{{namespace="{namespace}", '
                f'pod=~"{pods}", container!="", container!="POD"}}) / '
                f'sum(kube_pod_container_resource_requests{{namespace="{namespace}", '
                f'pod=~"{pods}", resource="memory"}})'
            )
            raw_mem, raw_ok = self._safe_query_metric(raw_mem_query, default=0.0)
            if raw_ok and raw_mem > 0:
                mem_util = raw_mem
                mem_ok = True
        telemetry_status["memory_utilization"] = mem_ok
        if not mem_ok:
            missing_metrics.append("memory_utilization")

        # 3. Replica Count (healthy running pods)
        rep_query = (
            f'count(kube_pod_status_phase{{namespace="{namespace}", '
            f'pod=~"{pods}", phase="Running"}} == 1)'
        )
        replica_count_f, rep_ok = self._safe_query_metric(rep_query, default=1.0)
        replica_count = int(replica_count_f) if rep_ok else 1
        if replica_count < 1:
            replica_count = 1
        telemetry_status["replica_count"] = rep_ok
        if not rep_ok:
            missing_metrics.append("replica_count")

        # 4. Request Rate (req/s over window)
        req_query = (
            f'sum(rate(http_requests_total{{namespace="{namespace}", '
            f'pod=~"{pods}"}}[{window}]))'
        )
        req_rate, req_ok = self._safe_query_metric(req_query, default=0.0)

        # No fabricated fallback: without http_requests_total the rate is reported missing.
        if req_ok and req_rate <= 0.0:
            req_ok = self._series_exists(
                f'http_requests_total{{namespace="{namespace}", pod=~"{pods}"}}'
            )
        telemetry_status["request_rate"] = req_ok
        if not req_ok:
            missing_metrics.append("request_rate")

        # 5. Success / Error Request Rates
        succ_query = (
            f'sum(rate(http_requests_total{{namespace="{namespace}", '
            f'pod=~"{pods}", status=~"2..|3.."}}[{window}]))'
        )
        succ_rate, succ_ok = self._safe_query_metric(succ_query, default=req_rate)

        err_query = (
            f'sum(rate(http_requests_total{{namespace="{namespace}", '
            f'pod=~"{pods}", status=~"4..|5.."}}[{window}]))'
        )
        err_rate_val, err_ok = self._safe_query_metric(err_query, default=0.0)

        # 6. Latency (ms over window)
        lat_query = (
            f'avg(rate(http_request_duration_seconds_sum{{namespace="{namespace}", '
            f'pod=~"{pods}"}}[{window}]) / '
            f'rate(http_request_duration_seconds_count{{namespace="{namespace}", '
            f'pod=~"{pods}"}}[{window}])) * 1000'
        )
        latency, lat_ok = self._safe_query_metric(lat_query, default=0.0)

        # No fabricated fallback: latency without request histograms is reported missing.
        if not lat_ok or latency != latency:
            latency, lat_ok = 0.0, False
        telemetry_status["latency_ms"] = lat_ok
        if not lat_ok:
            missing_metrics.append("latency_ms")

        data: Dict[str, Any] = {
            "timestamp": current_ts,
            "service_id": service_id,
            "cpu_utilization": max(0.0, min(100.0, cpu_util)),
            "memory_utilization": max(0.0, min(100.0, mem_util)),
            "replica_count": max(1, replica_count),
            "request_rate": max(0.0, req_rate),
            "latency_ms": max(0.0, latency),
            "successful_requests": max(0.0, succ_rate),
            "failed_requests": max(0.0, err_rate_val),
            "missing_metrics": missing_metrics,
            "telemetry_status": telemetry_status,
            "source": StateSource.LIVE,
        }

        return ServiceState.from_dict(data, source=StateSource.LIVE)

    def query_inter_service_traffic(
        self,
        namespace: str = "default",
    ) -> List[tuple[str, str, float]]:
        """
        Discovers caller -> callee traffic flow rates between microservices.
        Checks API Gateway forwards, service-mesh (Istio/Envoy) or HTTP client metrics in Prometheus.
        """
        window = f"{max(60, self.sampling_interval_seconds * 3)}s"
        flows: List[tuple[str, str, float]] = []

        # 0. Router/gateway forward counters: any workload exporting
        #    gateway_forward_total{target_service=...} is treated as the caller.
        gw_query = (
            f'sum by (pod, target_service) ('
            f'rate(gateway_forward_total{{namespace="{namespace}"}}[{window}]))'
        )
        try:
            r = requests.get(
                f"{self.url}/api/v1/query",
                params={"query": gw_query},
                timeout=self.timeout_seconds,
            )
            if r.status_code == 200:
                results = r.json().get("data", {}).get("result", [])
                for item in results:
                    metric = item.get("metric", {})
                    dst = metric.get("target_service")
                    src = re.sub(r"-[a-z0-9]{5,10}-[a-z0-9]{5}$", "", metric.get("pod", ""))
                    val = float(item.get("value", [0, 0])[1])
                    if src and dst and src != dst and val > 0:
                        flows.append((src, dst, val))
        except Exception:
            pass

        # 1. Istio / Envoy service mesh metrics
        if not flows:
            istio_query = (
                f'sum by (source_workload, destination_workload) ('
                f'rate(istio_requests_total{{source_workload_namespace="{namespace}"}}[{window}]))'
            )
            try:
                r = requests.get(
                    f"{self.url}/api/v1/query",
                    params={"query": istio_query},
                    timeout=self.timeout_seconds,
                )
                if r.status_code == 200:
                    results = r.json().get("data", {}).get("result", [])
                    for item in results:
                        metric = item.get("metric", {})
                        src = metric.get("source_workload")
                        dst = metric.get("destination_workload")
                        val = float(item.get("value", [0, 0])[1])
                        if src and dst and src != dst and val > 0:
                            flows.append((src, dst, val))
            except Exception:
                pass

        # 2. HTTP client requests with client/server labels
        if not flows:
            client_query = (
                f'sum by (client, server) (rate(http_requests_total{{namespace="{namespace}"}}[{window}]))'
            )
            try:
                r = requests.get(
                    f"{self.url}/api/v1/query",
                    params={"query": client_query},
                    timeout=self.timeout_seconds,
                )
                if r.status_code == 200:
                    results = r.json().get("data", {}).get("result", [])
                    for item in results:
                        metric = item.get("metric", {})
                        src = metric.get("client")
                        dst = metric.get("server")
                        val = float(item.get("value", [0, 0])[1])
                        if src and dst and src != dst and val > 0:
                            flows.append((src, dst, val))
            except Exception:
                pass

        return flows

