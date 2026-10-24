# Data-Quality Report: Alibaba Microservices v2021 Service States

Generated 2026-10-22 23:38:17 by `scripts/data_quality_report.py`.

## Provenance

- Source: Alibaba cluster-trace-microservices-v2021 (https://github.com/alibaba/clusterdata)
- Raw files: data/raw/alibaba/v2021/MSResource_0.csv, data/raw/alibaba/v2021/MSRTQps_0.csv (first 30-minute shard of the 12-hour trace; MSResource_0 2.9 GB, MSRTQps_0 2.8 GB)
- Builder: `python -m flexascale.data.build_dataset`; unit migration: `scripts/fix_dataset_units.py` (fraction_to_percent_v1)
- Not used: MSCallGraph (call-dependency) files. They were not downloaded, so the training graph is a fixed chain, not the real call graph.

## Shape

- 36,355 rows = 1,213 services x 30 timestamps (sampling interval [60000] ms, span 29 min)
- Services present at every timestamp (used for random episode sampling): 1,178

## Units

- `cpu_utilization`: percent of container CPU allocation (0-100)
- `memory_utilization`: percent of container memory allocation (0-100)
- `replica_count`: distinct msinstanceid per service per timestamp
- `request_rate`: providerRPC_MCR (mean over instances)
- `latency_ms`: providerRPC_RT (mean over instances, ms)

Defect found and fixed: the processed CSVs stored CPU and memory as fractions (0-1) while the schema, simulator and live telemetry use percent. All four files were rescaled by 100 (recorded in `PROVENANCE.json`) and the builder now writes percent. The original v1 model was trained on the fractional data.

## Splits (temporal, by timestamp)

| Split | Rows | Services | Timestamps | First ts (ms) | Last ts (ms) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| train | 25,446 | 1,213 | 21 | 0 | 1,200,000 |
| val | 4,847 | 1,213 | 4 | 1,260,000 | 1,440,000 |
| test | 6,062 | 1,213 | 5 | 1,500,000 | 1,740,000 |

- Timestamp overlap between splits: {'train&val': 0, 'train&test': 0, 'val&test': 0} (0 everywhere = no temporal leakage)
- Splits partition the full dataset exactly: True
- The same services appear in all splits (temporal split); evaluation tests generalisation to later time, not to unseen services.

## Feature distributions

| Feature | Mean | Std | Min | p5 | Median | p95 | Max | Missing |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cpu_utilization | 13.66 | 9.12 | 0.37 | 4.06 | 11.14 | 31.71 | 87.45 | 0 |
| memory_utilization | 61.23 | 12.74 | 14.75 | 39.96 | 62.34 | 80.67 | 95.73 | 0 |
| replica_count | 75.72 | 168.76 | 1.00 | 2.00 | 23.00 | 330.00 | 2716.00 | 0 |
| request_rate | 65.69 | 144.70 | 0.00 | 0.01 | 15.78 | 297.23 | 1981.16 | 0 |
| latency_ms | 37.14 | 87.26 | 0.00 | 0.34 | 11.92 | 160.74 | 2902.50 | 0 |

## Observations relevant to modelling

- 3.7% of rows have zero request rate (idle services).
- 9.5% of rows already exceed a 100 ms latency target at trace utilisation.
- 31.7% of rows have more than 50 instances; the live cluster uses 1-10. The simulator's `normalized` demand model rescales each service's demand into the 1-10 replica range instead of clipping.
- CPU utilisation is low (median ~13% of allocation); without rescaling a CPU-target policy would only ever scale down.
- 30 timestamps per service: episodes are short (21 training steps), so randomised service sampling and initial replicas provide the training diversity.

## Additional Alibaba data

Not added. The next shards (MSResource_1.., MSRTQps_1..) are about 1.4 GB / 0.85 GB compressed each, and MSCallGraph is larger still. No experiment here showed that more trace time would improve the model (the limiting factor is the reward design, see reports/simulation_evaluation.md), so the download was not justified for this release.
