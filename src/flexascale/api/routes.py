"""
API route handlers for FlexaScale REST API.
"""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException

from flexascale.api.models import (
    ConfigModel,
    ConfigUpdateModel,
    DecisionModel,
    GraphResponseModel,
    HistoryPointModel,
    ServiceMetricsModel,
    SystemStatusModel,
)
from flexascale.api.state_store import APIStateStore, get_state_store

router = APIRouter(prefix="/api", tags=["flexascale"])


@router.get("/health", response_model=Dict[str, str])
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "flexascale-api"}


@router.get("/status", response_model=SystemStatusModel)
def get_system_status(store: APIStateStore = Depends(get_state_store)):
    """Retrieve current system status, controller modes, and active replicas."""
    return store.get_system_status()


@router.get("/metrics", response_model=List[ServiceMetricsModel])
def get_metrics(store: APIStateStore = Depends(get_state_store)):
    """Retrieve real-time metrics and SLO compliance per microservice."""
    return store.get_service_metrics()


@router.get("/history", response_model=List[HistoryPointModel])
def get_metrics_history(store: APIStateStore = Depends(get_state_store)):
    """Retrieve chronological cluster telemetry for time-series dashboard charts."""
    return list(store.history)


@router.get("/decisions", response_model=List[DecisionModel])
def get_decisions(limit: int = 50, store: APIStateStore = Depends(get_state_store)):
    """Retrieve chronological log of safety scaling decisions."""
    return store.get_decisions(limit=limit)


@router.get("/graph", response_model=GraphResponseModel)
def get_dependency_graph(store: APIStateStore = Depends(get_state_store)):
    """Retrieve current microservice dependency call graph with EMA weights."""
    return store.get_graph()


@router.get("/config", response_model=ConfigModel)
def get_configuration(store: APIStateStore = Depends(get_state_store)):
    """Retrieve active SLO, safety thresholds, and autoscaler configuration."""
    return store.get_config()


@router.post("/config", response_model=ConfigModel)
def update_configuration(
    updates: ConfigUpdateModel,
    store: APIStateStore = Depends(get_state_store),
):
    """Dynamically update SLO target, target CPU, or confidence thresholds."""
    return store.update_config(updates.model_dump(exclude_none=True))


@router.post("/fallback", response_model=Dict[str, Any])
def trigger_emergency_fallback(store: APIStateStore = Depends(get_state_store)):
    """Emergency manual fallback: release all locks and restore native dynamic HPA."""
    return store.emergency_fallback()


@router.post("/step", response_model=List[DecisionModel])
def trigger_operator_step(store: APIStateStore = Depends(get_state_store)):
    """Manually trigger a single autonomous operator step and return decisions."""
    return store.step()
