#!/usr/bin/env python3
"""
A small A-share watchlist helper based on Benjamin Graham-style margin of safety.

It is a discipline tool, not an automatic trading system.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import http.server
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
LOG_FILE = ROOT / "signals.csv"


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    source: str


FINANCIAL_LABELS = {
    "latest_period_eps": ["摊薄每股收益(元)", "加权每股收益(元)"],
    "bvps": ["每股净资产_调整后(元)", "每股净资产_调整前(元)"],
    "roe": ["净资产收益率(%)", "加权净资产收益率(%)"],
    "revenue_growth": ["主营业务收入增长率(%)"],
    "profit_growth": ["净利润增长率(%)"],
    "operating_cash_flow_per_share": ["每股经营性现金流(元)"],
}


def market_code(symbol: str) -> str:
    code, exchange = symbol.split(".")
    if exchange.upper() == "SH":
        return f"sh{code}"
    if exchange.upper() == "SZ":
        return f"sz{code}"
    raise ValueError(f"Unsupported symbol: {symbol}")


def fetch_sina_quote(symbol: str, timeout: int = 8) -> Quote | None:
    """Fetch a real-time quote from Sina's public quote endpoint."""
    code = market_code(symbol)
    url = f"http://hq.sinajs.cn/list={urllib.parse.quote(code)}"
    req = urllib.request.Request(url, headers={"Referer": "http://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("gbk", errors="replace")
    except Exception:
        return None

    if '="' not in raw:
        return None
    payload = raw.split('="', 1)[1].split('";', 1)[0]
    parts = payload.split(",")
    if len(parts) < 4 or not parts[0]:
        return None
    name = parts[0]
    # Sina fields: open, previous close, current price...
    price = safe_float(parts[3])
    if price <= 0:
        price = safe_float(parts[2])
    if price <= 0:
        return None
    return Quote(symbol=symbol, name=name, price=price, source="sina")


def sina_financial_url(symbol: str) -> str:
    code, _ = symbol.split(".")
    return f"http://money.finance.sina.com.cn/corp/go.php/vFD_FinancialGuideLine/stockid/{code}/displaytype/4.phtml"


def parse_first_metric(html_text: str, labels: list[str]) -> float | None:
    for label in labels:
        pattern = rf">{re.escape(label)}</a></td><td>([^<]+)</td>"
        match = re.search(pattern, html_text)
        if not match:
            continue
        raw = match.group(1).strip().replace(",", "")
        if raw in {"", "--", "——"}:
            return None
        return safe_float(raw, None)
    return None


def fetch_financial_snapshot(symbol: str, timeout: int = 12) -> dict[str, Any] | None:
    url = sina_financial_url(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_text = resp.read().decode("gbk", errors="ignore")
    except Exception:
        return None

    date_match = re.search(r"<strong>报告日期</strong></td><td>(\d{4}-\d{2}-\d{2})</td>", html_text)
    if not date_match:
        return None

    snapshot: dict[str, Any] = {
        "research_updated_at": date_match.group(1),
        "research_source": "新浪财经财务指标",
    }
    for key, labels in FINANCIAL_LABELS.items():
        snapshot[key] = parse_first_metric(html_text, labels)

    for pct_key in ["roe", "revenue_growth", "profit_growth"]:
        if snapshot.get(pct_key) is not None:
            snapshot[pct_key] = snapshot[pct_key] / 100
    return snapshot


def extract_metric_series(html_text: str, labels: list[str]) -> list[float | None]:
    for label in labels:
        pattern = rf">{re.escape(label)}</a></td>((?:<td>[^<]*</td>){{4}})"
        match = re.search(pattern, html_text)
        if not match:
            continue
        cells = re.findall(r"<td>([^<]*)</td>", match.group(1))
        values: list[float | None] = []
        for raw in cells:
            cleaned = raw.strip().replace(",", "")
            values.append(None if cleaned in {"", "--", "——"} else safe_float(cleaned, None))
        return values
    return []


def fetch_financial_trends(symbol: str, timeout: int = 12) -> dict[str, Any] | None:
    url = sina_financial_url(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_text = resp.read().decode("gbk", errors="ignore")
    except Exception:
        return None

    date_match = re.search(
        r"<strong>报告日期</strong></td><td>(\d{4}-\d{2}-\d{2})</td><td>(\d{4}-\d{2}-\d{2})</td><td>(\d{4}-\d{2}-\d{2})</td><td>(\d{4}-\d{2}-\d{2})</td>",
        html_text,
    )
    if not date_match:
        return None
    dates = list(date_match.groups())
    metrics = {
        "revenue_growth": extract_metric_series(html_text, FINANCIAL_LABELS["revenue_growth"]),
        "profit_growth": extract_metric_series(html_text, FINANCIAL_LABELS["profit_growth"]),
        "roe": extract_metric_series(html_text, FINANCIAL_LABELS["roe"]),
    }
    for key in metrics:
        metrics[key] = [None if value is None else value / 100 for value in metrics[key]]
    return {
        "symbol": symbol,
        "dates": dates,
        "metrics": metrics,
        "valuation_percentile": [],
        "source": "新浪财经财务指标",
    }


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def graham_growth_value(eps: float, growth_rate: float, aaa_yield: float) -> float | None:
    """Graham's revised formula: V = EPS * (8.5 + 2g) * 4.4 / Y.

    g and Y are percentages in the original formula. This function accepts
    decimals, so 8% growth is 0.08 and a 4% yield is 0.04.
    """
    if eps <= 0 or aaa_yield <= 0:
        return None
    g_percent = growth_rate * 100
    y_percent = aaa_yield * 100
    return eps * (8.5 + 2 * g_percent) * 4.4 / y_percent


def target_pe_value(eps: float, target_pe: float) -> float | None:
    if eps <= 0 or target_pe <= 0:
        return None
    return eps * target_pe


def graham_number(eps: float, bvps: float) -> float | None:
    """Classic Graham Number: sqrt(22.5 * EPS * BVPS)."""
    if eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def normalize_margin_threshold(value: Any, default: float) -> float:
    margin = safe_float(value, default)
    if margin > 1 and margin <= 100:
        margin = margin / 100
    if margin < 0 or margin >= 1:
        raise ValueError("安全边际门槛请输入 0-95 之间的百分数，例如 30 表示 30%。")
    return margin


def margin_of_safety(intrinsic_value: float | None, price: float) -> float | None:
    if not intrinsic_value or intrinsic_value <= 0:
        return None
    return (intrinsic_value - price) / intrinsic_value


def classify_band(level: str, text: str) -> dict[str, str]:
    return {"level": level, "text": text}


def classify_research_metric(value: float | None, positive_good: bool = True) -> str:
    if value is None:
        return "neutral"
    if positive_good:
        if value >= 0.15:
            return "good"
        if value >= 0:
            return "watch"
        return "bad"
    if value >= 0:
        return "good"
    if value >= -0.2:
        return "watch"
    return "bad"


def long_term_assessment(
    revenue_growth: float | None,
    profit_growth: float | None,
    roe: float | None,
    valuation_percentile: float | None,
    mos: float | None,
    planned_weight: float,
) -> tuple[dict[str, str], dict[str, str]]:
    quality_score = 0
    if revenue_growth is not None:
        quality_score += 2 if revenue_growth >= 0.15 else 1 if revenue_growth >= 0 else -1
    if profit_growth is not None:
        quality_score += 2 if profit_growth >= 0.2 else 1 if profit_growth >= 0 else -1
    if roe is not None:
        quality_score += 2 if roe >= 0.12 else 1 if roe >= 0.06 else 0

    expensive = valuation_percentile is not None and valuation_percentile >= 0.75
    fair_zone = valuation_percentile is not None and valuation_percentile <= 0.45

    if quality_score >= 4 and not expensive:
        long_term = classify_band("good", "基本面与估值位置较协调，可列入长线重点跟踪。")
    elif quality_score >= 2:
        long_term = classify_band("watch", "有长线观察价值，但需要等待更好的估值或确认。")
    elif quality_score <= -1:
        long_term = classify_band("bad", "长线基本面支撑不足，更多偏交易机会。")
    else:
        long_term = classify_band("neutral", "长线信息不足，先观察。")

    if mos is not None and mos >= 0:
        entry = classify_band("good", "估值已接近可讨论区，可考虑分批进场。")
    elif fair_zone:
        entry = classify_band("watch", "估值分位不高，可等回踩或资金确认后小仓试探。")
    elif expensive:
        entry = classify_band("bad", "估值分位偏高，不适合追高作为长线进场点。")
    elif planned_weight >= 0.35:
        entry = classify_band("bad", "计划仓位偏重，适合先降仓位假设再观察。")
    else:
        entry = classify_band("watch", "尚未出现理想长线进场价格，适合等待节奏。")
    return long_term, entry


def find_stock(config: dict[str, Any], symbol_or_name: str) -> dict[str, Any] | None:
    query = normalize_symbol(symbol_or_name)
    for stock in config.get("stocks", []):
        if normalize_symbol(stock.get("symbol", "")) == query or stock.get("name") == symbol_or_name:
            return dict(stock)
    return None


def normalize_symbol(value: str) -> str:
    value = value.strip().upper()
    if len(value) == 6 and value.isdigit():
        if value.startswith("6"):
            return f"{value}.SH"
        return f"{value}.SZ"
    return value


def evaluate(stock: dict[str, Any], config: dict[str, Any], live: bool = False) -> dict[str, Any]:
    stock = dict(stock)
    stock["symbol"] = normalize_symbol(stock["symbol"])
    quote = fetch_sina_quote(stock["symbol"]) if live else None
    price = quote.price if quote else safe_float(stock.get("today_close"))
    pe_ttm = safe_float(stock.get("pe_ttm"))
    eps = safe_float(stock.get("eps_ttm"))
    eps_source = "财务数据输入"
    if eps <= 0 and pe_ttm > 0:
        eps = price / pe_ttm
        eps_source = "按价格 / PE(TTM)推导"
    bvps = safe_float(stock.get("bvps"))

    target_pe = safe_float(stock.get("target_pe"), safe_float(config.get("default_target_pe"), 20))
    growth_rate = safe_float(
        stock.get("growth_rate"),
        safe_float(config.get("default_growth_rate"), 0.08),
    )
    aaa_yield = safe_float(
        stock.get("aaa_yield"),
        safe_float(config.get("default_aaa_yield"), 0.04),
    )
    required_mos = normalize_margin_threshold(
        stock.get("required_margin_of_safety"),
        normalize_margin_threshold(config.get("required_margin_of_safety"), 0.3),
    )

    by_pe = target_pe_value(eps, target_pe)
    by_growth = graham_growth_value(eps, growth_rate, aaa_yield)
    by_graham_number = graham_number(eps, bvps)
    candidates = [v for v in [by_pe, by_growth, by_graham_number] if v and v > 0]
    conservative_value = min(candidates) if candidates else None
    mos = margin_of_safety(conservative_value, price)
    buy_below = conservative_value * (1 - required_mos) if conservative_value else None
    pb = price / bvps if price > 0 and bvps > 0 else None

    planned_amount = safe_float(stock.get("planned_amount"))
    planned_weight = planned_amount / safe_float(config.get("portfolio_cash"), 1)
    max_weight = safe_float(config.get("max_single_stock_weight"), 0.35)
    if pe_ttm >= 80 or (pb is not None and pb >= 5):
        model_fit = "低"
        model_note = "高 PE 或高 PB 情形下，Graham 买入线更像风险警报，不是短期价格预测。"
    else:
        model_fit = "一般"
        model_note = "结果仍依赖 EPS、BVPS 和增长假设，适合作为纪律筛选。"

    if eps <= 0:
        action = "盈利为负，Graham估值失效"
    elif mos is None:
        action = "资料不足"
    elif mos >= required_mos and planned_weight <= max_weight:
        action = "达到安全边际，可考虑分批"
    elif mos >= required_mos and planned_weight > max_weight:
        action = "价格可看，但计划仓位过高"
    elif mos >= 0:
        action = "接近合理，继续等待"
    else:
        action = "无安全边际，谨慎追高"

    if eps <= 0 or conservative_value is None or mos is None:
        value_view = classify_band("neutral", "资料不足，无法形成价值纪律结论。")
    elif mos >= required_mos:
        value_view = classify_band("good", "达到你设定的安全边际门槛。")
    elif mos >= 0:
        value_view = classify_band("watch", "价格接近保守价值，但仍未达到门槛。")
    else:
        value_view = classify_band("bad", "明显高于保守价值，按 Graham 口径不便宜。")

    growth_pressure = None
    if pe_ttm > 0:
        growth_pressure = pe_ttm / max(target_pe, 1)
    if pe_ttm >= 120 or (pb is not None and pb >= 8):
        growth_view = classify_band("bad", "估值高度依赖持续高预期，交易属性强。")
    elif pe_ttm >= 50 or (pb is not None and pb >= 5):
        growth_view = classify_band("watch", "并非传统便宜股，更多取决于成长兑现。")
    else:
        growth_view = classify_band("good", "相对更接近可讨论区间，但仍需结合行业质量。")

    if planned_weight > max_weight:
        position_view = classify_band("bad", "计划仓位超过单股上限，集中度过高。")
    elif planned_weight >= max_weight * 0.75:
        position_view = classify_band("watch", "仓位已偏重，适合分批而非一次打满。")
    else:
        position_view = classify_band("good", "计划仓位处于相对克制区间。")

    revenue_growth = stock.get("revenue_growth")
    profit_growth = stock.get("profit_growth")
    roe = stock.get("roe")
    ocf_growth = stock.get("operating_cash_flow_growth")
    ocf_value = stock.get("operating_cash_flow_value")
    valuation_percentile = stock.get("valuation_percentile")
    valuation_percentile_history = stock.get("valuation_percentile_history", [])
    if valuation_percentile is None and valuation_percentile_history:
        valuation_percentile = valuation_percentile_history[-1]["value"]

    growth_score = 0
    for metric in [revenue_growth, profit_growth, roe]:
        if metric is None:
            continue
        growth_score += 1 if metric >= 0 else -1
    if ocf_growth is not None:
        growth_score += 1 if ocf_growth >= 0 else -1
    if ocf_value is not None:
        growth_score += 1 if ocf_value >= 0 else -1

    if growth_score >= 3:
        research_view = classify_band("good", "经营与盈利动能相对积极，值得继续跟踪兑现。")
    elif growth_score >= 1:
        research_view = classify_band("watch", "有亮点，但仍伴随兑现或现金流压力。")
    elif growth_score <= -2:
        research_view = classify_band("bad", "基本面动能偏弱，题材交易成分更高。")
    else:
        research_view = classify_band("neutral", "研究指标不足，暂不下强结论。")

    long_term_view, entry_timing_view = long_term_assessment(
        revenue_growth,
        profit_growth,
        roe,
        valuation_percentile,
        mos,
        planned_weight,
    )

    return {
        "symbol": stock["symbol"],
        "name": stock.get("name") or (quote.name if quote else ""),
        "price": price,
        "price_source": quote.source if quote else "config",
        "pe_ttm": pe_ttm,
        "eps_ttm": eps,
        "eps_source": eps_source,
        "bvps": bvps,
        "pb": pb,
        "target_pe_value": by_pe,
        "graham_growth_value": by_growth,
        "graham_number": by_graham_number,
        "conservative_value": conservative_value,
        "buy_below": buy_below,
        "margin_of_safety": mos,
        "required_margin_of_safety": required_mos,
        "planned_amount": planned_amount,
        "planned_weight": planned_weight,
        "model_fit": model_fit,
        "model_note": model_note,
        "growth_pressure": growth_pressure,
        "value_view": value_view,
        "growth_view": growth_view,
        "position_view": position_view,
        "research_view": research_view,
        "long_term_view": long_term_view,
        "entry_timing_view": entry_timing_view,
        "research_updated_at": stock.get("research_updated_at", "待补充"),
        "research_source": stock.get("research_source", "本地预设 / 手动输入"),
        "latest_period_eps": stock.get("latest_period_eps"),
        "revenue_growth": revenue_growth,
        "profit_growth": profit_growth,
        "roe": roe,
        "operating_cash_flow_growth": ocf_growth,
        "operating_cash_flow_value": ocf_value,
        "valuation_percentile": valuation_percentile,
        "valuation_percentile_history": valuation_percentile_history,
        "valuation_percentile_source": stock.get("valuation_percentile_source", "待接入"),
        "revenue_growth_level": classify_research_metric(revenue_growth),
        "profit_growth_level": classify_research_metric(profit_growth),
        "roe_level": classify_research_metric(roe),
        "operating_cash_flow_growth_level": classify_research_metric(ocf_growth),
        "action": action,
        "notes": stock.get("notes", ""),
    }


def money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def print_report(rows: list[dict[str, Any]], config: dict[str, Any]) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nA股安全边际监控 - {now}")
    print(f"最低安全边际门槛: {pct(safe_float(config.get('required_margin_of_safety'), 0.3))}")
    print("-" * 128)
    print(
        f"{'股票':<12} {'价格':>8} {'PE(TTM)':>8} {'EPS':>8} {'BVPS':>8} {'PB':>8} "
        f"{'保守价值':>10} {'买入线':>10} {'实际安全边际':>12} {'计划仓位':>10}  建议"
    )
    print("-" * 128)
    for row in rows:
        label = f"{row['name']} {row['symbol']}"
        print(
            f"{label:<12} {money(row['price']):>8} {money(row['pe_ttm']):>8} "
            f"{money(row['eps_ttm']):>8} {money(row['bvps']):>8} {money(row['pb']):>8} "
            f"{money(row['conservative_value']):>10} {money(row['buy_below']):>10} "
            f"{pct(row['margin_of_safety']):>12} "
            f"{pct(row['planned_weight']):>10}  {row['action']}"
        )
    print("-" * 128)
    print("说明: 保守价值取“目标PE估值”“Graham增长公式估值”“Graham Number”的较低值。")
    print("      它只能做风险纪律，不代表真实内在价值或买卖指令。\n")


def append_log(rows: list[dict[str, Any]]) -> None:
    exists = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "time",
                "symbol",
                "name",
                "price",
                "conservative_value",
                "buy_below",
                "margin_of_safety",
                "action",
            ],
        )
        if not exists:
            writer.writeheader()
        now = dt.datetime.now().isoformat(timespec="seconds")
        for row in rows:
            writer.writerow(
                {
                    "time": now,
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "price": money(row["price"]),
                    "conservative_value": money(row["conservative_value"]),
                    "buy_below": money(row["buy_below"]),
                    "margin_of_safety": pct(row["margin_of_safety"]),
                    "action": row["action"],
                }
            )


def maybe_notify(rows: list[dict[str, Any]]) -> None:
    actionable = [r for r in rows if "可考虑" in r["action"] or "仓位过高" in r["action"]]
    if not actionable:
        return
    message = "；".join(f"{r['name']} {r['price']:.2f}: {r['action']}" for r in actionable)
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "A股安全边际提醒"'],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="A-share margin-of-safety monitor")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.json")
    parser.add_argument("--live", action="store_true", help="Fetch live quotes from Sina")
    parser.add_argument("--log", action="store_true", help="Append result to signals.csv")
    parser.add_argument("--notify", action="store_true", help="Show macOS notification on actionable signals")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    rows = [evaluate(stock, config, live=args.live) for stock in config["stocks"]]
    print_report(rows, config)
    if args.log:
        append_log(rows)
    if args.notify:
        maybe_notify(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
