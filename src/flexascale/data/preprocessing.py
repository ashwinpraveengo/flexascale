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


def enrich_service_state_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich merged telemetry DataFrame with all 5 schema categories defined by ServiceState:
    1. Time: submit_time, start_time, finish_time, completion_time, wait_time, makespan
    2. CPU / Memory: cpu_memory_ratio
    3. Hardware: cpu_capacity, gpu_count, gpu_utilization, gpu_memory
    4. Performance: jct, acceptance_ratio
    5. Reliability: successful_requests, failed_requests, error_rate, success_rate
    6. Metadata: source ('alibaba')
    """
    enriched = df.copy()

    # Metadata & Source tagging
    if "source" not in enriched.columns:
        enriched["source"] = "alibaba"

    # 1. Time fields
    if "submit_time" not in enriched.columns:
        enriched["submit_time"] = enriched["timestamp"].astype(float)
    if "start_time" not in enriched.columns:
        enriched["start_time"] = enriched["submit_time"]
    if "completion_time" not in enriched.columns:
        enriched["completion_time"] = enriched["latency_ms"].clip(lower=0.0)
    if "finish_time" not in enriched.columns:
        enriched["finish_time"] = enriched["start_time"] + enriched["completion_time"]
    if "wait_time" not in enriched.columns:
        enriched["wait_time"] = 0.0
    if "makespan" not in enriched.columns:
        enriched["makespan"] = enriched["completion_time"]

    # 2. CPU / Memory fields
    if "cpu_memory_ratio" not in enriched.columns:
        safe_mem = enriched["memory_utilization"].clip(lower=1e-6)
        enriched["cpu_memory_ratio"] = (enriched["cpu_utilization"] / safe_mem).astype(float)

    # 3. Hardware fields
    if "cpu_capacity" not in enriched.columns:
        enriched["cpu_capacity"] = enriched["replica_count"].astype(float)
    if "gpu_count" not in enriched.columns:
        enriched["gpu_count"] = 0
    if "gpu_utilization" not in enriched.columns:
        enriched["gpu_utilization"] = 0.0
    if "gpu_memory" not in enriched.columns:
        enriched["gpu_memory"] = 0.0

    # 4. Performance fields
    if "jct" not in enriched.columns:
        enriched["jct"] = enriched["completion_time"]
    if "acceptance_ratio" not in enriched.columns:
        enriched["acceptance_ratio"] = 1.0

    # 5. Reliability fields
    if "successful_requests" not in enriched.columns:
        enriched["successful_requests"] = enriched["request_rate"].astype(float)
    if "failed_requests" not in enriched.columns:
        enriched["failed_requests"] = 0.0
    if "error_rate" not in enriched.columns:
        enriched["error_rate"] = 0.0
    if "success_rate" not in enriched.columns:
        enriched["success_rate"] = 1.0

    # Reorder columns with core fields first, followed by extended categories
    core_cols = [
        "timestamp",
        "service_id",
        "cpu_utilization",
        "memory_utilization",
        "replica_count",
        "request_rate",
        "latency_ms",
        "source",
        "submit_time",
        "start_time",
        "finish_time",
        "completion_time",
        "wait_time",
        "makespan",
        "cpu_memory_ratio",
        "cpu_capacity",
        "gpu_count",
        "gpu_utilization",
        "gpu_memory",
        "jct",
        "acceptance_ratio",
        "successful_requests",
        "failed_requests",
        "error_rate",
        "success_rate",
    ]
    # Include any additional columns not in core_cols
    ordered_cols = [c for c in core_cols if c in enriched.columns] + [
        c for c in enriched.columns if c not in core_cols
    ]
    return enriched[ordered_cols]


def merge_service_states(
    resource_state: pd.DataFrame,
    rtqps_state: pd.DataFrame,
    enrich: bool = True,
) -> pd.DataFrame:
    """
    Merge resource and provider RPC metrics.

    Only services present in both datasets are retained.
    If enrich is True, populates all extended ServiceState schema fields.
    """

    merged = resource_state.merge(
        rtqps_state,
        on=["timestamp", "service_id"],
        how="inner",
    )

    if enrich:
        merged = enrich_service_state_schema(merged)

    merged = merged.sort_values(
        ["timestamp", "service_id"]
    ).reset_index(drop=True)

    return merged

