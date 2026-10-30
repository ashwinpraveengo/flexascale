"""
WorkloadMetricsClient.collect against canned Prometheus answers: the three cluster
differences documented in metrics/workload_metrics.py (pod-level cAdvisor only,
pods scraped by two jobs, genuine zero traffic vs missing data).
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from flexascale.metrics.workload_metrics import WorkloadMetricsClient

POD = "cart-service-6d567c9496-tz9c8"


def series(values: Dict[str, float], **labels) -> List[dict]:
    return [{"metric": {"pod": pod, **labels}, "value": [0, str(v)]} for pod, v in values.items()]


class FakeProm(WorkloadMetricsClient):
    """Answers by query shape; records every query it was asked."""

    def __init__(self, answers: Dict[str, List[dict]]) -> None:
        super().__init__("http://prometheus.invalid")
        self.answers = answers
        self.asked: List[str] = []

    def query(self, promql: str):
        self.asked.append(promql)
        for key, result in self.answers.items():
            if key in promql:
                return result
        return []


def answers(**over) -> Dict[str, List[dict]]:
    base = {
        'container_cpu_usage_seconds_total{namespace="ns",container!=""': [],
        'container_cpu_usage_seconds_total{namespace="ns",container="",pod!=""}': series({POD: 0.05}),
        'container_memory_working_set_bytes{namespace="ns",container!=""': [],
        'container_memory_working_set_bytes{namespace="ns",container="",pod!=""}': series({POD: 64e6}),
        "timestamp(container_cpu_usage_seconds_total": series({POD: 5.0}),
        "up{": series({POD: 1}),
    }
    base.update(over)
    return base


def collect(client: FakeProm):
    return client.collect("ns", ["cart-service"], {"cart-service": 0.1}, {"cart-service": 256e6})["cart-service"]


def test_pod_level_cadvisor_is_used_when_no_container_series_exist():
    m = collect(FakeProm(answers()))
    assert m.cpu_pct == pytest.approx(50.0) and m.memory_pct == pytest.approx(25.0)
    assert "cpu" not in m.missing and "memory" not in m.missing and not m.stale


def test_container_level_series_win_over_pod_level():
    m = collect(FakeProm(answers(**{'container_cpu_usage_seconds_total{namespace="ns",container!=""': series({POD: 0.02})})))
    assert m.cpu_pct == pytest.approx(20.0)


def test_scraped_pod_without_request_series_is_a_genuine_zero():
    m = collect(FakeProm(answers()))
    assert m.request_rate == 0.0 and m.error_rate == 0.0 and m.no_traffic
    assert "request_rate" not in m.missing and "latency" not in m.missing and m.latency_mean_ms is None


def test_unscraped_pod_reports_request_metrics_missing_not_zero():
    m = collect(FakeProm(answers(**{"up{": []})))
    assert m.request_rate is None and not m.no_traffic
    assert "request_rate" in m.missing and "latency" in m.missing


def test_request_metrics_are_deduplicated_across_scrape_jobs():
    client = FakeProm(answers(**{
        "rate(http_requests_total{namespace=\"ns\"}": series({POD: 4.0}),
        "http_request_duration_seconds_sum": series({POD: 0.2}),
        "http_request_duration_seconds_count": series({POD: 4.0}),
    }))
    m = collect(client)
    assert m.request_rate == pytest.approx(4.0) and m.latency_mean_ms == pytest.approx(50.0) and not m.no_traffic
    http = [q for q in client.asked if "http_request" in q]
    assert http and all(q.startswith("max by (pod") and "sum by (pod, job)" in q or "sum by (pod, le, job)" in q for q in http)


def test_missing_cpu_is_never_invented():
    m = collect(FakeProm(answers(**{'container_cpu_usage_seconds_total{namespace="ns",container="",pod!=""}': [],
                                    "timestamp(container_cpu_usage_seconds_total": []})))
    assert m.cpu_pct is None and "cpu" in m.missing and m.stale
