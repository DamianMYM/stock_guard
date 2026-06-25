#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_LABELED = ROOT / "data" / "training_labeled.bootstrap.csv"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "future20_bootstrap"


def run_step(command: list[str]) -> None:
    print(">", " ".join(str(part) for part in command))
    subprocess.run(command, check=True, cwd=ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-stock", type=int, default=240)
    parser.add_argument("--target", default="future_20d_excess_return")
    parser.add_argument("--labeled", type=Path, default=DEFAULT_LABELED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    python = sys.executable

    run_step(
        [
            python,
            str(ROOT / "bootstrap_labeled_data.py"),
            "--samples-per-stock",
            str(args.samples_per_stock),
            "--output",
            str(args.labeled),
        ]
    )
    run_step(
        [
            python,
            str(ROOT / "train_ranker.py"),
            "--input",
            str(args.labeled),
            "--target",
            args.target,
            "--output-dir",
            str(args.output_dir),
        ]
    )
    run_step([python, str(ROOT / "build_training_frame.py")])
    run_step(
        [
            python,
            str(ROOT / "score_watchlist.py"),
            "--model",
            str(args.output_dir / "model.joblib"),
            "--input",
            str(ROOT / "data" / "watchlist_features.csv"),
            "--output",
            str(ROOT / "data" / "watchlist_scores.csv"),
        ]
    )
    print(f"Pipeline completed. Model bundle: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
