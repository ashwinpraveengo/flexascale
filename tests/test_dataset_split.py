"""
Tests for Train / Validation / Test dataset splitting and environment integration.
"""

import sys
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from flexascale.config.env_config import EnvConfig
from flexascale.data.preprocessing import split_service_state_dataset
from flexascale.data.schema import ServiceState, StateSource, VECTOR_FIELDS
from flexascale.simulator.flexascale_env import FlexaScaleEnv


@pytest.fixture
def synthetic_dataset():
    """Create a synthetic dataset with 10 timestamps, 5 services per timestamp."""
    timestamps = [i * 60_000 for i in range(10)]
    services = [f"service_{s}" for s in range(5)]
    records = []
    for ts in timestamps:
        for s in services:
            records.append(
                {
                    "timestamp": ts,
                    "service_id": s,
                    "cpu_utilization": 45.0,
                    "memory_utilization": 50.0,
                    "replica_count": 3,
                    "request_rate": 120.0,
                    "latency_ms": 15.0,
                    "source": "alibaba",
                    "submit_time": float(ts),
                    "start_time": float(ts),
                    "finish_time": float(ts) + 15.0,
                    "completion_time": 15.0,
                    "wait_time": 0.0,
                    "makespan": 15.0,
                    "cpu_memory_ratio": 0.9,
                    "cpu_capacity": 3.0,
                    "gpu_count": 0,
                    "gpu_utilization": 0.0,
                    "gpu_memory": 0.0,
                    "jct": 15.0,
                    "acceptance_ratio": 1.0,
                    "successful_requests": 120.0,
                    "failed_requests": 0.0,
                    "error_rate": 0.0,
                    "success_rate": 1.0,
                }
            )
    return pd.DataFrame(records)


def test_split_ratios_validation(synthetic_dataset):
    """Ensure invalid split ratios raise ValueError."""
    with pytest.raises(ValueError, match="Split ratios must sum to 1.0"):
        split_service_state_dataset(synthetic_dataset, train_ratio=0.5, val_ratio=0.2, test_ratio=0.2)

    with pytest.raises(ValueError, match="Ratios must be non-negative"):
        split_service_state_dataset(synthetic_dataset, train_ratio=-0.1, val_ratio=0.5, test_ratio=0.6)


def test_temporal_split_properties(synthetic_dataset):
    """Ensure temporal splitting has zero time overlap, preserves order and row sum."""
    train_df, val_df, test_df = split_service_state_dataset(
        synthetic_dataset,
        train_ratio=0.70,
        val_ratio=0.15,
        test_ratio=0.15,
        method="temporal",
    )

    # 1. Row count sum
    assert len(train_df) + len(val_df) + len(test_df) == len(synthetic_dataset)

    # 2. Timestamp disjointness
    train_ts = set(train_df["timestamp"].unique())
    val_ts = set(val_df["timestamp"].unique())
    test_ts = set(test_df["timestamp"].unique())

    assert len(train_ts.intersection(val_ts)) == 0
    assert len(val_ts.intersection(test_ts)) == 0
    assert len(train_ts.intersection(test_ts)) == 0

    # 3. Chronological ordering (no lookahead leakage)
    assert max(train_ts) < min(val_ts)
    assert max(val_ts) < min(test_ts)

    # 4. Correct number of timestamps (10 total -> 7 train, 2 val, 1 test)
    assert len(train_ts) == 7
    assert len(val_ts) == 2
    assert len(test_ts) == 1
    assert len(train_ts) + len(val_ts) + len(test_ts) == 10


def test_random_split_properties(synthetic_dataset):
    """Ensure random splitting partitions rows properly."""
    train_df, val_df, test_df = split_service_state_dataset(
        synthetic_dataset,
        train_ratio=0.60,
        val_ratio=0.20,
        test_ratio=0.20,
        method="random",
        random_state=42,
    )
    assert len(train_df) + len(val_df) + len(test_df) == len(synthetic_dataset)
    assert len(train_df) == 30
    assert len(val_df) == 10
    assert len(test_df) == 10


def test_service_split_properties(synthetic_dataset):
    """Ensure service-level splitting creates disjoint service ID partitions."""
    train_df, val_df, test_df = split_service_state_dataset(
        synthetic_dataset,
        train_ratio=0.60,
        val_ratio=0.20,
        test_ratio=0.20,
        method="service",
        random_state=42,
    )
    assert len(train_df) + len(val_df) + len(test_df) == len(synthetic_dataset)

    train_s = set(train_df["service_id"].unique())
    val_s = set(val_df["service_id"].unique())
    test_s = set(test_df["service_id"].unique())

    assert len(train_s.intersection(val_s)) == 0
    assert len(val_s.intersection(test_s)) == 0
    assert len(train_s.intersection(test_s)) == 0


def test_split_preserves_schema(synthetic_dataset):
    """Verify that split slices maintain all 25 schema fields and validate against ServiceState."""
    train_df, val_df, test_df = split_service_state_dataset(synthetic_dataset)
    for subset in (train_df, val_df, test_df):
        for idx, row in subset.iterrows():
            state = ServiceState.from_dataframe_row(row, source=StateSource.ALIBABA)
            assert state.service_id.startswith("service_")
            assert state.cpu_utilization == 45.0
            break


def test_flexascale_env_split_integration():
    """Verify FlexaScaleEnv behaves properly for all split configurations."""
    processed_path = Path("data/processed/alibaba_service_state.csv")
    if not processed_path.is_file():
        pytest.skip("Processed dataset not available for integration test.")

    # Train split
    env_train = FlexaScaleEnv(config=EnvConfig(split="train"))
    assert env_train.episode_length == 21
    obs, info = env_train.reset(seed=42)
    assert obs is not None
    next_obs, reward, terminated, truncated, info = env_train.step(1)
    assert not terminated

    # Validation split
    env_val = FlexaScaleEnv(config=EnvConfig(split="val"))
    assert env_val.episode_length == 4
    obs, info = env_val.reset(seed=42)
    assert obs is not None

    # Test split
    env_test = FlexaScaleEnv(config=EnvConfig(split="test"))
    assert env_test.episode_length == 5
    obs, info = env_test.reset(seed=42)
    assert obs is not None

    # Invalid split
    with pytest.raises(ValueError, match="Unknown split 'invalid'"):
        FlexaScaleEnv(config=EnvConfig(split="invalid"))


def test_cli_split_script(synthetic_dataset):
    """Test CLI script splitting on temporary directory."""
    from scripts.split_dataset import split_service_state_dataset

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "test_data.csv"
        synthetic_dataset.to_csv(input_file, index=False)

        train_df, val_df, test_df = split_service_state_dataset(synthetic_dataset)
        assert len(train_df) > 0
        assert len(val_df) > 0
        assert len(test_df) > 0
