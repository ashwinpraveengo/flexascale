import time
from typing import Dict, Any

from prometheus_api_client import PrometheusConnect
from flexascale.data.schema import ServiceState, StateSource

class MetricsClient:
    """
    Client wrapper for querying Prometheus and returning standardized ServiceState.
    """
    def __init__(self, url: str = "http://localhost:9090"):
        self.prom = PrometheusConnect(url=url, disable_ssl=True)
        
    def get_service_state(self, service_id: str, namespace: str = "flexascale-apps") -> ServiceState:
        """
        Queries Prometheus for the last 5s of metrics for a given service.
        Returns a validated ServiceState object.
        """
        # 1. CPU Utilization (percentage)
        cpu_query = f'avg(rate(container_cpu_usage_seconds_total{{namespace="{namespace}", pod=~"^{service_id}.*"}}[5s])) * 100'
        cpu_res = self.prom.custom_query(cpu_query)
        cpu_util = float(cpu_res[0]["value"][1]) if cpu_res else 0.0
        
        # 2. Memory Utilization (percentage)
        mem_query = f'avg(container_memory_working_set_bytes{{namespace="{namespace}", pod=~"^{service_id}.*"}} / container_spec_memory_limit_bytes{{namespace="{namespace}", pod=~"^{service_id}.*"}}) * 100'
        mem_res = self.prom.custom_query(mem_query)
        mem_util = float(mem_res[0]["value"][1]) if mem_res else 0.0
        
        # 3. Replica Count
        # If kube-state-metrics isn't fully synced or matching, fallback to 1 to pass schema validation
        rep_query = f'count(kube_pod_info{{namespace="{namespace}", pod=~"^{service_id}.*"}})'
        rep_res = self.prom.custom_query(rep_query)
        replica_count = int(rep_res[0]["value"][1]) if rep_res else 1
        
        # 4. Request Rate (req/s)
        # Assuming standard http_requests_total metric. If not present (e.g. dummy apps), defaults to 0.0
        req_query = f'sum(rate(http_requests_total{{namespace="{namespace}", pod=~"^{service_id}.*"}}[5s]))'
        req_res = self.prom.custom_query(req_query)
        req_rate = float(req_res[0]["value"][1]) if req_res else 0.0
        
        # 5. Latency (ms)
        # Using http_request_duration_seconds summary/histogram. If not present, defaults to 0.0
        lat_query = f'avg(rate(http_request_duration_seconds_sum{{namespace="{namespace}", pod=~"^{service_id}.*"}}[5s]) / rate(http_request_duration_seconds_count{{namespace="{namespace}", pod=~"^{service_id}.*"}}[5s])) * 1000'
        lat_res = self.prom.custom_query(lat_query)
        
        latency = 0.0
        if lat_res:
            val = lat_res[0]["value"][1]
            if val != "NaN" and val is not None:
                latency = float(val)
                
        # Build dictionary for from_dict constructor
        data = {
            "timestamp": int(time.time()),
            "service_id": service_id,
            "cpu_utilization": max(0.0, min(100.0, cpu_util)),
            "memory_utilization": max(0.0, min(100.0, mem_util)),
            "replica_count": max(1, replica_count),
            "request_rate": max(0.0, req_rate),
            "latency_ms": max(0.0, latency)
        }
        
        return ServiceState.from_dict(data, source=StateSource.LIVE)
