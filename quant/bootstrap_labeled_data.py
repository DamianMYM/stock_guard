#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_engine import build_feature_row, build_watchlist_rankings
from stock_guard import load_config

DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "data" / "training_labeled.bootstrap.csv"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def infer_intel_stub(row: dict) -> dict:
    score = safe_float(row.get("headline_score"), 0.0) or 0.0
    positive = 1 if score > 0.3 else 0
    negative = 1 if score < -0.3 else 0
    mixed = 1 if not positive and not negative and abs(score) > 0.05 else 0
    return {
        "headline_score": score,
        "sentiment_counts": {
            "positive": positive,
            "negative": negative,
            "mixed": mixed,
        },
    }


def synthesize_variant(base: dict, rng: random.Random) -> dict:
    price = max(0.5, safe_float(base.get("price"), 10.0) * rng.uniform(0.68, 1.38))
    conservative_value = max(0.5, safe_float(base.get("conservative_value"), price) * rng.uniform(0.92, 1.08))
    required_mos = safe_float(base.get("required_margin_of_safety"), 0.3) or 0.3
    buy_below = max(0.5, conservative_value * (1 - required_mos))
    margin = (conservative_value - price) / price if price else None

    bvps = safe_float(base.get("bvps"), None)
    eps_ttm = safe_float(base.get("eps_ttm"), None)
    pe_ttm = price / eps_ttm if eps_ttm and eps_ttm > 0 else safe_float(base.get("pe_ttm"), None)
    pb = price / bvps if bvps and bvps > 0 else safe_float(base.get("pb"), None)

    revenue_growth = clamp((safe_float(base.get("revenue_growth"), 0.05) or 0.05) + rng.uniform(-0.08, 0.12), -0.35, 0.65)
    profit_growth = clamp((safe_float(base.get("profit_growth"), 0.08) or 0.08) + rng.uniform(-0.15, 0.2), -0.7, 1.2)
    roe = clamp((safe_float(base.get("roe"), 0.08) or 0.08) + rng.uniform(-0.03, 0.06), -0.05, 0.35)
    ocf_growth = clamp((safe_float(base.get("operating_cash_flow_growth"), 0.0) or 0.0) + rng.uniform(-0.2, 0.25), -0.8, 1.0)
    ocf_value = (safe_float(base.get("operating_cash_flow_value"), 0.0) or 0.0) + rng.uniform(-3.0, 3.0)
    valuation_percentile = clamp((safe_float(base.get("valuation_percentile"), 0.55) or 0.55) + rng.uniform(-0.25, 0.25), 0.01, 0.99)
    planned_weight = clamp((safe_float(base.get("planned_weight"), 0.1) or 0.1) + rng.uniform(-0.08, 0.1), 0.0, 0.55)
    headline_score = clamp((safe_float(base.get("headline_score"), 0.0) or 0.0) + rng.uniform(-1.2, 1.2), -4.0, 4.0)

    positive_news_count = max(0, int(round((safe_float(base.get("positive_news_count"), 0) or 0) + rng.randint(-1, 3))))
    negative_news_count = max(0, int(round((safe_float(base.get("negative_news_count"), 0) or 0) + rng.randint(-1, 3))))
    mixed_news_count = max(0, int(round((safe_float(base.get("mixed_news_count"), 0) or 0) + rng.randint(0, 2))))

    row = dict(base)
    row.update(
        {
            "price": round(price, 4),
            "conservative_value": round(conservative_value, 4),
            "buy_below": round(buy_below, 4),
            "margin_of_safety": None if margin is None else round(margin, 6),
            "pe_ttm": None if pe_ttm is None else round(pe_ttm, 4),
            "pb": None if pb is None else round(pb, 4),
            "revenue_growth": round(revenue_growth, 6),
            "profit_growth": round(profit_growth, 6),
            "roe": round(roe, 6),
            "operating_cash_flow_growth": round(ocf_growth, 6),
            "operating_cash_flow_value": round(ocf_value, 6),
            "valuation_percentile": round(valuation_percentile, 6),
            "planned_weight": round(planned_weight, 6),
            "planned_amount": round(planned_weight * 100000, 2),
            "headline_score": round(headline_score, 6),
            "positive_news_count": positive_news_count,
            "negative_news_count": negative_news_count,
            "mixed_news_count": mixed_news_count,
        }
    )
    row["high_pe_flag"] = int((row.get("pe_ttm") or 0) >= 80)
    row["high_pb_flag"] = int((row.get("pb") or 0) >= 5)
    row["negative_eps_flag"] = int((row.get("eps_ttm") or 0) <= 0)
    return row


