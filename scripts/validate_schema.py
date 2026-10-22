"""
Schema and Topology Validation Script for FlexaScale.

Validates:
1. Per-service schema conformity between simulated (Alibaba trace) and live (Prometheus) state.
2. Complete multi-service state builder across all 7 shopping microservices.
3. Live Prometheus telemetry collection for all 7 microservices.
4. Correct 35-dimensional observation vector layout for GNN/RL consumption.
5. In-band telemetry status and missing-metric tracking.
"""

import time
import numpy as np
import pandas as pd

from flexascale.data.schema import ServiceState, StateSource, VECTOR_DIM, VECTOR_FIELDS
from flexascale.metrics.client import MetricsClient
from flexascale.state.live_builder import LiveStateBuilder
from flexascale.rl.gnn_encoder import SHOPPING_SERVICES


def validate_sim_data() -> tuple[np.ndarray, ServiceState]:
    """Validates that simulated/Alibaba trace data conforms to the shared schema."""
    print("[*] 1. Validating SIM (Alibaba) single-service data schema...")

    sim_row = pd.Series({
        "timestamp": int(time.time()),
        "service_id": "catalog-service",
        "cpu_utilization": 45.2,
        "memory_utilization": 60.5,
        "replica_count": 3,
        "request_rate": 150.0,
        "latency_ms": 25.4,
        "successful_requests": 148.0,
        "failed_requests": 2.0,
    })

    state = ServiceState.from_dataframe_row(sim_row, source=StateSource.ALIBABA)
    vec = state.to_vector()

    assert isinstance(vec, np.ndarray), "Output must be a numpy array"
    assert vec.shape == (VECTOR_DIM,), f"Vector must have shape ({VECTOR_DIM},)"
    assert vec.dtype == np.float32, "Vector must be float32"
    assert state.cpu_memory_ratio is not None, "Derived cpu_memory_ratio must be computed"
    assert 0.0 <= state.error_rate <= 1.0, "Derived error_rate must be in [0, 1]"

    print(f"  [+] SIM Validation passed! Vector shape: {vec.shape}, dtype: {vec.dtype}")
    print(f"      Extended metrics -> CPU/Mem Ratio: {state.cpu_memory_ratio:.2f}, Error Rate: {state.error_rate:.2%}, JCT: {state.jct:.1f}ms")
    return vec, state


def validate_live_seven_services() -> dict[str, ServiceState]:
    """Validates telemetry scrape across all 7 live shopping services from Prometheus."""
    print("\n[*] 2. Validating LIVE telemetry for all 7 shopping microservices...")

    client = MetricsClient(url="http://localhost:9090", sampling_interval_seconds=5)
    live_states: dict[str, ServiceState] = {}

    for sid in SHOPPING_SERVICES:
        state = client.get_service_state(sid, namespace="flexascale-apps")
        vec = state.to_vector()

        assert isinstance(vec, np.ndarray), f"Vector for {sid} must be a numpy array"
        assert vec.shape == (VECTOR_DIM,), f"Vector for {sid} must have shape ({VECTOR_DIM},)"
        assert vec.dtype == np.float32, f"Vector for {sid} must be float32"
        assert state.source == StateSource.LIVE

        live_states[sid] = state
        status_flag = "COMPLETE" if not state.missing_metrics else f"PARTIAL (missing: {state.missing_metrics})"
        print(f"  [+] {sid:<18} -> CPU: {state.cpu_utilization:5.2f}% | Mem: {state.memory_utilization:5.2f}% | "
              f"Reps: {state.replica_count} | RPS: {state.request_rate:5.2f} | Lat: {state.latency_ms:5.2f}ms | Telemetry: {status_flag}")

    return live_states


def validate_live_cluster_observation_vector() -> np.ndarray:
    """Validates multi-service concatenated observation vector construction."""
    print("\n[*] 3. Validating multi-service LiveStateBuilder observation vector (7 x 5 = 35)...")

    builder = LiveStateBuilder(
        services=SHOPPING_SERVICES,
        namespace="flexascale-apps",
        mock=False,
    )
    cluster_state = builder.build()
    obs_vector = cluster_state.observation_vector

    expected_dim = len(SHOPPING_SERVICES) * VECTOR_DIM
    assert obs_vector.shape == (expected_dim,), f"Expected shape ({expected_dim},), got {obs_vector.shape}"
    assert obs_vector.dtype == np.float32, f"Expected float32, got {obs_vector.dtype}"
    assert len(cluster_state.service_states) == len(SHOPPING_SERVICES), "All 7 services must be present"

    print(f"  [+] Live observation vector shape: {obs_vector.shape} (dtype: {obs_vector.dtype})")
    print(f"  [+] First 10 features: {np.round(obs_vector[:10], 2)}")
    print(f"  [+] Last 10 features:  {np.round(obs_vector[-10:], 2)}")
    return obs_vector


if __name__ == "__main__":
    print("=" * 72)
    print(" FlexaScale - 7-Service Shopping Application Schema Validation")
    print("=" * 72)

    sim_vec, sim_state = validate_sim_data()
    live_states = validate_live_seven_services()
    obs_vec = validate_live_cluster_observation_vector()

    # Verify per-service layout consistency
    sample_live_sid = list(live_states.keys())[0]
    sample_live_vec = live_states[sample_live_sid].to_vector()
    assert sim_vec.shape == sample_live_vec.shape, "Shape mismatch between SIM and LIVE per-service vectors!"
    assert sim_vec.dtype == sample_live_vec.dtype, "Dtype mismatch between SIM and LIVE per-service vectors!"

    print("\n" + "=" * 72)
    print("[SUCCESS] All 7 shopping microservices validated against the schema contract!")
    print(f"Per-Service Vector Dimension: {VECTOR_DIM} | Layout: {VECTOR_FIELDS}")
    print(f"Full Cluster Observation:     {obs_vec.shape[0]} dimensions (7 nodes x 5 features)")
    print("=" * 72)
