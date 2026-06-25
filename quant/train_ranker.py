#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:
    from lightgbm import LGBMRegressor

    HAS_LIGHTGBM = True
except ImportError:  # pragma: no cover
    from sklearn.ensemble import HistGradientBoostingRegressor

    HAS_LIGHTGBM = False


def build_model(numeric_features: list[str], categorical_features: list[str]) -> Pipeline:
    preprocess = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), numeric_features),
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("encoder", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
        ]
    )
    if HAS_LIGHTGBM:
        model = LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            random_state=42,
        )
    else:
        model = HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.05,
            max_depth=6,
            random_state=42,
        )
    return Pipeline(steps=[("preprocess", preprocess), ("model", model)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    if args.target not in df.columns:
      raise SystemExit(f"Missing target column: {args.target}")

    if "snapshot_date" in df.columns:
        df = df.sort_values("snapshot_date")

    df = df.dropna(subset=[args.target]).reset_index(drop=True)
    if len(df) < 10:
        raise SystemExit("Not enough labeled rows to train. Need at least 10.")

    ignore = {args.target, "future_20d_excess_return", "future_60d_excess_return", "max_drawdown_20d"}
    features = [col for col in df.columns if col not in ignore]
    categorical = [col for col in features if df[col].dtype == "object"]
    numeric = [col for col in features if col not in categorical]

    split = max(1, int(len(df) * 0.8))
    train_df = df.iloc[:split]
    test_df = df.iloc[split:]
    if test_df.empty:
        test_df = train_df.iloc[-1:].copy()
        train_df = train_df.iloc[:-1].copy()

    pipeline = build_model(numeric, categorical)
    pipeline.fit(train_df[features], train_df[args.target])

    pred = pipeline.predict(test_df[features])
    metrics = {
        "rows_train": int(len(train_df)),
        "rows_test": int(len(test_df)),
        "target": args.target,
        "model_family": "lightgbm" if HAS_LIGHTGBM else "hist_gradient_boosting",
        "mae": float(mean_absolute_error(test_df[args.target], pred)),
        "r2": float(r2_score(test_df[args.target], pred)) if len(test_df) > 1 else None,
        "features": features,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_dir / "model.joblib")
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
