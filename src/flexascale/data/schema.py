"""
Shared state-vector schema for FlexaScale.

This module defines the single source of truth for the per-service
observation used by every component in the system:

    Producer                Consumer
    --------                --------
    Alibaba pipeline   ──┐
    Live Prometheus    ──┼──►  GNN + PPO RL agent
    Simulator          ──┘

All producers construct a ``ServiceState`` and call ``to_vector()``
to obtain the fixed-width float32 numpy array fed into the agent's observation space.

Schema Categories:
1. Time:
   - Raw/Normalized: timestamp, submit_time, start_time, finish_time
   - Derived: completion_time, wait_time, makespan
2. CPU / Memory:
   - Raw/Normalized: cpu_utilization (%), memory_utilization (%)
   - Derived: cpu_memory_ratio
3. Hardware:
   - Raw/Normalized: cpu_capacity, gpu_count, gpu_utilization, gpu_memory
4. Performance / Metrics:
   - Raw/Normalized: request_rate (req/s), latency_ms (ms)
   - Derived: jct, acceptance_ratio
5. Reliability:
   - Raw/Normalized: successful_requests, failed_requests
   - Derived: error_rate, success_rate

Fixed RL observation vector layout (index → field):
    0  cpu_utilization    (float, %)
    1  memory_utilization (float, %)
    2  replica_count      (float, cast from int)
    3  request_rate       (float, req/s)
    4  latency_ms         (float, ms)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, Tuple

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
Ordered field names that make up the primary RL observation vector.
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

    Used by schema-match validation to assert that live
    and sim observations share the same field definitions.
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
    Per-service observation at a single timestep across all telemetry categories.

    Field Categories:
    -----------------
    1. Time:
       - timestamp: int (epoch ms or seconds) [RAW/NORM]
       - submit_time: float (timestamp when request/task arrived) [RAW/NORM]
       - start_time: float (timestamp when request/task started execution) [RAW/NORM]
       - finish_time: float (timestamp when request/task finished) [RAW/NORM]
       - completion_time: float (finish_time - submit_time or latency duration) [DERIVED]
       - wait_time: float (start_time - submit_time or queue delay) [DERIVED]
       - makespan: float (workload duration across epoch/batch) [DERIVED]

    2. CPU / Memory:
       - cpu_utilization: float (%) [0, 100] [RAW/NORM]
       - memory_utilization: float (%) [0, 100] [RAW/NORM]
       - cpu_memory_ratio: float (cpu_util / memory_util) [DERIVED]

    3. Hardware:
       - replica_count: int (healthy running pods) [≥ 1] [RAW/NORM]
       - cpu_capacity: float (allocated cores/millicores) [RAW/NORM]
       - gpu_count: int (GPU count, default 0 for CPU-only services) [RAW/NORM]
       - gpu_utilization: float (GPU utilization %, default 0.0) [RAW/NORM]
       - gpu_memory: float (GPU memory in MB/%, default 0.0) [RAW/NORM]

    4. Performance / Metrics:
       - request_rate: float (req/s) [≥ 0] [RAW/NORM]
       - latency_ms: float (response latency in ms) [≥ 0] [RAW/NORM]
       - jct: float (Job Completion Time in ms) [DERIVED]
       - acceptance_ratio: float (accepted tasks / submitted tasks) [0, 1] [DERIVED]

    5. Reliability:
       - successful_requests: float (success count or req/s) [RAW/NORM]
       - failed_requests: float (error count or req/s) [RAW/NORM]
       - error_rate: float (failed / total) [0, 1] [DERIVED]
       - success_rate: float (successful / total) [0, 1] [DERIVED]
    """

    # Identifiers & Primary telemetry
    timestamp: int
    service_id: str
    cpu_utilization: float
    memory_utilization: float
    replica_count: int
    request_rate: float
    latency_ms: float
    source: StateSource = field(default=StateSource.ALIBABA)

    # 1. Time fields
    submit_time: float | None = None
    start_time: float | None = None
    finish_time: float | None = None
    completion_time: float | None = None
    wait_time: float | None = None
    makespan: float | None = None

    # 2. CPU / Memory fields
    cpu_memory_ratio: float | None = None

    # 3. Hardware fields
    cpu_capacity: float | None = None
    gpu_count: int = 0
    gpu_utilization: float = 0.0
    gpu_memory: float = 0.0

    # 4. Performance fields
    jct: float | None = None
    acceptance_ratio: float | None = None

    # 5. Reliability fields
    successful_requests: float = 0.0
    failed_requests: float = 0.0
    error_rate: float = 0.0
    success_rate: float = 1.0

    # Field category metadata mappings
    RAW_FIELDS: ClassVar[Tuple[str, ...]] = (
        "timestamp",
        "service_id",
        "cpu_utilization",
        "memory_utilization",
        "replica_count",
        "request_rate",
        "latency_ms",
        "submit_time",
        "start_time",
        "finish_time",
        "cpu_capacity",
        "gpu_count",
        "gpu_utilization",
        "gpu_memory",
        "successful_requests",
        "failed_requests",
    )

    NORMALIZED_FIELDS: ClassVar[Tuple[str, ...]] = (
        "cpu_utilization",
        "memory_utilization",
        "replica_count",
        "request_rate",
        "latency_ms",
    )

    DERIVED_FIELDS: ClassVar[Tuple[str, ...]] = (
        "completion_time",
        "wait_time",
        "makespan",
        "cpu_memory_ratio",
        "jct",
        "acceptance_ratio",
        "error_rate",
        "success_rate",
    )

    def __post_init__(self) -> None:
        self._calculate_derived_fields()
        self.validate()

    # ------------------------------------------------------------------
    # Derived fields computation
    # ------------------------------------------------------------------

    def _calculate_derived_fields(self) -> None:
        """Compute all derived metrics deterministically from raw values."""
        # 1. Time calculations
        if self.submit_time is None:
            self.submit_time = float(self.timestamp)
        if self.start_time is None:
            self.start_time = self.submit_time
        if self.completion_time is None:
            if self.finish_time is not None:
                self.completion_time = max(0.0, self.finish_time - self.submit_time)
            else:
                self.completion_time = max(0.0, self.latency_ms)
        if self.finish_time is None:
            self.finish_time = self.start_time + self.completion_time

        if self.wait_time is None:
            if self.start_time is not None and self.submit_time is not None:
                self.wait_time = max(0.0, self.start_time - self.submit_time)
            else:
                self.wait_time = 0.0

        if self.makespan is None:
            self.makespan = self.completion_time

        # 2. CPU / Memory ratio: cpu_utilization / memory_utilization
        if self.cpu_memory_ratio is None:
            safe_mem = max(self.memory_utilization, 1e-6)
            self.cpu_memory_ratio = float(self.cpu_utilization / safe_mem)

        # 3. Performance / JCT
        if self.jct is None:
            self.jct = float(self.completion_time)

        # 4. Reliability calculations
        total_reqs = self.successful_requests + self.failed_requests
        if total_reqs > 0:
            self.error_rate = float(self.failed_requests / total_reqs)
            self.success_rate = float(self.successful_requests / total_reqs)
            if self.acceptance_ratio is None:
                self.acceptance_ratio = self.success_rate
        else:
            if self.acceptance_ratio is None:
                self.acceptance_ratio = max(0.0, min(1.0, 1.0 - self.error_rate))
            if self.success_rate is None or self.success_rate == 1.0:
                self.success_rate = max(0.0, min(1.0, 1.0 - self.error_rate))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Raise ``ValueError`` if any field is out of its valid range.
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

        if self.error_rate < 0.0 or self.error_rate > 1.0:
            errors.append(
                f"error_rate must be in [0, 1], got {self.error_rate}"
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert state instance to a complete dictionary of all metrics."""
        return {
            # Metadata
            "timestamp": self.timestamp,
            "service_id": self.service_id,
            "source": self.source.value,
            # Core Normalized Fields
            "cpu_utilization": self.cpu_utilization,
            "memory_utilization": self.memory_utilization,
            "replica_count": self.replica_count,
            "request_rate": self.request_rate,
            "latency_ms": self.latency_ms,
            # Time Fields
            "submit_time": self.submit_time,
            "start_time": self.start_time,
            "finish_time": self.finish_time,
            "completion_time": self.completion_time,
            "wait_time": self.wait_time,
            "makespan": self.makespan,
            # CPU / Memory Fields
            "cpu_memory_ratio": self.cpu_memory_ratio,
            # Hardware Fields
            "cpu_capacity": self.cpu_capacity,
            "gpu_count": self.gpu_count,
            "gpu_utilization": self.gpu_utilization,
            "gpu_memory": self.gpu_memory,
            # Performance Fields
            "jct": self.jct,
            "acceptance_ratio": self.acceptance_ratio,
            # Reliability Fields
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "error_rate": self.error_rate,
            "success_rate": self.success_rate,
        }

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        source: StateSource = StateSource.LIVE,
    ) -> "ServiceState":
        """Construct from dictionary with optional extended fields."""
        return cls(
            timestamp=int(data["timestamp"]),
            service_id=str(data["service_id"]),
            cpu_utilization=float(data["cpu_utilization"]),
            memory_utilization=float(data["memory_utilization"]),
            replica_count=int(data["replica_count"]),
            request_rate=float(data["request_rate"]),
            latency_ms=float(data["latency_ms"]),
            source=source if isinstance(source, StateSource) else StateSource(source),
            submit_time=float(data["submit_time"]) if "submit_time" in data and data["submit_time"] is not None else None,
            start_time=float(data["start_time"]) if "start_time" in data and data["start_time"] is not None else None,
            finish_time=float(data["finish_time"]) if "finish_time" in data and data["finish_time"] is not None else None,
            completion_time=float(data["completion_time"]) if "completion_time" in data and data["completion_time"] is not None else None,
            wait_time=float(data["wait_time"]) if "wait_time" in data and data["wait_time"] is not None else None,
            makespan=float(data["makespan"]) if "makespan" in data and data["makespan"] is not None else None,
            cpu_memory_ratio=float(data["cpu_memory_ratio"]) if "cpu_memory_ratio" in data and data["cpu_memory_ratio"] is not None else None,
            cpu_capacity=float(data["cpu_capacity"]) if "cpu_capacity" in data and data["cpu_capacity"] is not None else None,
            gpu_count=int(data.get("gpu_count", 0)),
            gpu_utilization=float(data.get("gpu_utilization", 0.0)),
            gpu_memory=float(data.get("gpu_memory", 0.0)),
            jct=float(data["jct"]) if "jct" in data and data["jct"] is not None else None,
            acceptance_ratio=float(data["acceptance_ratio"]) if "acceptance_ratio" in data and data["acceptance_ratio"] is not None else None,
            successful_requests=float(data.get("successful_requests", 0.0)),
            failed_requests=float(data.get("failed_requests", 0.0)),
            error_rate=float(data.get("error_rate", 0.0)),
            success_rate=float(data.get("success_rate", 1.0)),
        )

    @classmethod
    def from_dataframe_row(
        cls,
        row: pd.Series,
        source: StateSource = StateSource.ALIBABA,
    ) -> "ServiceState":
        """Construct from pandas Series."""
        return cls(
            timestamp=int(row["timestamp"]),
            service_id=str(row["service_id"]),
            cpu_utilization=float(row["cpu_utilization"]),
            memory_utilization=float(row["memory_utilization"]),
            replica_count=int(row["replica_count"]),
            request_rate=float(row["request_rate"]),
            latency_ms=float(row["latency_ms"]),
            source=source if isinstance(source, StateSource) else StateSource(source),
            submit_time=float(row["submit_time"]) if "submit_time" in row and pd.notna(row["submit_time"]) else None,
            start_time=float(row["start_time"]) if "start_time" in row and pd.notna(row["start_time"]) else None,
            finish_time=float(row["finish_time"]) if "finish_time" in row and pd.notna(row["finish_time"]) else None,
            completion_time=float(row["completion_time"]) if "completion_time" in row and pd.notna(row["completion_time"]) else None,
            wait_time=float(row["wait_time"]) if "wait_time" in row and pd.notna(row["wait_time"]) else None,
            makespan=float(row["makespan"]) if "makespan" in row and pd.notna(row["makespan"]) else None,
            cpu_memory_ratio=float(row["cpu_memory_ratio"]) if "cpu_memory_ratio" in row and pd.notna(row["cpu_memory_ratio"]) else None,
            cpu_capacity=float(row["cpu_capacity"]) if "cpu_capacity" in row and pd.notna(row["cpu_capacity"]) else None,
            gpu_count=int(row["gpu_count"]) if "gpu_count" in row and pd.notna(row["gpu_count"]) else 0,
            gpu_utilization=float(row["gpu_utilization"]) if "gpu_utilization" in row and pd.notna(row["gpu_utilization"]) else 0.0,
            gpu_memory=float(row["gpu_memory"]) if "gpu_memory" in row and pd.notna(row["gpu_memory"]) else 0.0,
            jct=float(row["jct"]) if "jct" in row and pd.notna(row["jct"]) else None,
            acceptance_ratio=float(row["acceptance_ratio"]) if "acceptance_ratio" in row and pd.notna(row["acceptance_ratio"]) else None,
            successful_requests=float(row["successful_requests"]) if "successful_requests" in row and pd.notna(row["successful_requests"]) else 0.0,
            failed_requests=float(row["failed_requests"]) if "failed_requests" in row and pd.notna(row["failed_requests"]) else 0.0,
            error_rate=float(row["error_rate"]) if "error_rate" in row and pd.notna(row["error_rate"]) else 0.0,
            success_rate=float(row["success_rate"]) if "success_rate" in row and pd.notna(row["success_rate"]) else 1.0,
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
            f"cpu/mem={self.cpu_memory_ratio:.2f}, "
            f"replicas={self.replica_count}, "
            f"rps={self.request_rate:.2f}, "
            f"latency={self.latency_ms:.1f}ms, "
            f"err_rate={self.error_rate:.2%}, "
            f"source={self.source.value})"
        )
