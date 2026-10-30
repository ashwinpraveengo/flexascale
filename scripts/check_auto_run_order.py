#!/usr/bin/env python3
"""Robustness: pair each Auto run with the preceding vs the following default-HPA run of the same scenario."""
import json, glob, math
from flexascale.lab.benchmark import mean_ci
runs = []
for p in sorted(glob.glob('reports/experiments/20261026-*/run.json')):
    r = json.load(open(p, encoding="utf-8"))
    if r['started_at'] < __import__('datetime').datetime(2026,10,26,4,34).timestamp() or not (r.get('summary') or {}).get('complete'):  # clean batch only (>= 04:35)
        continue
    runs.append(r)
rh = lambda r: r['summary']['resources']['replica_hours']
p95 = lambda r: r['summary']['workload']['p95_ms']
by = {}
for r in sorted(runs, key=lambda r: r['started_at']):
    by.setdefault(r['request']['scenario'], []).append(r)
for label, pick in (('preceding HPA', lambda hs, a: [h for h in hs if h['started_at'] < a['started_at']][-1:]),
                    ('following HPA', lambda hs, a: [h for h in hs if h['started_at'] > a['started_at']][:1])):
    d_rh, d_p95 = [], []
    for sc, rs in by.items():
        hs = [r for r in rs if r['request']['controller'] == 'hpa']
        for a in (r for r in rs if r['request']['controller'] == 'auto'):
            h = pick(hs, a)
            if h:
                d_rh.append(100 * (rh(a) - rh(h[0])) / rh(h[0])); d_p95.append(100 * (p95(a) - p95(h[0])) / p95(h[0]))
    m, m2 = mean_ci(d_rh), mean_ci(d_p95)
    print(f"{label:14s} n={m['n']:2d}  replica-h {m['mean']:+.1f}% CI [{m['ci95'][0]:+.1f}, {m['ci95'][1]:+.1f}]  "
          f"p95 {m2['mean']:+.1f}% CI [{m2['ci95'][0]:+.1f}, {m2['ci95'][1]:+.1f}]  all negative: {all(x < 0 for x in d_rh)}")
# drift of the HPA arm across repeats
for sc, rs in sorted(by.items()):
    hs = [round(rh(r), 3) for r in rs if r['request']['controller'] == 'hpa']
    au = [round(rh(r), 3) for r in rs if r['request']['controller'] == 'auto']
    print(f"{sc:20s} HPA replica-h {hs}  Auto {au}")
