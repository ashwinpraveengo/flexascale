#!/usr/bin/env python3
"""
CLI utility to split a FlexaScale ServiceState dataset into Train, Validation, and Test sets.

Usage:
    python scripts/split_dataset.py
    python scripts/split_dataset.py --method temporal --train-ratio 0.70 --val-ratio 0.15 --test-ratio 0.15
    python scripts/split_dataset.py --method random --seed 123
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import pandas as pd

# Add src to sys.path so flexascale packages are discoverable
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from flexascale.data.preprocessing import split_service_state_dataset
from flexascale.data.schema import ServiceState, StateSource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split FlexaScale ServiceState dataset into Train, Validation, and Test subsets."
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data/processed/alibaba_service_state.csv",
        help="Path to input dataset CSV file (default: data/processed/alibaba_service_state.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save split files (defaults to same directory as input)",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.70,
        help="Proportion of data for training (default: 0.70)",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Proportion of data for validation (default: 0.15)",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.15,
        help="Proportion of data for testing (default: 0.15)",
    )
    parser.add_argument(
        "--method",
        type=str,
        default="temporal",
        choices=["temporal", "random", "service"],
        help="Splitting methodology: 'temporal' (default, strictly prevents time leakage), 'random', 'service'",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for 'random' and 'service' splits (default: 42)",
    )
    parser.add_argument(
        "--validate-schema",
        action="store_true",
        default=True,
        help="Spot-check schema against ServiceState (default: True)",
    )
    return parser.parse_args()


def validate_split(df: pd.DataFrame, name: str, sample_size: int = 200) -> None:
    sample = df.sample(n=min(sample_size, len(df)), random_state=42)
    errors = []
    for idx, row in sample.iterrows():
        try:
            ServiceState.from_dataframe_row(row, source=StateSource.ALIBABA)
        except Exception as e:
            errors.append(f"Row {idx}: {e}")
    if errors:
        raise ValueError(
            f"Schema validation failed for {name} ({len(errors)} errors):\n"
            + "\n".join(errors[:5])
        )
    print(f"  Schema OK for {name} ({len(sample)} sampled rows verified).")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)

    if not input_path.is_file():
        print(f"Error: Input file '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = input_path.stem
    train_path = output_dir / f"{stem}_train.csv"
    val_path = output_dir / f"{stem}_val.csv"
    test_path = output_dir / f"{stem}_test.csv"

    print(f"=== FlexaScale Dataset Splitter ===")
    print(f"Reading input from: {input_path}")
    df = pd.read_csv(input_path)
    print(f"Loaded {len(df):,} rows, {df['service_id'].nunique()} unique services, {df['timestamp'].nunique()} timestamps.")
    print(f"Splitting using method '{args.method}' (train={args.train_ratio:.2f}, val={args.val_ratio:.2f}, test={args.test_ratio:.2f})...")

    train_df, val_df, test_df = split_service_state_dataset(
        df=df,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        method=args.method,
        random_state=args.seed,
    )

    print()
    print("=== Split Results Summary ===")
    for name, subset, path in [
        ("Train", train_df, train_path),
        ("Validation", val_df, val_path),
        ("Test", test_df, test_path),
    ]:
        ts_min = subset["timestamp"].min() if not subset.empty else "N/A"
        ts_max = subset["timestamp"].max() if not subset.empty else "N/A"
        print(f"[{name.upper()}]")
        print(f"  Rows:         {len(subset):,} ({len(subset)/len(df)*100:.1f}%)")
        print(f"  Timestamps:   {subset['timestamp'].nunique():,} (range: {ts_min} -> {ts_max})")
        print(f"  Services:     {subset['service_id'].nunique():,}")
        subset.to_csv(path, index=False)
        print(f"  Saved to:     {path}")

    if args.validate_schema:
        print()
        print("=== Schema Validation ===")
        validate_split(train_df, "train")
        validate_split(val_df, "val")
        validate_split(test_df, "test")

    print("\nDataset split successfully completed.")


if __name__ == "__main__":
    main()
