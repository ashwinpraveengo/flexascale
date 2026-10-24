#!/usr/bin/env python3
"""
Data-quality report for the processed Alibaba service-state dataset.

Writes reports/data_quality_report.md (and .json) with provenance, schema/units,
split sizes and time ranges (leakage check), feature distributions, missing
values and the characteristics relevant to the simulator.
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROC = Path("data/processed")
FIELDS = ["cpu_utilization", "memory_utilization", "replica_count", "request_rate", "latency_ms"]


def main() -> int:
    full = pd.read_csv(PROC / "alibaba_service_state.csv")
    splits = {s: pd.read_csv(PROC / f"alibaba_service_state_{s}.csv") for s in ("train", "val", "test")}
    prov = json.loads((PROC / "PROVENANCE.json").read_text())

    ts = np.sort(full["timestamp"].unique())
    interval = np.diff(ts)
    per_service = full.groupby("service_id")["timestamp"].nunique()
    complete = per_service[per_service == len(ts)]

    split_rows = []
    ts_sets = {}
    for name, df in splits.items():
        t = np.sort(df["timestamp"].unique())
        ts_sets[name] = set(t)
        split_rows.append((name, len(df), df["service_id"].nunique(), len(t), int(t.min()), int(t.max())))
    overlap = {f"{a}&{b}": len(ts_sets[a] & ts_sets[b]) for a, b in (("train", "val"), ("train", "test"), ("val", "test"))}
    union_ok = sum(r[1] for r in split_rows) == len(full)

    desc = full[FIELDS].describe(percentiles=[0.05, 0.5, 0.95]).T
    missing = full[FIELDS].isna().sum()
    zero_rate = float((full["request_rate"] == 0).mean())
    over_slo = float((full["latency_ms"] > 100).mean())
    big_replicas = float((full["replica_count"] > 50).mean())

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provenance": prov,
        "rows": int(len(full)),
        "services": int(full["service_id"].nunique()),
        "timestamps": int(len(ts)),
        "sampling_interval_ms": sorted(set(int(x) for x in interval)),
        "span_minutes": float((ts[-1] - ts[0]) / 60000.0),
        "services_present_at_every_timestamp": int(len(complete)),
        "splits": [dict(zip(["split", "rows", "services", "timestamps", "first_ts", "last_ts"], r)) for r in split_rows],
        "split_timestamp_overlap": overlap,
        "splits_partition_full_dataset": bool(union_ok),
        "missing_values": {k: int(v) for k, v in missing.items()},
        "share_zero_request_rate": zero_rate,
        "share_latency_over_100ms": over_slo,
        "share_replicas_over_50": big_replicas,
        "distributions": {f: {k: float(desc.loc[f, k]) for k in ("mean", "std", "min", "5%", "50%", "95%", "max")} for f in FIELDS},
    }
    Path("reports/data_quality_report.json").write_text(json.dumps(report, indent=2, default=str))

    L = [
        "# Data-Quality Report: Alibaba Microservices v2021 Service States",
        "",
        f"Generated {report['generated_at']} by `scripts/data_quality_report.py`.",
        "",
        "## Provenance",
        "",
        f"- Source: {prov.get('source')}",
        f"- Raw files: {', '.join(prov.get('raw_files', []))} (first 30-minute shard of the 12-hour trace; MSResource_0 2.9 GB, MSRTQps_0 2.8 GB)",
        f"- Builder: `{prov.get('builder')}`; unit migration: `scripts/fix_dataset_units.py` "
        f"({', '.join(m['name'] for m in prov.get('migrations', [])) or 'none'})",
        "- Not used: MSCallGraph (call-dependency) files. They were not downloaded, so the training graph is a fixed chain, not the real call graph.",
        "",
        "## Shape",
        "",
        f"- {report['rows']:,} rows = {report['services']:,} services x {report['timestamps']} timestamps "
        f"(sampling interval {report['sampling_interval_ms']} ms, span {report['span_minutes']:.0f} min)",
        f"- Services present at every timestamp (used for random episode sampling): {report['services_present_at_every_timestamp']:,}",
        "",
        "## Units",
        "",
    ]
    for k, v in prov.get("units", {}).items():
        L.append(f"- `{k}`: {v}")
    L += [
        "",
        "Defect found and fixed: the processed CSVs stored CPU and memory as fractions (0-1) while the schema, simulator "
        "and live telemetry use percent. All four files were rescaled by 100 (recorded in `PROVENANCE.json`) and the builder now "
        "writes percent. The original v1 model was trained on the fractional data.",
        "",
        "## Splits (temporal, by timestamp)",
        "",
        "| Split | Rows | Services | Timestamps | First ts (ms) | Last ts (ms) |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in split_rows:
        L.append(f"| {r[0]} | {r[1]:,} | {r[2]:,} | {r[3]} | {r[4]:,} | {r[5]:,} |")
    L += [
        "",
        f"- Timestamp overlap between splits: {overlap} (0 everywhere = no temporal leakage)",
        f"- Splits partition the full dataset exactly: {union_ok}",
        "- The same services appear in all splits (temporal split); evaluation tests generalisation to later time, not to unseen services.",
        "",
        "## Feature distributions",
        "",
        "| Feature | Mean | Std | Min | p5 | Median | p95 | Max | Missing |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for f in FIELDS:
        d = report["distributions"][f]
        L.append(f"| {f} | {d['mean']:.2f} | {d['std']:.2f} | {d['min']:.2f} | {d['5%']:.2f} | {d['50%']:.2f} | {d['95%']:.2f} | {d['max']:.2f} | {missing[f]} |")
    L += [
        "",
        "## Observations relevant to modelling",
        "",
        f"- {100 * zero_rate:.1f}% of rows have zero request rate (idle services).",
        f"- {100 * over_slo:.1f}% of rows already exceed a 100 ms latency target at trace utilisation.",
        f"- {100 * big_replicas:.1f}% of rows have more than 50 instances; the live cluster uses 1-10. The simulator's "
        "`normalized` demand model rescales each service's demand into the 1-10 replica range instead of clipping.",
        "- CPU utilisation is low (median ~13% of allocation); without rescaling a CPU-target policy would only ever scale down.",
        "- 30 timestamps per service: episodes are short (21 training steps), so randomised service sampling and initial "
        "replicas provide the training diversity.",
        "",
        "## Additional Alibaba data",
        "",
        "Not added. The next shards (MSResource_1.., MSRTQps_1..) are about 1.4 GB / 0.85 GB compressed each, and MSCallGraph is "
        "larger still. No experiment here showed that more trace time would improve the model (the limiting factor is the reward "
        "design, see reports/simulation_evaluation.md), so the download was not justified for this release.",
    ]
    Path("reports/data_quality_report.md").write_text("\n".join(L) + "\n")
    print("Wrote reports/data_quality_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
