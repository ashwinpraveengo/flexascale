"""
Unit tests for Dynamic Service Discovery module.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from flexascale.discovery.service_discovery import ServiceDiscovery


def test_discovery_mock_mode():
    sd = ServiceDiscovery(mock=True, mock_services=["user-api", "cart-service", "db-proxy"])
    services = sd.discover()
    assert set(services) == {"cart-service", "db-proxy", "user-api"}
    assert len(services) == 3


def test_discovery_exclusion_patterns():
    sd = ServiceDiscovery(mock=True)
    assert sd.is_excluded("flexascale-operator") is True
    assert sd.is_excluded("flexascale-api") is True
    assert sd.is_excluded("monitoring-prometheus") is True
    assert sd.is_excluded("kube-state-metrics") is True
    assert sd.is_excluded("grafana") is True
    assert sd.is_excluded("frontend") is False
    assert sd.is_excluded("payment-service") is False


def test_discovery_cache_ttl():
    sd = ServiceDiscovery(mock=True, mock_services=["service-a", "service-b"], cache_ttl_seconds=10.0)
    s1 = sd.discover()
    assert s1 == ["service-a", "service-b"]

    # Directly mutate mock services without force refresh
    sd._mock_services = ["service-c"]
    s2 = sd.discover(force_refresh=False)
    assert s2 == ["service-a", "service-b"]

    # Force refresh
    s3 = sd.discover(force_refresh=True)
    assert s3 == ["service-c"]


def test_discovery_kubectl_parsing():
    sd = ServiceDiscovery(mock=False, namespace="test-ns")
    sample_kubectl_output = json.dumps({
        "items": [
            {"metadata": {"name": "auth-service"}},
            {"metadata": {"name": "cart-service"}},
            {"metadata": {"name": "flexascale-operator"}},  # Should be excluded
        ]
    })

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = sample_kubectl_output

    with patch("subprocess.run", return_value=mock_res):
        discovered = sd._discover_via_kubectl()
        assert discovered == ["auth-service", "cart-service"]


def test_discovery_prometheus_parsing():
    sd = ServiceDiscovery(mock=False, namespace="test-ns")
    sample_prom_response = MagicMock()
    sample_prom_response.status_code = 200
    sample_prom_response.json.return_value = {
        "data": {
            "result": [
                {"metric": {"deployment": "billing-engine"}},
                {"metric": {"deployment": "catalog-api"}},
                {"metric": {"deployment": "flexascale-api"}},  # Should be excluded
            ]
        }
    }

    with patch("requests.get", return_value=sample_prom_response):
        discovered = sd._discover_via_prometheus()
        assert discovered == ["billing-engine", "catalog-api"]
