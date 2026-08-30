from pathlib import Path

import pandas as pd


RESOURCE_COLUMNS = [
    "msname",
    "msinstanceid",
    "nodeid",
    "instance_cpu_usage",
    "instance_memory_usage",
    "timestamp",
]

RTQPS_COLUMNS = [
    "timestamp",
    "msname",
    "msinstanceid",
    "metric",
    "value",
]


def load_resource_data(
    file_path: str | Path,
    chunksize: int = 50_000,
):
    """
    Stream Alibaba MSResource data in chunks.
    """

    return pd.read_csv(
        file_path,
        usecols=RESOURCE_COLUMNS,
        chunksize=chunksize,
    )


def load_rtqps_data(
    file_path: str | Path,
    chunksize: int = 50_000,
):
    """
    Stream Alibaba MSRTQps data in chunks.

    Each record contains a timestamp, service,
    instance, metric type, and metric value.
    """

    return pd.read_csv(
        file_path,
        usecols=RTQPS_COLUMNS,
        chunksize=chunksize,
    )