def label_variant(row: dict, rng: random.Random) -> dict:
    margin = safe_float(row.get("margin_of_safety"), 0.0) or 0.0
    rev = safe_float(row.get("revenue_growth"), 0.0) or 0.0
    profit = safe_float(row.get("profit_growth"), 0.0) or 0.0
    roe = safe_float(row.get("roe"), 0.0) or 0.0
    ocf_growth = safe_float(row.get("operating_cash_flow_growth"), 0.0) or 0.0
    ocf_value = safe_float(row.get("operating_cash_flow_value"), 0.0) or 0.0
    valuation_percentile = safe_float(row.get("valuation_percentile"), 0.5) or 0.5
    headline_score = safe_float(row.get("headline_score"), 0.0) or 0.0
    planned_weight = safe_float(row.get("planned_weight"), 0.0) or 0.0
    pe_ttm = safe_float(row.get("pe_ttm"), 40.0) or 40.0
    pb = safe_float(row.get("pb"), 2.0) or 2.0

    value_component = clamp(margin, -0.7, 0.8) * 0.24
    growth_component = clamp(rev, -0.4, 0.6) * 0.07 + clamp(profit, -0.7, 1.0) * 0.09
    quality_component = clamp(roe, -0.05, 0.3) * 0.16 + clamp(ocf_growth, -0.8, 1.0) * 0.04
    cash_component = clamp(ocf_value / 10.0, -0.6, 0.6) * 0.03
    event_component = clamp(headline_score / 4.0, -1.0, 1.0) * 0.08
    valuation_penalty = valuation_percentile * 0.09 + clamp((pe_ttm - 35) / 120.0, 0.0, 0.3) * 0.12 + clamp((pb - 3.2) / 4.0, 0.0, 0.25) * 0.07
    exposure_penalty = planned_weight * 0.07
    flag_penalty = row.get("high_pe_flag", 0) * 0.04 + row.get("high_pb_flag", 0) * 0.03 + row.get("negative_eps_flag", 0) * 0.12
    news_penalty = (safe_float(row.get("negative_news_count"), 0) or 0) * 0.01
    news_bonus = (safe_float(row.get("positive_news_count"), 0) or 0) * 0.008
    noise = rng.uniform(-0.025, 0.025)

    future_20d = value_component + growth_component + quality_component + cash_component + event_component + news_bonus - valuation_penalty - exposure_penalty - flag_penalty - news_penalty + noise
    future_60d = future_20d * 1.45 + clamp(profit, -0.5, 0.8) * 0.04 + clamp(headline_score / 4.0, -1.0, 1.0) * 0.03 + rng.uniform(-0.03, 0.03)
    drawdown_20d = 0.08 + clamp(valuation_percentile, 0.0, 1.0) * 0.15 + row.get("high_pe_flag", 0) * 0.08 + row.get("negative_eps_flag", 0) * 0.12 + max(0.0, -headline_score) * 0.02 + rng.uniform(-0.02, 0.03)

    labeled = dict(row)
    labeled["future_20d_excess_return"] = round(future_20d, 6)
    labeled["future_60d_excess_return"] = round(future_60d, 6)
    labeled["max_drawdown_20d"] = round(clamp(drawdown_20d, 0.01, 0.65), 6)
    return labeled


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples-per-stock", type=int, default=240)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    config = load_config(args.config)
    rankings = build_watchlist_rankings(config, live=False, refresh=False)
    by_symbol = {row["symbol"]: row for row in rankings}

    rows: list[dict[str, Any]] = []
    for stock in config.get("stocks", []):
        symbol = stock.get("symbol")
        base_row = by_symbol.get(symbol)
        if not base_row:
            continue
        base_features = build_feature_row(stock, base_row, infer_intel_stub(base_row))
        for _ in range(args.samples_per_stock):
            variant = synthesize_variant(base_features, rng)
            rows.append(label_variant(variant, rng))

    if not rows:
        raise SystemExit("No rows generated. Check config.json watchlist.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    expected = sum(row["future_20d_excess_return"] for row in rows) / len(rows)
    avg_drawdown = sum(row["max_drawdown_20d"] for row in rows) / len(rows)
    print(
        f"Generated {len(rows)} bootstrap rows for {len(config.get('stocks', []))} stocks -> {args.output}\n"
        f"Average 20d target: {expected:.4f}, average drawdown: {avg_drawdown:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
