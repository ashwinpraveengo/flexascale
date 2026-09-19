"""
Pydantic API models for FlexaScale REST API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ServiceMetricsModel(BaseModel):
    service_id: str
    cpu_utilization: float
    memory_utilization: float
    replica_count: int
    request_rate: float
    latency_ms: float
    error_rate: float = 0.0
    slo_satisfied: bool = True


class SystemStatusModel(BaseModel):
    status: str = "healthy"
    operator_running: bool
    is_live_cluster: bool
    modes: Dict[str, str]
    replicas: Dict[str, int]
    timestamp: float


class DecisionModel(BaseModel):
    service_id: str
    chosen_mode: str
    confidence: Optional[float] = None
    target_replicas: int
    action_applied: Optional[int] = None
    lock_acquired: bool
    hpa_frozen: bool
    hpa_active: bool
    reason: str
    timestamp: Optional[float] = None


class GraphNodeModel(BaseModel):
    id: str
    index: int
    label: str


class GraphEdgeModel(BaseModel):
    source: str
    target: str
    weight: float
    active: bool = True


class GraphResponseModel(BaseModel):
    nodes: List[GraphNodeModel]
    edges: List[GraphEdgeModel]
    num_nodes: int
    num_edges: int
    alpha: float
    decay_rate: float
    last_updated: float


class ConfigModel(BaseModel):
    target_cpu_utilization: float = Field(default=70.0, ge=10.0, le=95.0)
    slo_latency_target_ms: float = Field(default=100.0, ge=1.0, le=2000.0)
    confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    deactivation_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    cooldown_seconds: float = Field(default=15.0, ge=0.0, le=300.0)
    hpa_min_replicas: int = Field(default=1, ge=1, le=50)
    hpa_max_replicas: int = Field(default=10, ge=1, le=100)


class ConfigUpdateModel(BaseModel):
    target_cpu_utilization: Optional[float] = None
    slo_latency_target_ms: Optional[float] = None
    confidence_threshold: Optional[float] = None
    deactivation_threshold: Optional[float] = None
    cooldown_seconds: Optional[float] = None


class HistoryPointModel(BaseModel):
    timestamp: float
    cpu_utilization: float
    latency_ms: float
    request_rate: float
    total_replicas: int
    slo_latency_target_ms: float
