"""
Tests for the shared state-vector schema (flexascale.data.schema).
"""

import numpy as np
import pandas as pd
import pytest

from flexascale.data.schema import (
    VECTOR_DIM,
    VECTOR_FIELDS,
    ServiceState,
    StateSource,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_kwargs() -> dict:
    return dict(
        timestamp=1_000_000,
        service_id="orders",
        cpu_utilization=42.5,
        memory_utilization=60.0,
        replica_count=3,
        request_rate=150.0,
        latency_ms=12.3,
        source=StateSource.ALIBABA,
    )


@pytest.fixture
def valid_state(valid_kwargs) -> ServiceState:
    return ServiceState(**valid_kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:

    def test_valid_construction(self, valid_kwargs):
        state = ServiceState(**valid_kwargs)
        assert state.service_id == "orders"
        assert state.source == StateSource.ALIBABA

    def test_default_source_is_alibaba(self, valid_kwargs):
        valid_kwargs.pop("source")
        state = ServiceState(**valid_kwargs)
        assert state.source == StateSource.ALIBABA

    def test_source_tagging(self, valid_kwargs):
        for src in StateSource:
            valid_kwargs["source"] = src
            state = ServiceState(**valid_kwargs)
            assert state.source == src


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_cpu_below_zero(self, valid_kwargs):
        valid_kwargs["cpu_utilization"] = -0.1
        with pytest.raises(ValueError, match="cpu_utilization"):
            ServiceState(**valid_kwargs)

    def test_cpu_above_100(self, valid_kwargs):
        valid_kwargs["cpu_utilization"] = 100.1
        with pytest.raises(ValueError, match="cpu_utilization"):
            ServiceState(**valid_kwargs)

    def test_cpu_boundary_values_accepted(self, valid_kwargs):
        for boundary in (0.0, 100.0):
            valid_kwargs["cpu_utilization"] = boundary
            ServiceState(**valid_kwargs)  # must not raise

    def test_memory_below_zero(self, valid_kwargs):
        valid_kwargs["memory_utilization"] = -1.0
        with pytest.raises(ValueError, match="memory_utilization"):
            ServiceState(**valid_kwargs)

    def test_memory_above_100(self, valid_kwargs):
        valid_kwargs["memory_utilization"] = 101.0
        with pytest.raises(ValueError, match="memory_utilization"):
            ServiceState(**valid_kwargs)

    def test_replica_count_zero(self, valid_kwargs):
        valid_kwargs["replica_count"] = 0
        with pytest.raises(ValueError, match="replica_count"):
            ServiceState(**valid_kwargs)

    def test_replica_count_negative(self, valid_kwargs):
        valid_kwargs["replica_count"] = -1
        with pytest.raises(ValueError, match="replica_count"):
            ServiceState(**valid_kwargs)

    def test_replica_count_one_accepted(self, valid_kwargs):
        valid_kwargs["replica_count"] = 1
        ServiceState(**valid_kwargs)  # must not raise

    def test_request_rate_negative(self, valid_kwargs):
        valid_kwargs["request_rate"] = -0.01
        with pytest.raises(ValueError, match="request_rate"):
            ServiceState(**valid_kwargs)

    def test_request_rate_zero_accepted(self, valid_kwargs):
        valid_kwargs["request_rate"] = 0.0
        ServiceState(**valid_kwargs)  # must not raise

    def test_latency_negative(self, valid_kwargs):
        valid_kwargs["latency_ms"] = -1.0
        with pytest.raises(ValueError, match="latency_ms"):
            ServiceState(**valid_kwargs)

    def test_latency_zero_accepted(self, valid_kwargs):
        valid_kwargs["latency_ms"] = 0.0
        ServiceState(**valid_kwargs)  # must not raise

    def test_empty_service_id(self, valid_kwargs):
        valid_kwargs["service_id"] = ""
        with pytest.raises(ValueError, match="service_id"):
            ServiceState(**valid_kwargs)

    def test_whitespace_service_id(self, valid_kwargs):
        valid_kwargs["service_id"] = "   "
        with pytest.raises(ValueError, match="service_id"):
            ServiceState(**valid_kwargs)


# ---------------------------------------------------------------------------
# to_vector()
# ---------------------------------------------------------------------------

class TestToVector:

    def test_shape(self, valid_state):
        vec = valid_state.to_vector()
        assert vec.shape == (VECTOR_DIM,)

    def test_dtype(self, valid_state):
        vec = valid_state.to_vector()
        assert vec.dtype == np.float32

    def test_vector_dim_constant(self):
        assert VECTOR_DIM == 5

    def test_vector_fields_constant(self):
        assert VECTOR_FIELDS == (
            "cpu_utilization",
            "memory_utilization",
            "replica_count",
            "request_rate",
            "latency_ms",
        )

    def test_vector_values(self, valid_state):
        vec = valid_state.to_vector()
        assert vec[0] == pytest.approx(valid_state.cpu_utilization)
        assert vec[1] == pytest.approx(valid_state.memory_utilization)
        assert vec[2] == pytest.approx(float(valid_state.replica_count))
        assert vec[3] == pytest.approx(valid_state.request_rate)
        assert vec[4] == pytest.approx(valid_state.latency_ms)

    def test_vector_layout_matches_vector_fields(self, valid_state):
        """Ensure VECTOR_FIELDS indices match actual to_vector() output."""
        vec = valid_state.to_vector()
        for i, field_name in enumerate(VECTOR_FIELDS):
            expected = float(getattr(valid_state, field_name))
            assert vec[i] == pytest.approx(expected), (
                f"Index {i} ({field_name}) mismatch"
            )


# ---------------------------------------------------------------------------
# from_dict()
# ---------------------------------------------------------------------------

class TestFromDict:

    def test_basic_roundtrip(self, valid_kwargs):
        d = {
            "timestamp": valid_kwargs["timestamp"],
            "service_id": valid_kwargs["service_id"],
            "cpu_utilization": valid_kwargs["cpu_utilization"],
            "memory_utilization": valid_kwargs["memory_utilization"],
            "replica_count": valid_kwargs["replica_count"],
            "request_rate": valid_kwargs["request_rate"],
            "latency_ms": valid_kwargs["latency_ms"],
        }
        state = ServiceState.from_dict(d, source=StateSource.LIVE)
        assert state.service_id == valid_kwargs["service_id"]
        assert state.source == StateSource.LIVE

    def test_default_source_is_live(self, valid_kwargs):
        d = {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        state = ServiceState.from_dict(d)
        assert state.source == StateSource.LIVE

    def test_missing_key_raises(self, valid_kwargs):
        d = {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        d.pop("latency_ms")
        with pytest.raises(KeyError):
            ServiceState.from_dict(d)

    def test_type_coercion(self, valid_kwargs):
        d = {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        d["replica_count"] = "3"  # string instead of int
        d["cpu_utilization"] = "42.5"  # string instead of float
        state = ServiceState.from_dict(d)
        assert state.replica_count == 3
        assert state.cpu_utilization == pytest.approx(42.5)


# ---------------------------------------------------------------------------
# from_dataframe_row()
# ---------------------------------------------------------------------------

class TestFromDataframeRow:

    def test_basic_roundtrip(self, valid_kwargs):
        row = pd.Series(
            {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        )
        state = ServiceState.from_dataframe_row(row, source=StateSource.ALIBABA)
        assert state.service_id == valid_kwargs["service_id"]
        assert state.source == StateSource.ALIBABA

    def test_default_source_is_alibaba(self, valid_kwargs):
        row = pd.Series(
            {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        )
        state = ServiceState.from_dataframe_row(row)
        assert state.source == StateSource.ALIBABA

    def test_missing_field_raises(self, valid_kwargs):
        d = {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        d.pop("replica_count")
        row = pd.Series(d)
        with pytest.raises(KeyError):
            ServiceState.from_dataframe_row(row)

    def test_validates_on_construction(self, valid_kwargs):
        d = {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
        d["cpu_utilization"] = 999.9  # invalid
        row = pd.Series(d)
        with pytest.raises(ValueError, match="cpu_utilization"):
            ServiceState.from_dataframe_row(row)

    def test_from_dataframe_slice(self, valid_kwargs):
        """Simulate iterating over a real DataFrame."""
        records = [
            {k: valid_kwargs[k] for k in valid_kwargs if k != "source"}
            for _ in range(5)
        ]
        df = pd.DataFrame(records)
        for _, row in df.iterrows():
            state = ServiceState.from_dataframe_row(row)
            vec = state.to_vector()
            assert vec.shape == (VECTOR_DIM,)
            assert vec.dtype == np.float32


# ---------------------------------------------------------------------------
# StateSource enum
# ---------------------------------------------------------------------------

class TestStateSource:

    def test_all_sources_defined(self):
        names = {s.value for s in StateSource}
        assert names == {"alibaba", "live", "sim"}

    def test_str_enum_values(self):
        assert StateSource.ALIBABA == "alibaba"
        assert StateSource.LIVE == "live"
        assert StateSource.SIM == "sim"


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------

class TestRepr:

    def test_repr_contains_service_id(self, valid_state):
        assert "orders" in repr(valid_state)

    def test_repr_contains_source(self, valid_state):
        assert "alibaba" in repr(valid_state)
