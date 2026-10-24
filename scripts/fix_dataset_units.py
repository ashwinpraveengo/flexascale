#!/usr/bin/env python3
"""
Migrate processed Alibaba service-state CSVs from fractional to percent units.

The original pipeline wrote ``cpu_utilization`` and ``memory_utilization`` as
fractions (0-1, as reported by the v2021 MSResource trace), while the schema,
the simulator (CPU target 70) and live Prometheus telemetry all use percent
(0-100). This script rescales the existing processed files in place so the
2.8 GB raw trace does not have to be reprocessed.

Idempotent: a file whose CPU/memory columns already exceed 1.0 is left alone.
A provenance record is written to ``data/processed/PROVENANCE.json``.

Usage:
    python scripts/fix_dataset_units.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

PROCESSED_DIR = Path("data/processed")
FILES = [
    "alibaba_service_state.csv",
    "alibaba_service_state_train.csv",
    "alibaba_service_state_val.csv",
    "alibaba_service_state_test.csv",
]
UNIT_COLUMNS = ["cpu_utilization", "memory_utilization"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def migrate(path: Path, dry_run: bool) -> dict:
    df = pd.read_csv(path)
    maxima = {c: float(df[c].max()) for c in UNIT_COLUMNS}
    if all(v <= 1.0 for v in maxima.values()):
        action = "converted_fraction_to_percent"
        if not dry_run:
            for c in UNIT_COLUMNS:
                df[c] = df[c] * 100.0
            df.to_csv(path, index=False)
    else:
        action = "already_percent"
    return {
        "file": str(path),
        "rows": int(len(df)),
        "action": action,
        "max_before": maxima,
        "sha256_after": sha256(path) if not dry_run else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    results = []
    for name in FILES:
        path = PROCESSED_DIR / name
        if not path.is_file():
            print(f"SKIP {path} (missing)")
            continue
        res = migrate(path, args.dry_run)
        results.append(res)
        print(f"{res['action']:<32} {path} rows={res['rows']} max_before={res['max_before']}")

    if not args.dry_run and results:
        prov_path = PROCESSED_DIR / "PROVENANCE.json"
        prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}
        prov.update({
            "source": "Alibaba cluster-trace-microservices-v2021 (https://github.com/alibaba/clusterdata)",
            "raw_files": [
                "data/raw/alibaba/v2021/MSResource_0.csv",
                "data/raw/alibaba/v2021/MSRTQps_0.csv",
            ],
            "builder": "python -m flexascale.data.build_dataset",
            "units": {
                "cpu_utilization": "percent of container CPU allocation (0-100)",
                "memory_utilization": "percent of container memory allocation (0-100)",
                "replica_count": "distinct msinstanceid per service per timestamp",
                "request_rate": "providerRPC_MCR (mean over instances)",
                "latency_ms": "providerRPC_RT (mean over instances, ms)",
            },
            "sampling_interval_ms": 60000,
        })
        history = prov.setdefault("migrations", [])
        if any(r["action"] == "converted_fraction_to_percent" for r in results):
            history.append({
                "name": "fraction_to_percent_v1",
                "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "columns": UNIT_COLUMNS,
                "factor": 100.0,
                "files": results,
            })
        prov_path.write_text(json.dumps(prov, indent=2) + "\n")
        print(f"Provenance written to {prov_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
