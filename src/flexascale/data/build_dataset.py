from pathlib import Path

import pandas as pd

from flexascale.data.alibaba import (
    load_resource_data,
    load_rtqps_data,
)

from flexascale.data.preprocessing import (
    merge_service_states,
)

from flexascale.data.schema import (
    ServiceState,
    StateSource,
)


VALIDATION_SAMPLE_SIZE = 500
"""Number of rows sampled for schema validation after the pipeline runs."""



RESOURCE_FILE = Path(
    "data/raw/alibaba/v2021/MSResource_0.csv"
)

RTQPS_FILE = Path(
    "data/raw/alibaba/v2021/MSRTQps_0.csv"
)

OUTPUT_FILE = Path(
    "data/processed/alibaba_service_state.csv"
)


# RTQps uses 60-second timestamps.
TIMESTAMP_INTERVAL = 60_000


def build_resource_state() -> pd.DataFrame:
    """
    Process the full MSResource dataset.

    Resource data is recorded every 30 seconds.
    We keep only timestamps aligned with the 60-second
    RTQps data.

    Instance-level records are first aggregated within
    each chunk and then combined safely across chunks.
    """

    states = []

    chunks = load_resource_data(
        RESOURCE_FILE,
        chunksize=50_000,
    )

    for i, chunk in enumerate(chunks, start=1):

        # Keep only timestamps compatible with RTQps.
        chunk = chunk[
            chunk["timestamp"] % TIMESTAMP_INTERVAL == 0
        ].copy()

        if chunk.empty:
            continue

        # Remove rows without valid identifiers.
        chunk = chunk.dropna(
            subset=[
                "msname",
                "msinstanceid",
            ]
        )

        # Aggregate CPU/memory for each instance.
        instance_state = (
            chunk
            .groupby(
                [
                    "timestamp",
                    "msname",
                    "msinstanceid",
                ],
                as_index=False,
            )
            .agg(
                cpu_utilization=(
                    "instance_cpu_usage",
                    "mean",
                ),
                memory_utilization=(
                    "instance_memory_usage",
                    "mean",
                ),
            )
        )

        states.append(instance_state)

        if i % 20 == 0:
            print(
                f"Resource chunks processed: {i}"
            )

    print("Combining resource chunks...")

    instances = pd.concat(
        states,
        ignore_index=True,
    )

    # A single instance should have one record per
    # timestamp after chunk-level aggregation.
    #
    # If a record was split across chunks, combine its
    # measurements before calculating service state.
    instances = (
        instances
        .groupby(
            [
                "timestamp",
                "msname",
                "msinstanceid",
            ],
            as_index=False,
        )
        .agg(
            cpu_utilization=(
                "cpu_utilization",
                "mean",
            ),
            memory_utilization=(
                "memory_utilization",
                "mean",
            ),
        )
    )

    # Now aggregate instances to services.
    resource_state = (
        instances
        .groupby(
            [
                "timestamp",
                "msname",
            ],
            as_index=False,
        )
        .agg(
            cpu_utilization=(
                "cpu_utilization",
                "mean",
            ),
            memory_utilization=(
                "memory_utilization",
                "mean",
            ),
            replica_count=(
                "msinstanceid",
                "nunique",
            ),
        )
    )

    resource_state = resource_state.rename(
        columns={
            "msname": "service_id"
        }
    )

    resource_state = resource_state.dropna(
        subset=[
            "cpu_utilization",
            "memory_utilization",
        ]
    )

    resource_state = resource_state.sort_values(
        [
            "timestamp",
            "service_id",
        ]
    ).reset_index(drop=True)

    return resource_state


