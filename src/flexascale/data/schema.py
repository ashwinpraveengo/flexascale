"""
Shared state-vector schema for FlexaScale.

This module defines the single source of truth for the per-service
observation used by every component in the system:

    Producer                Consumer
    --------                --------
    Alibaba pipeline   ──┐
    Live Prometheus    ──┼──►  GNN + PPO RL agent
    Simulator          ──┘

All producers must construct a ``ServiceState`` and call
``to_vector()`` to obtain the fixed-width float32 numpy array
fed into the agent's observation space.

Fixed vector layout (index → field):
    0  cpu_utilization    (float, %)
    1  memory_utilization (float, %)
    2  replica_count      (float, cast from int)
    3  request_rate       (float, req/s)
    4  latency_ms         (float, ms)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Vector layout
# ---------------------------------------------------------------------------

VECTOR_FIELDS: tuple[str, ...] = (
    "cpu_utilization",
    "memory_utilization",
    "replica_count",
    "request_rate",
    "latency_ms",
)
"""
Ordered field names that make up the RL observation vector.
Index positions are stable — never reorder without versioning the agent.
"""

VECTOR_DIM: int = len(VECTOR_FIELDS)
"""Dimensionality of the per-service observation vector (= 5)."""


# ---------------------------------------------------------------------------
# Source enum
# ---------------------------------------------------------------------------

class StateSource(str, Enum):
    """
    Origin tag for a ServiceState observation.

    Used by Ghanshyam's schema-match validation to assert that live
    and sim observations share the same field distributions.
    """

    ALIBABA = "alibaba"   # Offline historical trace (build_dataset.py)
    LIVE = "live"         # Real-time Prometheus scrape
    SIM = "sim"           # Simulator-generated episode step


# ---------------------------------------------------------------------------
# Core dataclass
# ---------------------------------------------------------------------------

@dataclass
class ServiceState:
    """
    Per-service observation at a single timestep.

    All numeric fields are normalised to standard units:
        - cpu_utilization    : mean CPU utilisation across replicas [0, 100] %
        - memory_utilization : mean memory utilisation across replicas [0, 100] %
        - replica_count      : number of healthy running replicas [≥ 1]
        - request_rate       : provider-side requests per second [≥ 0]
        - latency_ms         : mean provider-side response latency in ms [≥ 0]

    The ``source`` field tags which producer created this observation so
    that downstream consumers and validation scripts can distinguish
    live telemetry from historical or simulated data without inspecting
    the call stack.
    """

    timestamp: int
    service_id: str
    cpu_utilization: float
    memory_utilization: float
    replica_count: int
    request_rate: float
    latency_ms: float
    source: StateSource = field(default=StateSource.ALIBABA)

    def __post_init__(self) -> None:
        self.validate()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Raise ``ValueError`` if any field is out of its valid range.

        Called automatically on construction via ``__post_init__``.
        """
        errors: list[str] = []

        if not isinstance(self.service_id, str) or not self.service_id.strip():
            errors.append("service_id must be a non-empty string")

        if not (0.0 <= self.cpu_utilization <= 100.0):
            errors.append(
                f"cpu_utilization must be in [0, 100], got {self.cpu_utilization}"
            )

        if not (0.0 <= self.memory_utilization <= 100.0):
            errors.append(
                f"memory_utilization must be in [0, 100], got {self.memory_utilization}"
            )

        if self.replica_count < 1:
            errors.append(
                f"replica_count must be >= 1, got {self.replica_count}"
            )

        if self.request_rate < 0.0:
            errors.append(
                f"request_rate must be >= 0, got {self.request_rate}"
            )

        if self.latency_ms < 0.0:
            errors.append(
                f"latency_ms must be >= 0, got {self.latency_ms}"
            )

        if errors:
            raise ValueError(
                f"Invalid ServiceState for '{self.service_id}': "
                + "; ".join(errors)
            )

    # ------------------------------------------------------------------
    # RL vector conversion
    # ------------------------------------------------------------------

    def to_vector(self) -> np.ndarray:
        """
        Return a fixed-width float32 numpy array for the RL agent.

        Shape: ``(VECTOR_DIM,)`` = ``(5,)``
        Layout: see ``VECTOR_FIELDS``.

        Example::

            state = ServiceState(...)
            obs   = state.to_vector()   # shape (5,), dtype float32
        """
        return np.array(
            [
                self.cpu_utilization,
                self.memory_utilization,
                float(self.replica_count),
                self.request_rate,
                self.latency_ms,
            ],
            dtype=np.float32,
        )

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        source: StateSource = StateSource.LIVE,
    ) -> "ServiceState":
        """
        Construct from a plain dictionary.

        Used by the live Prometheus scraper and any JSON-based producer.

        Args:
            data:   Dictionary with keys matching ``ServiceState`` fields.
            source: Origin tag (defaults to ``LIVE`` for scraper use).

        Raises:
            KeyError:   if a required key is missing from ``data``.
            ValueError: if any field fails range validation.
        """
        return cls(
            timestamp=int(data["timestamp"]),
            service_id=str(data["service_id"]),
            cpu_utilization=float(data["cpu_utilization"]),
            memory_utilization=float(data["memory_utilization"]),
            replica_count=int(data["replica_count"]),
            request_rate=float(data["request_rate"]),
            latency_ms=float(data["latency_ms"]),
            source=source,
        )

    @classmethod
    def from_dataframe_row(
        cls,
        row: pd.Series,
        source: StateSource = StateSource.ALIBABA,
    ) -> "ServiceState":
        """
        Construct from a pandas Series (single row of a DataFrame).

        Used by ``build_dataset.py`` to validate pipeline output rows.

        Args:
            row:    A pandas Series whose index contains the required fields.
            source: Origin tag (defaults to ``ALIBABA`` for pipeline use).

        Raises:
            KeyError:   if a required field is missing from the Series.
            ValueError: if any field fails range validation.
        """
        return cls(
            timestamp=int(row["timestamp"]),
            service_id=str(row["service_id"]),
            cpu_utilization=float(row["cpu_utilization"]),
            memory_utilization=float(row["memory_utilization"]),
            replica_count=int(row["replica_count"]),
            request_rate=float(row["request_rate"]),
            latency_ms=float(row["latency_ms"]),
            source=source,
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ServiceState("
            f"service_id={self.service_id!r}, "
            f"t={self.timestamp}, "
            f"cpu={self.cpu_utilization:.1f}%, "
            f"mem={self.memory_utilization:.1f}%, "
            f"replicas={self.replica_count}, "
            f"rps={self.request_rate:.2f}, "
            f"latency={self.latency_ms:.1f}ms, "
            f"source={self.source.value})"
        )
