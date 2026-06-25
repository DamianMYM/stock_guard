#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    model = joblib.load(args.model)
    raw_df = pd.read_csv(args.input)
    df = raw_df.copy()
    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is None or len(feature_names) == 0:
        feature_names = []
    feature_names = list(feature_names)
    for column in feature_names:
        if column not in df.columns:
            df[column] = None
    if feature_names:
        df = df[feature_names]
    scored = raw_df.copy()
    scored["quant_score"] = model.predict(df)
    scored = scored.sort_values("quant_score", ascending=False)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"Wrote scores to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