def build_rtqps_state() -> pd.DataFrame:
    """
    Process the full MSRTQps dataset.

    Only provider-side metrics are used:

        providerRPC_MCR -> request_rate
        providerRPC_RT  -> latency_ms
    """

    states = []

    chunks = load_rtqps_data(
        RTQPS_FILE,
        chunksize=50_000,
    )

    for i, chunk in enumerate(chunks, start=1):

        # Keep provider metrics only.
        chunk = chunk[
            chunk["metric"].isin(
                [
                    "providerRPC_MCR",
                    "providerRPC_RT",
                ]
            )
        ].copy()

        if chunk.empty:
            continue

        chunk = chunk.dropna(
            subset=[
                "timestamp",
                "msname",
                "msinstanceid",
                "metric",
                "value",
            ]
        )

        states.append(chunk)

        if i % 20 == 0:
            print(
                f"RTQps chunks processed: {i}"
            )

    print("Combining RTQps chunks...")

    provider = pd.concat(
        states,
        ignore_index=True,
    )

    # Aggregate duplicate measurements for the same
    # timestamp/service/instance/metric.
    provider = (
        provider
        .groupby(
            [
                "timestamp",
                "msname",
                "msinstanceid",
                "metric",
            ],
            as_index=False,
        )
        .agg(
            value=("value", "mean")
        )
    )

    # Request rate.
    request_rate = (
        provider[
            provider["metric"]
            == "providerRPC_MCR"
        ]
        .groupby(
            [
                "timestamp",
                "msname",
            ],
            as_index=False,
        )
        .agg(
            request_rate=("value", "mean")
        )
    )

    # Latency.
    latency = (
        provider[
            provider["metric"]
            == "providerRPC_RT"
        ]
        .groupby(
            [
                "timestamp",
                "msname",
            ],
            as_index=False,
        )
        .agg(
            latency_ms=("value", "mean")
        )
    )

    rtqps_state = request_rate.merge(
        latency,
        on=[
            "timestamp",
            "msname",
        ],
        how="outer",
    )

    rtqps_state = rtqps_state.rename(
        columns={
            "msname": "service_id"
        }
    )

    rtqps_state = rtqps_state.sort_values(
        [
            "timestamp",
            "service_id",
        ]
    ).reset_index(drop=True)

    return rtqps_state


def main():

    print("=== FlexaScale Dataset Builder ===")
    print()

    print("Processing MSResource...")
    resource_state = build_resource_state()

    print(
        f"Resource state rows: "
        f"{len(resource_state):,}"
    )

    print(
        f"Resource services: "
        f"{resource_state['service_id'].nunique():,}"
    )

    print(
        f"Resource timestamps: "
        f"{resource_state['timestamp'].nunique():,}"
    )

    print()

    print("Processing MSRTQps...")
    rtqps_state = build_rtqps_state()

    print(
        f"RTQps state rows: "
        f"{len(rtqps_state):,}"
    )

    print(
        f"RTQps services: "
        f"{rtqps_state['service_id'].nunique():,}"
    )

    print(
        f"RTQps timestamps: "
        f"{rtqps_state['timestamp'].nunique():,}"
    )

    print()

    print("Merging datasets...")

    state = merge_service_states(
        resource_state,
        rtqps_state,
    )

    # Final deterministic ordering.
    state = state.sort_values(
        [
            "timestamp",
            "service_id",
        ]
    ).reset_index(drop=True)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    state.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    print()
    print("=== Final Dataset ===")

    print(
        f"Rows: {len(state):,}"
    )

    print(
        f"Columns: {list(state.columns)}"
    )

    print(
        f"Services: "
        f"{state['service_id'].nunique():,}"
    )

    print(
        f"Timestamps: "
        f"{state['timestamp'].nunique():,}"
    )

    print()
    print("Timestamp range:")

    print(
        state["timestamp"].min(),
        "→",
        state["timestamp"].max(),
    )

    print()
    print("Missing values:")

    print(
        state.isna().sum()
    )

    print()
    print(
        f"Saved to: {OUTPUT_FILE}"
    )

    # Schema validation — spot-check sampled rows against ServiceState.
    # Fails loudly here rather than silently producing invalid observations.
    print()
    print("Validating output against ServiceState schema...")
    _validate_output(state)
    print("  OK: Schema validation passed.")


def _validate_output(df: pd.DataFrame) -> None:
    """
    Spot-check a random sample of the final dataset against ``ServiceState``.

    Raises ``ValueError`` via ``ServiceState.validate()`` if any sampled
    row violates the shared schema contract.

    Args:
        df: The fully merged output DataFrame from ``main()``.
    """
    sample = df.sample(
        n=min(VALIDATION_SAMPLE_SIZE, len(df)),
        random_state=42,
    )

    errors: list[str] = []

    for idx, row in sample.iterrows():
        try:
            ServiceState.from_dataframe_row(
                row,
                source=StateSource.ALIBABA,
            )
        except (ValueError, KeyError) as exc:
            errors.append(f"  Row {idx}: {exc}")

    if errors:
        error_summary = "\n".join(errors[:10])
        raise ValueError(
            f"Schema validation failed on "
            f"{len(errors)} / {len(sample)} sampled rows:\n"
            + error_summary
        )


if __name__ == "__main__":
    main()
