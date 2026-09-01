import time
import pandas as pd
import numpy as np

from flexascale.data.schema import ServiceState, StateSource, VECTOR_DIM
from flexascale.metrics.client import MetricsClient

def validate_sim_data():
    """Validates that simulated/Alibaba trace data conforms to the schema."""
    print("[*] Validating SIM (Alibaba) data schema...")
    
    # Create a dummy row matching what build_dataset.py would output
    dummy_row = pd.Series({
        "timestamp": int(time.time()),
        "service_id": "frontend",
        "cpu_utilization": 45.2,
        "memory_utilization": 60.5,
        "replica_count": 3,
        "request_rate": 150.0,
        "latency_ms": 25.4
    })
    
    state = ServiceState.from_dataframe_row(dummy_row, source=StateSource.ALIBABA)
    vec = state.to_vector()
    
    assert isinstance(vec, np.ndarray), "Output must be a numpy array"
    assert vec.shape == (VECTOR_DIM,), f"Vector must have shape ({VECTOR_DIM},)"
    assert vec.dtype == np.float32, "Vector must be float32"
    
    print(f"  [+] SIM Validation passed! Vector shape: {vec.shape}, dtype: {vec.dtype}")
    return vec

def validate_live_data():
    """Validates that live Prometheus data conforms to the schema."""
    print("\n[*] Validating LIVE (Prometheus) data schema...")
    
    client = MetricsClient(url="http://localhost:9090")
    
    try:
        state = client.get_service_state("frontend")
        vec = state.to_vector()
        
        assert isinstance(vec, np.ndarray), "Output must be a numpy array"
        assert vec.shape == (VECTOR_DIM,), f"Vector must have shape ({VECTOR_DIM},)"
        assert vec.dtype == np.float32, "Vector must be float32"
        
        print(f"  [+] LIVE Validation passed! Vector shape: {vec.shape}, dtype: {vec.dtype}")
        return vec
    except Exception as e:
        print(f"  [-] LIVE Validation failed or could not connect to Prometheus: {e}")
        print("      (Make sure 'kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n flexascale-monitoring 9090:9090' is running!)")
        return None

if __name__ == "__main__":
    print("==================================================")
    print(" FlexaScale - Schema Match Validation")
    print("==================================================")
    
    sim_vec = validate_sim_data()
    live_vec = validate_live_data()
    
    if sim_vec is not None and live_vec is not None:
        assert sim_vec.shape == live_vec.shape, "Shape mismatch between SIM and LIVE!"
        assert sim_vec.dtype == live_vec.dtype, "Dtype mismatch between SIM and LIVE!"
        print("\n[SUCCESS] Schema match validated perfectly between LIVE and SIM data pipelines!")
    else:
        print("\n[WARNING] Could not fully validate LIVE data. Ensure port-forwarding is active.")
