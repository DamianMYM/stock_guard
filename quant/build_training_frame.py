#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
SIGNALS_PATH = ROOT / "signals.csv"
OUTPUT_DIR = Path(__file__).resolve().parent / "data"
OUTPUT_PATH = OUTPUT_DIR / "watchlist_features.csv"


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_last_signal_rows() -> dict[str, dict[str, str]]:
    if not SIGNALS_PATH.exists():
        return {}
    latest: dict[str, dict[str, str]] = {}
    with SIGNALS_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = row.get("symbol")
            if symbol:
                latest[symbol] = row
    return latest


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    latest_signals = load_last_signal_rows()

    rows = []
    portfolio_cash = safe_float(config.get("portfolio_cash")) or 1.0
    for stock in config.get("stocks", []):
        symbol = stock.get("symbol", "")
        signal = latest_signals.get(symbol, {})
        price = safe_float(stock.get("today_close"))
        pe_ttm = safe_float(stock.get("pe_ttm"))
        eps_ttm = safe_float(stock.get("eps_ttm"))
        bvps = safe_float(stock.get("bvps"))
        pb = (price / bvps) if price and bvps else None
        planned_amount = safe_float(stock.get("planned_amount")) or 0.0
        planned_weight = planned_amount / portfolio_cash

        rows.append(
            {
                "snapshot_date": signal.get("time", "")[:10] or stock.get("research_updated_at", ""),
                "symbol": symbol,
                "name": stock.get("name", ""),
                "price": price,
                "pe_ttm": pe_ttm,
                "pb": pb,
                "eps_ttm": eps_ttm,
                "bvps": bvps,
                "target_pe": safe_float(stock.get("target_pe")),
                "growth_rate": safe_float(stock.get("growth_rate")),
                "required_margin_of_safety": safe_float(stock.get("required_margin_of_safety") or config.get("required_margin_of_safety")),
                "planned_amount": planned_amount,
                "planned_weight": planned_weight,
                "margin_of_safety": safe_float(signal.get("margin_of_safety")),
                "conservative_value": safe_float(signal.get("conservative_value")),
                "buy_below": safe_float(signal.get("buy_below")),
                "revenue_growth": safe_float(stock.get("revenue_growth")),
                "profit_growth": safe_float(stock.get("profit_growth")),
                "roe": safe_float(stock.get("roe")),
                "operating_cash_flow_growth": safe_float(stock.get("operating_cash_flow_growth")),
                "operating_cash_flow_value": safe_float(stock.get("operating_cash_flow_value")),
                "valuation_percentile": (
                    safe_float(stock.get("valuation_percentile"))
                    if stock.get("valuation_percentile") is not None
                    else safe_float((stock.get("valuation_percentile_history") or [{}])[-1].get("value"))
                ),
                "high_pe_flag": int((pe_ttm or 0) >= 80),
                "high_pb_flag": int((pb or 0) >= 5),
                "negative_eps_flag": int((eps_ttm or 0) <= 0),
                "research_updated_at": stock.get("research_updated_at", ""),
                "headline_score": 0.0,
                "positive_news_count": 0,
                "negative_news_count": 0,
                "mixed_news_count": 0,
            }
        )

    fieldnames = list(rows[0].keys()) if rows else []
    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
