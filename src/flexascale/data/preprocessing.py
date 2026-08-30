import pandas as pd


def aggregate_to_service_state(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert Alibaba instance-level resource metrics into
    service-level state.

    Aggregation is performed for each timestamp and service.
    """

    required_columns = {
        "timestamp",
        "msname",
        "msinstanceid",
        "instance_cpu_usage",
        "instance_memory_usage",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    clean = df.dropna(
        subset=["msname", "msinstanceid"]
    ).copy()

    state = (
        clean
        .groupby(["timestamp", "msname"], as_index=False)
        .agg(
            cpu_utilization=(
                "instance_cpu_usage",
                "mean",
            ),
            memory_utilization=(
                "instance_memory_usage",
                "mean",
            ),
            replica_count=(
                "msinstanceid",
                "nunique",
            ),
        )
    )

    state = state.rename(
        columns={"msname": "service_id"}
    )

    state = state.dropna(
        subset=[
            "cpu_utilization",
            "memory_utilization",
        ]
    )

    state = state.sort_values(
        ["timestamp", "service_id"]
    ).reset_index(drop=True)

    return state


def aggregate_rtqps_to_service_state(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Convert Alibaba MSRTQps provider metrics into
    service-level request rate and latency.

    providerRPC_MCR -> request_rate
    providerRPC_RT  -> latency_ms
    """

    required_columns = {
        "timestamp",
        "msname",
        "msinstanceid",
        "metric",
        "value",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    clean = df.dropna(
        subset=[
            "timestamp",
            "msname",
            "msinstanceid",
            "metric",
            "value",
        ]
    ).copy()

    provider = clean[
        clean["metric"].isin(
            [
                "providerRPC_MCR",
                "providerRPC_RT",
            ]
        )
    ]

    request_rate = (
        provider[
            provider["metric"] == "providerRPC_MCR"
        ]
        .groupby(
            ["timestamp", "msname"],
            as_index=False,
        )
        .agg(
            request_rate=("value", "mean")
        )
    )

    latency = (
        provider[
            provider["metric"] == "providerRPC_RT"
        ]
        .groupby(
            ["timestamp", "msname"],
            as_index=False,
        )
        .agg(
            latency_ms=("value", "mean")
        )
    )

    state = request_rate.merge(
        latency,
        on=["timestamp", "msname"],
        how="outer",
    )

    state = state.rename(
        columns={"msname": "service_id"}
    )

    state = state.sort_values(
        ["timestamp", "service_id"]
    ).reset_index(drop=True)

    return state


def merge_service_states(
    resource_state: pd.DataFrame,
    rtqps_state: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge resource and provider RPC metrics.

    Only services present in both datasets are retained.
    """

    merged = resource_state.merge(
        rtqps_state,
        on=["timestamp", "service_id"],
        how="inner",
    )

    merged = merged.sort_values(
        ["timestamp", "service_id"]
    ).reset_index(drop=True)

    return merged
