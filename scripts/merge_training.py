#!/usr/bin/env python3
"""
Merge per-run training summaries into one (v9 trains its runs as parallel processes, each with its own
--report-dir, so they never write the same file). Afterwards `scripts/train_v7.py --report-dir <out dir>
--select-only` selects among all runs exactly as for v7 (already-trained runs are skipped).

    python scripts/merge_training.py reports/v9/runs/*/training_v7.json --out reports/v9/training_v7.json
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("summaries", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default=None, help="recorded in the merged summary (speed only)")
    args = ap.parse_args()
    out_path = Path(args.out)
    merged = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"runs": {}}
    for p in args.summaries:
        part = json.loads(Path(p).read_text(encoding="utf-8"))
        for name, run in part.get("runs", {}).items():
            if not run.get("best"):
                print(f"{p}: run {name} has no validated checkpoint; not merged")
                continue
            merged["runs"][name] = run
            print(f"merged {name}: best validation reward {run['best']['reward']:.2f}")
    if args.device:
        merged["device"] = args.device
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out_path}: {len(merged['runs'])} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
