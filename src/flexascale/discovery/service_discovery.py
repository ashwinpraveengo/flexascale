"""
Dynamic Workload & Service Discovery for FlexaScale.

Automatically discovers Kubernetes Deployments and microservices in target namespaces
without requiring application-specific code modifications or hardcoded service lists.
Supports Kubernetes API / kubectl inspection, Prometheus metrics discovery,
and mock testing environments.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Sequence, Set

import requests

logger = logging.getLogger(__name__)

# Default services to ignore (FlexaScale internal controllers)
DEFAULT_EXCLUDED_PATTERNS: tuple[str, ...] = (
    r"^flexascale-.*",
    r".*monitoring.*",
    r".*grafana.*",
    r".*prometheus.*",
    r".*kube-state-metrics.*",
)


class ServiceDiscovery:
    """
    Discovers scalable container workloads and microservices in Kubernetes.
    """

    def __init__(
        self,
        namespace: str = "default",
        label_selector: str = "",
        prometheus_url: str = "http://localhost:9090",
        excluded_patterns: Sequence[str] = DEFAULT_EXCLUDED_PATTERNS,
        mock: bool = False,
        mock_services: Optional[Sequence[str]] = None,
        cache_ttl_seconds: float = 15.0,
    ) -> None:
        self.namespace = namespace
        self.label_selector = label_selector
        self.prometheus_url = prometheus_url.rstrip("/")
        self.excluded_patterns = [re.compile(p) for p in excluded_patterns]
        self.mock = mock
        self._mock_services = list(mock_services) if mock_services is not None else [
            "frontend", "orders", "inventory", "payments"
        ]
        self.cache_ttl = cache_ttl_seconds
        self._cached_services: List[str] = []
        self._last_discovery_time: float = 0.0

    def set_mock_services(self, services: Sequence[str]) -> None:
        """Dynamically updates mock service list for testing."""
        self._mock_services = list(services)
        self._cached_services = list(services)
        self._last_discovery_time = time.time()

    def is_excluded(self, service_name: str) -> bool:
        """Check if service matches any internal exclusion patterns."""
        for pattern in self.excluded_patterns:
            if pattern.search(service_name):
                return True
        return False

    def _discover_via_kubectl(self) -> List[str]:
        """Discover deployments via kubectl CLI."""
        cmd = [
            "kubectl", "get", "deployments",
            "-n", self.namespace,
            "-o", "json",
        ]
        if self.label_selector:
            cmd.extend(["-l", self.label_selector])

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                items = data.get("items", [])
                deployments = [
                    item["metadata"]["name"]
                    for item in items
                    if "metadata" in item and "name" in item["metadata"]
                ]
                return [d for d in deployments if not self.is_excluded(d)]
        except Exception as exc:
            logger.debug("[DISCOVERY] kubectl discovery failed: %s", exc)
        return []

    def _discover_via_incluster_api(self) -> List[str]:
        """Discover deployments via in-cluster Kubernetes REST API."""
        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

        if not os.path.exists(token_path):
            return []

        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()

            headers = {"Authorization": f"Bearer {token}"}
            url = f"https://kubernetes.default.svc/apis/apps/v1/namespaces/{self.namespace}/deployments"
            params: Dict[str, str] = {}
            if self.label_selector:
                params["labelSelector"] = self.label_selector

            verify: Any = ca_path if os.path.exists(ca_path) else False
            resp = requests.get(url, headers=headers, params=params, verify=verify, timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                deployments = [item["metadata"]["name"] for item in items if "name" in item.get("metadata", {})]
                return [d for d in deployments if not self.is_excluded(d)]
        except Exception as exc:
            logger.debug("[DISCOVERY] In-cluster API discovery failed: %s", exc)
        return []

    def _discover_via_prometheus(self) -> List[str]:
        """Discover active services/deployments from Prometheus metrics."""
        # Query kube-state-metrics deployment labels
        query = f'count by (deployment) (kube_deployment_labels{{namespace="{self.namespace}"}})'
        try:
            resp = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": query},
                timeout=3.0,
            )
            if resp.status_code == 200:
                results = resp.json().get("data", {}).get("result", [])
                deployments = [
                    r["metric"]["deployment"]
                    for r in results
                    if "metric" in r and "deployment" in r["metric"]
                ]
                if deployments:
                    return [d for d in deployments if not self.is_excluded(d)]
        except Exception as exc:
            logger.debug("[DISCOVERY] Prometheus deployment query failed: %s", exc)

        # Fallback query: pod containers in namespace
        query_pods = f'count by (pod) (container_cpu_usage_seconds_total{{namespace="{self.namespace}", container!=""}})'
        try:
            resp = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": query_pods},
                timeout=3.0,
            )
            if resp.status_code == 200:
                results = resp.json().get("data", {}).get("result", [])
                # Extract deployment prefix from pod names (e.g., 'cart-service-5d9c79469-x8j2l' -> 'cart-service')
                discovered: Set[str] = set()
                for r in results:
                    pod_name = r.get("metric", {}).get("pod", "")
                    parts = pod_name.rsplit("-", 2)
                    if len(parts) >= 3:
                        dep_name = parts[0]
                        if not self.is_excluded(dep_name):
                            discovered.add(dep_name)
                    elif pod_name and not self.is_excluded(pod_name):
                        discovered.add(pod_name)
                if discovered:
                    return sorted(list(discovered))
        except Exception as exc:
            logger.debug("[DISCOVERY] Prometheus pod query failed: %s", exc)

        return []

    def discover(self, force_refresh: bool = False) -> List[str]:
        """
        Discover scalable microservices in the target namespace.
        Uses cached results if called within cache_ttl_seconds.
        """
        now = time.time()
        if not force_refresh and self._cached_services and (now - self._last_discovery_time < self.cache_ttl):
            return list(self._cached_services)

        if self.mock:
            self._cached_services = [s for s in self._mock_services if not self.is_excluded(s)]
            self._last_discovery_time = now
            return list(self._cached_services)

        # 1. Try in-cluster Kubernetes API
        discovered = self._discover_via_incluster_api()

        # 2. Try kubectl CLI if in-cluster API was empty
        if not discovered:
            discovered = self._discover_via_kubectl()

        # 3. Try Prometheus metrics discovery if K8s API was unavailable
        if not discovered:
            discovered = self._discover_via_prometheus()

        # 4. If all live methods yielded nothing, fall back to mock or cached
        if not discovered and self._cached_services:
            return list(self._cached_services)

        # Retain sorted unique service list
        self._cached_services = sorted(list(set(discovered)))
        self._last_discovery_time = now
        logger.info(
            "[DISCOVERY] Discovered %d scalable workloads in namespace '%s': %s",
            len(self._cached_services),
            self.namespace,
            self._cached_services,
        )
        return list(self._cached_services)
