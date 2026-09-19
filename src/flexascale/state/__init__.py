"""
FlexaScale Live State Aggregator & Graph Inference.

Provides online telemetry aggregation, schema vector transformation,
and dynamic caller-callee dependency graph inference with EMA decay.
"""

from flexascale.state.graph_inference import LiveGraphInference
from flexascale.state.live_builder import LiveClusterState, LiveStateBuilder

__all__ = [
    "LiveGraphInference",
    "LiveStateBuilder",
    "LiveClusterState",
]
