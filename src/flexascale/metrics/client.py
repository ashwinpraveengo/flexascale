"""
Prometheus Metrics Client for FlexaScale.

Wraps queries to Prometheus with 5-second sampling intervals to extract
live telemetry and constructs normalized, schema-compliant ServiceState objects.
"""

from __future__ import annotations

import time
import logging
from typing import Any, Dict
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

    def is_connected(self) -> bool:
        """Check if Prometheus instance is reachable."""
        try:
            r = requests.get(f"{self.url}/-/healthy", timeout=self.timeout_seconds)
            return r.status_code == 200
        except Exception:
            return False

    def _safe_query_value(self, query: str, default: float = 0.0) -> float:
        """Execute a PromQL query and extract the float value safely with timeout."""
        try:
            if self.prom is not None:
                # Custom query with direct requests for strict timeout enforcement
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
                            return float(val)
        except Exception as exc:
            logger.debug("PromQL query failed: %s (error: %s)", query, exc)
        return default

    def get_service_state(
        self,
        service_id: str,
        namespace: str = "flexascale-apps",
    ) -> ServiceState:
        """
        Queries Prometheus for the last 5-second window of telemetry for a service.
        Calculates raw, normalized, and derived metrics and returns a validated ServiceState.

        Args:
            service_id: Service identifier (e.g. 'frontend', 'orders', 'inventory', 'payments').
            namespace: Kubernetes namespace where microservices reside.

        Returns:
            Validated ServiceState object tagged with StateSource.LIVE.
        """
        window = f"{self.sampling_interval_seconds}s"
        current_ts = int(time.time())

        # 1. CPU Utilization (percentage: 0 to 100)
        cpu_query = (
            f'avg(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*", container!=""}}[{window}])) * 100'
        )
        cpu_util = self._safe_query_value(cpu_query, default=0.0)

        # 2. Memory Utilization (percentage: 0 to 100)
        mem_query = (
            f'avg(container_memory_working_set_bytes{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*", container!=""}} / '
            f'container_spec_memory_limit_bytes{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*", container!=""}}) * 100'
        )
        mem_util = self._safe_query_value(mem_query, default=0.0)
        if mem_util <= 0.0:
            raw_mem_query = (
                f'avg(container_memory_working_set_bytes{{namespace="{namespace}", '
                f'pod=~"^{service_id}.*", container!=""}})[{window}:1s]'
            )
            raw_mem = self._safe_query_value(raw_mem_query, default=0.0)
            if raw_mem > 0:
                mem_util = (raw_mem / 268435456.0) * 100.0

        # 3. Replica Count (healthy running pods)
        rep_query = (
            f'count(kube_pod_status_phase{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*", phase="Running"}} == 1)'
        )
        replica_count = int(self._safe_query_value(rep_query, default=1.0))
        if replica_count < 1:
            replica_count = 1

        # 4. Request Rate (req/s over 5s)
        req_query = (
            f'sum(rate(http_requests_total{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*"}}[{window}]))'
        )
        req_rate = self._safe_query_value(req_query, default=0.0)

        # 5. Success / Error Request Rates
        succ_query = (
            f'sum(rate(http_requests_total{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*", status=~"2..|3.."}}[{window}]))'
        )
        succ_rate = self._safe_query_value(succ_query, default=req_rate)

        err_query = (
            f'sum(rate(http_requests_total{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*", status=~"4..|5.."}}[{window}]))'
        )
        err_rate_val = self._safe_query_value(err_query, default=0.0)

        # 6. Latency (ms over 5s)
        lat_query = (
            f'avg(rate(http_request_duration_seconds_sum{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*"}}[{window}]) / '
            f'rate(http_request_duration_seconds_count{{namespace="{namespace}", '
            f'pod=~"^{service_id}.*"}}[{window}])) * 1000'
        )
        latency = self._safe_query_value(lat_query, default=0.0)

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
            "source": StateSource.LIVE,
        }

        return ServiceState.from_dict(data, source=StateSource.LIVE)
