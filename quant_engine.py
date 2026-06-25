#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import joblib
    import pandas as pd
except ImportError:  # pragma: no cover
    joblib = None
    pd = None

from core_model import build_core_model_brief
from intel_engine import analyze_announcements
from stock_guard import evaluate, fetch_financial_snapshot, find_stock, normalize_symbol


ROOT = Path(__file__).resolve().parent
QUANT_DIR = ROOT / "quant"
OUTPUTS_DIR = QUANT_DIR / "outputs"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _scaled(value: float | None, low: float, high: float) -> float:
    if value is None or high == low:
        return 0.0
    return clamp((value - low) / (high - low), 0.0, 1.0)


def discover_model_bundle() -> dict[str, Any] | None:
    if joblib is None or pd is None or not OUTPUTS_DIR.exists():
        return None

    candidates = sorted(OUTPUTS_DIR.glob("**/model.joblib"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None

    model_path = candidates[0]
    metrics_path = model_path.with_name("metrics.json")
    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            metrics = {}

    try:
        model = joblib.load(model_path)
    except Exception:
        return None

    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is None or len(feature_names) == 0:
        feature_names = metrics.get("features") or []
    feature_names = list(feature_names)
    return {
        "path": model_path,
        "model": model,
        "metrics": metrics,
        "feature_names": feature_names,
        "target": metrics.get("target") or "trained_target",
    }


def build_feature_row(stock: dict[str, Any], row: dict[str, Any], intel: dict[str, Any] | None = None) -> dict[str, Any]:
    valuation_percentile = row.get("valuation_percentile")
    if valuation_percentile is None:
        history = row.get("valuation_percentile_history") or []
        if history:
            valuation_percentile = history[-1].get("value")

    intel = intel or {}
    sentiment_counts = intel.get("sentiment_counts") or {}

    return {
        "snapshot_date": row.get("research_updated_at") or "",
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "price": row.get("price"),
        "pe_ttm": row.get("pe_ttm"),
        "pb": row.get("pb"),
        "eps_ttm": row.get("eps_ttm"),
        "bvps": row.get("bvps"),
        "target_pe": stock.get("target_pe"),
        "growth_rate": stock.get("growth_rate"),
        "required_margin_of_safety": row.get("required_margin_of_safety"),
        "planned_amount": row.get("planned_amount"),
        "planned_weight": row.get("planned_weight"),
        "margin_of_safety": row.get("margin_of_safety"),
        "conservative_value": row.get("conservative_value"),
        "buy_below": row.get("buy_below"),
        "revenue_growth": row.get("revenue_growth"),
        "profit_growth": row.get("profit_growth"),
        "roe": row.get("roe"),
        "operating_cash_flow_growth": row.get("operating_cash_flow_growth"),
        "operating_cash_flow_value": row.get("operating_cash_flow_value"),
        "valuation_percentile": valuation_percentile,
        "high_pe_flag": int((row.get("pe_ttm") or 0) >= 80),
        "high_pb_flag": int((row.get("pb") or 0) >= 5),
        "negative_eps_flag": int((row.get("eps_ttm") or 0) <= 0),
        "research_updated_at": row.get("research_updated_at"),
        "headline_score": intel.get("headline_score", 0.0),
        "positive_news_count": sentiment_counts.get("positive", 0),
        "negative_news_count": sentiment_counts.get("negative", 0),
        "mixed_news_count": sentiment_counts.get("mixed", 0),
    }


def heuristic_score(row: dict[str, Any], intel: dict[str, Any] | None = None) -> dict[str, Any]:
    mos = row.get("margin_of_safety")
    revenue_growth = row.get("revenue_growth")
    profit_growth = row.get("profit_growth")
    roe = row.get("roe")
    pe_ttm = row.get("pe_ttm")
    pb = row.get("pb")
    ocf_value = row.get("operating_cash_flow_value")
    planned_weight = row.get("planned_weight") or 0.0

    value_score = _scaled(mos, -0.5, 0.5) * 35
    quality_score = (
        _scaled(revenue_growth, -0.1, 0.3) * 8
        + _scaled(profit_growth, -0.2, 0.5) * 10
        + _scaled(roe, 0.0, 0.2) * 8
        + (4 if ocf_value is not None and ocf_value > 0 else 0)
    )

    risk_penalty = 0.0
    if pe_ttm is not None and pe_ttm >= 80:
        risk_penalty += clamp((pe_ttm - 80) / 80, 0, 1.5) * 10
    if pb is not None and pb >= 5:
        risk_penalty += clamp((pb - 5) / 3, 0, 1.2) * 8
    if row.get("eps_ttm") is not None and row.get("eps_ttm") <= 0:
        risk_penalty += 12
    if planned_weight >= 0.35:
        risk_penalty += 5

    event_score = 0.0
    if intel:
        event_score = clamp((intel.get("headline_score") or 0.0) * 2.5, -10, 10)

    total = clamp(45 + value_score + quality_score + event_score - risk_penalty, 0, 100)

    factors: list[str] = []
    if mos is not None:
        factors.append(f"安全边际 {mos * 100:.1f}%")
    if profit_growth is not None:
        factors.append(f"净利同比 {profit_growth * 100:.1f}%")
    if revenue_growth is not None:
        factors.append(f"营收同比 {revenue_growth * 100:.1f}%")
    if pe_ttm is not None:
        factors.append(f"PE {pe_ttm:.1f}")
    if pb is not None:
        factors.append(f"PB {pb:.1f}")
    if intel and intel.get("top_tags"):
        factors.append("事件标签: " + " / ".join(intel["top_tags"]))

    if total >= 75:
        label = "优先跟踪"
    elif total >= 60:
        label = "可继续研究"
    elif total >= 40:
        label = "中性观察"
    else:
        label = "偏谨慎"

    return {
        "quant_score": round(total, 1),
        "quant_label": label,
        "quant_source": "heuristic",
        "quant_model_target": None,
        "score_breakdown": {
            "value_score": round(value_score, 1),
            "quality_score": round(quality_score, 1),
            "event_score": round(event_score, 1),
            "risk_penalty": round(risk_penalty, 1),
        },
        "factors": factors[:6],
    }


def apply_trained_model(records: list[dict[str, Any]], bundle: dict[str, Any]) -> None:
    if not records or pd is None:
        return

    feature_names = bundle.get("feature_names") or []
    if not feature_names:
        return

    df = pd.DataFrame([record["features"] for record in records])
    for column in feature_names:
        if column not in df.columns:
            df[column] = None
    df = df[feature_names]

    raw_scores = bundle["model"].predict(df)
    if len(raw_scores) == 1:
        scaled_scores = [70.0]
    else:
        order = sorted(range(len(raw_scores)), key=lambda idx: raw_scores[idx])
        ranks = {idx: rank for rank, idx in enumerate(order)}
        scaled_scores = [
            round(35 + (ranks[idx] / max(len(raw_scores) - 1, 1)) * 60, 1)
            for idx in range(len(raw_scores))
        ]

    for idx, record in enumerate(records):
        score = scaled_scores[idx]
        if score >= 80:
            label = "模型优先"
        elif score >= 65:
            label = "模型看多"
        elif score >= 50:
            label = "模型中性"
        else:
            label = "模型谨慎"

        breakdown = record["row"].get("score_breakdown", {}).copy()
        breakdown["model_prediction"] = round(float(raw_scores[idx]), 4)
        breakdown["model_rank_score"] = score
        record["row"].update(
            {
                "quant_score": score,
                "quant_label": label,
                "quant_source": "trained_model",
                "quant_model_target": bundle.get("target"),
                "score_breakdown": breakdown,
                "factors": (record["row"].get("factors") or [])[:6],
            }
        )


def _enrich_stock(
    config: dict[str, Any],
    raw_stock: dict[str, Any],
    live: bool,
    refresh: bool,
    with_intel: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    stock = dict(raw_stock)
    symbol = normalize_symbol(stock.get("symbol", ""))
    if refresh:
        snapshot = fetch_financial_snapshot(symbol)
        if snapshot:
            stock.update({key: value for key, value in snapshot.items() if value is not None})
    row = evaluate(stock, config, live=live)
    intel = analyze_announcements(symbol, limit=8 if with_intel else 4) if with_intel else None
    return row, intel


def build_watchlist_rankings(config: dict[str, Any], live: bool = False, refresh: bool = False) -> list[dict[str, Any]]:
    bundle = discover_model_bundle()
    records: list[dict[str, Any]] = []

    for raw_stock in config.get("stocks", []):
        row, intel = _enrich_stock(config, raw_stock, live=live, refresh=refresh, with_intel=refresh)
        heuristic = heuristic_score(row, intel)
        row.update(heuristic)
        row["intel_overall"] = intel.get("overall") if intel else ""
        row["intel_top_tags"] = intel.get("top_tags", []) if intel else []
        row["core_model"] = build_core_model_brief(row, intel)
        records.append({"row": row, "features": build_feature_row(raw_stock, row, intel)})

    if bundle:
        apply_trained_model(records, bundle)

    rankings = [record["row"] for record in records]
    rankings.sort(key=lambda item: item.get("quant_score", 0), reverse=True)
    return rankings


def build_symbol_snapshot(config: dict[str, Any], symbol: str, live: bool = True) -> dict[str, Any]:
    stock = find_stock(config, symbol) or {"symbol": normalize_symbol(symbol)}
    row, intel = _enrich_stock(config, stock, live=live, refresh=True, with_intel=True)
    row.update(heuristic_score(row, intel))
    row["intel"] = intel
    row["core_model"] = build_core_model_brief(row, intel)

    rankings = build_watchlist_rankings(config, live=False, refresh=False)
    for item in rankings:
        if item.get("symbol") == normalize_symbol(symbol):
            row["quant_score"] = item.get("quant_score")
            row["quant_label"] = item.get("quant_label")
            row["quant_source"] = item.get("quant_source")
            row["quant_model_target"] = item.get("quant_model_target")
            row["score_breakdown"] = item.get("score_breakdown")
            row["factors"] = item.get("factors")
            break

    return row
