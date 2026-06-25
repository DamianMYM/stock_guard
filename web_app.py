#!/usr/bin/env python3
"""Local web UI for Stock Guard."""

from __future__ import annotations

import datetime as dt
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request
from urllib.parse import parse_qs, urlparse

from core_model import build_core_model_brief
from intel_engine import analyze_announcements
from quant_engine import build_symbol_snapshot, build_watchlist_rankings, heuristic_score
from stock_guard import (
    DATA_ROOT,
    DEFAULT_CONFIG,
    RESOURCE_ROOT,
    evaluate,
    fetch_financial_snapshot,
    fetch_financial_trends,
    fetch_sina_quote,
    fetch_stock_announcements,
    find_stock,
    load_config,
    normalize_symbol,
)


STATIC = RESOURCE_ROOT / "web"
OLLAMA_BASE = "http://127.0.0.1:11434"
HISTORY_FILE = DATA_ROOT / "history.json"
WATCHLIST_FIELDS = {
    "symbol",
    "name",
    "today_close",
    "planned_amount",
    "pe_ttm",
    "eps_ttm",
    "bvps",
    "target_pe",
    "growth_rate",
    "notes",
    "research_updated_at",
    "research_source",
    "latest_period_eps",
    "revenue_growth",
    "profit_growth",
    "roe",
    "operating_cash_flow_growth",
    "operating_cash_flow_value",
    "valuation_percentile",
    "valuation_percentile_history",
    "valuation_percentile_source",
}


def save_config(config: dict) -> None:
    DEFAULT_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def load_history_store() -> dict:
    if not HISTORY_FILE.exists():
        return {"recent": []}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"recent": []}


def save_history_store(store: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def recent_history(symbol: str | None = None, limit: int = 12, unique: bool = False) -> list[dict]:
    items = load_history_store().get("recent", [])
    filtered = [
        item
        for item in items
        if not symbol or normalize_symbol(item.get("symbol", "")) == normalize_symbol(symbol)
    ]
    if not unique:
        return filtered[:limit]

    seen: set[str] = set()
    deduped: list[dict] = []
    for item in filtered:
        item_symbol = normalize_symbol(item.get("symbol", ""))
        if not item_symbol or item_symbol in seen:
            continue
        seen.add(item_symbol)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def record_recent_activity(entry: dict) -> None:
    symbol = normalize_symbol(entry.get("symbol", ""))
    if not symbol:
        return

    payload = dict(entry)
    payload["symbol"] = symbol
    payload["viewed_at"] = dt.datetime.now().isoformat(timespec="seconds")

    store = load_history_store()
    recent = store.setdefault("recent", [])
    latest = recent[0] if recent else None
    if (
        latest
        and normalize_symbol(latest.get("symbol", "")) == symbol
        and latest.get("event") == payload.get("event")
        and latest.get("action") == payload.get("action")
    ):
        recent[0] = payload
    else:
        recent.insert(0, payload)
    store["recent"] = recent[:80]
    save_history_store(store)


def watchlist_snapshot(config: dict, limit: int = 20) -> list[dict]:
    items = []
    for stock in config.get("stocks", [])[:limit]:
        items.append(
            {
                "symbol": normalize_symbol(stock.get("symbol", "")),
                "name": stock.get("name") or normalize_symbol(stock.get("symbol", "")),
            }
        )
    return items


def sanitize_watchlist_item(payload: dict, config: dict) -> dict:
    stock = dict(payload.get("stock") or payload)
    symbol = normalize_symbol(stock.get("symbol", ""))
    if not symbol:
        raise ValueError("请输入股票代码后再保存。")

    clean: dict[str, Any] = {"symbol": symbol}
    for key in WATCHLIST_FIELDS:
        if key == "symbol":
            continue
        if key not in stock:
            continue
        value = stock.get(key)
        if value in ("", None):
            continue
        clean[key] = value

    if "today_close" not in clean and stock.get("price") not in ("", None):
        clean["today_close"] = stock.get("price")

    clean.setdefault("target_pe", config.get("default_target_pe", 20))
    clean.setdefault("growth_rate", config.get("default_growth_rate", 0.08))
    clean.setdefault("planned_amount", 0)
    return clean


def split_thinking(text: str) -> tuple[str, str]:
    matches = re.findall(r"<think>(.*?)</think>", text, flags=re.S)
    reasoning = "\n\n".join(part.strip() for part in matches if part.strip())
    answer = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return reasoning, answer


def context_basis(context: dict) -> list[str]:
    evaluation = context.get("evaluation") or {}
    form = context.get("form") or {}
    basis = []
    symbol = evaluation.get("symbol") or form.get("symbol")
    if symbol:
        basis.append(f"股票：{evaluation.get('name') or symbol}")
    if evaluation.get("price") is not None:
        basis.append(f"当前价：{evaluation.get('price')}")
    if evaluation.get("pe_ttm") is not None:
        basis.append(f"PE(TTM)：{evaluation.get('pe_ttm')}")
    if evaluation.get("margin_of_safety") is not None:
        basis.append(f"安全边际：{round(float(evaluation.get('margin_of_safety')) * 100, 1)}%")
    if evaluation.get("planned_weight") is not None:
        basis.append(f"计划仓位：{round(float(evaluation.get('planned_weight')) * 100, 1)}%")
    if evaluation.get("action"):
        basis.append(f"鼓手判断：{evaluation.get('action')}")
    return basis


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/llm/models":
            self.send_llm_models()
            return
        if parsed.path == "/api/preset":
            self.send_preset(parsed.query)
            return
        if parsed.path == "/api/quote":
            self.send_quote(parsed.query)
            return
        if parsed.path == "/api/research":
            self.send_research(parsed.query)
            return
        if parsed.path == "/api/news":
            self.send_news(parsed.query)
            return
        if parsed.path == "/api/trends":
            self.send_trends(parsed.query)
            return
        if parsed.path == "/api/quant/rankings":
            self.send_quant_rankings(parsed.query)
            return
        if parsed.path == "/api/intel":
            self.send_intel(parsed.query)
            return
        if parsed.path == "/api/history":
            self.send_history()
            return
        self.send_static(parsed.path)

    def do_POST(self) -> None:
        if self.path == "/api/llm/chat":
            self.send_llm_chat()
            return
        if self.path == "/api/valuation-snapshot":
            self.save_valuation_snapshot()
            return
        if self.path == "/api/watchlist":
            self.save_watchlist()
            return
        if self.path != "/api/evaluate":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            config = load_config(DEFAULT_CONFIG)
            stock = find_stock(config, payload.get("symbol", "")) or {}
            symbol = normalize_symbol(payload.get("symbol", ""))
            snapshot = fetch_financial_snapshot(symbol)
            if snapshot:
                stock.update({k: v for k, v in snapshot.items() if v is not None})
            stock.update({k: v for k, v in payload.items() if v not in ("", None)})
            if not stock.get("symbol"):
                raise ValueError("请输入股票代码")
            result = evaluate(stock, config, live=bool(payload.get("live")))
            intel = analyze_announcements(symbol, limit=6)
            result.update(heuristic_score(result, intel))
            result["intel_overall"] = intel.get("overall") if intel else ""
            result["intel_top_tags"] = intel.get("top_tags", []) if intel else []
            result["core_model"] = build_core_model_brief(result, intel)
            record_recent_activity(
                {
                    "event": "evaluate",
                    "symbol": result.get("symbol"),
                    "name": result.get("name"),
                    "price": result.get("price"),
                    "action": result.get("action"),
                    "quant_label": result.get("quant_label"),
                    "quant_score": result.get("quant_score"),
                }
            )
            self.send_json({"ok": True, "result": result})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def send_llm_models(self) -> None:
        try:
            with request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=6) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.send_json({"ok": True, "models": data.get("models", [])})
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": f"未连接到本地 Ollama：{exc}"}, status=502)

    def send_llm_chat(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            model = payload.get("model") or "deepseek-r1:7b"
            message = str(payload.get("message") or "").strip()
            context = payload.get("context") or {}
            if not message:
                raise ValueError("请输入要问本地模型的问题。")

            form = context.get("form") or {}
            evaluation = context.get("evaluation") or {}
            symbol = evaluation.get("symbol") or form.get("symbol") or ""
            if symbol and not context.get("recent_history"):
                context["recent_history"] = recent_history(symbol=symbol, limit=3, unique=False)

            announcements = []
            if payload.get("use_online_research", True):
                announcements = fetch_stock_announcements(symbol)
                if announcements:
                    context["online_announcements"] = announcements
                if symbol and not context.get("core_model"):
                    context["core_model"] = build_symbol_snapshot(load_config(DEFAULT_CONFIG), symbol, live=True).get("core_model")

            system_prompt = (
                "你是鼓手 Stock Guard 的本地投资研究助手。"
                "你熟悉 A 股基本面、估值、安全边际、仓位管理、财报与公司公告分析。"
                "你只能基于用户提供的行情、估值、财务上下文和联网公告做解释与风险建议。"
                "公告只是一手线索，不要把标题扩写成未经证实的事实。"
                "不要编造实时数据，不要承诺收益，不要给出绝对化的买卖指令。"
                "回答时区分事实、推断和风险，用简洁中文输出。"
            )
            user_prompt = (
                "当前鼓手页面上下文如下，可能包含股票代码、实时价格、估值、仓位和用户输入参数：\n"
                f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
                f"用户问题：{message}"
            )
            req = request.Request(
                f"{OLLAMA_BASE}/api/chat",
                data=json_bytes(
                    {
                        "model": model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    }
                ),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started = dt.datetime.now()
            with request.urlopen(req, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
            elapsed = (dt.datetime.now() - started).total_seconds()
            raw_content = data.get("message", {}).get("content", "")
            reasoning, content = split_thinking(raw_content)
            self.send_json(
                {
                    "ok": True,
                    "model": model,
                    "answer": content or "本地模型没有返回内容。",
                    "reasoning": reasoning,
                    "raw_answer": raw_content,
                    "basis": context_basis(context)
                    + ([f"联网公告：{len(announcements)}条（东方财富）"] if announcements else []),
                    "online_sources": announcements,
                    "elapsed_seconds": round(elapsed, 1),
                }
            )
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": f"本地模型调用失败：{exc}"}, status=502)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def send_preset(self, query: str) -> None:
        symbol = parse_qs(query).get("symbol", [""])[0]
        config = load_config(DEFAULT_CONFIG)
        stock = find_stock(config, symbol) or {"symbol": normalize_symbol(symbol)}
        snapshot = fetch_financial_snapshot(normalize_symbol(symbol))
        if snapshot:
            stock.update({k: v for k, v in snapshot.items() if v is not None})
        self.send_json({"ok": True, "stock": stock, "config": config})

    def send_quote(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        quote = fetch_sina_quote(symbol)
        if not quote:
            self.send_json({"ok": False, "error": "未能获取实时行情"}, status=502)
            return
        self.send_json({"ok": True, "quote": quote.__dict__})

    def send_research(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        snapshot = fetch_financial_snapshot(symbol)
        if not snapshot:
            self.send_json({"ok": False, "error": "未能获取财务研究指标"}, status=502)
            return
        self.send_json({"ok": True, "research": snapshot})

    def send_news(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        self.send_json({"ok": True, "announcements": fetch_stock_announcements(symbol)})

    def send_trends(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        trends = fetch_financial_trends(symbol)
        if not trends:
            self.send_json({"ok": False, "error": "未能获取历史趋势"}, status=502)
            return
        config = load_config(DEFAULT_CONFIG)
        stock = find_stock(config, symbol) or {}
        trends["valuation_percentile"] = stock.get("valuation_percentile_history", [])
        trends["valuation_percentile_source"] = stock.get("valuation_percentile_source", "待接入")
        self.send_json({"ok": True, "trends": trends})

    def send_quant_rankings(self, query: str) -> None:
        params = parse_qs(query)
        live = params.get("live", ["0"])[0] in {"1", "true", "True"}
        refresh = params.get("refresh", ["0"])[0] in {"1", "true", "True"}
        config = load_config(DEFAULT_CONFIG)
        self.send_json({"ok": True, "rankings": build_watchlist_rankings(config, live=live, refresh=refresh)})

    def send_intel(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        if not symbol:
            self.send_json({"ok": False, "error": "缺少股票代码"}, status=400)
            return
        config = load_config(DEFAULT_CONFIG)
        snapshot = build_symbol_snapshot(config, symbol, live=True)
        self.send_json({"ok": True, "snapshot": snapshot, "intel": snapshot.get("intel", {})})

    def send_history(self) -> None:
        config = load_config(DEFAULT_CONFIG)
        self.send_json(
            {
                "ok": True,
                "watchlist": watchlist_snapshot(config),
                "watchlist_count": len(config.get("stocks", [])),
                "recent": recent_history(limit=12, unique=False),
                "recent_symbols": recent_history(limit=8, unique=True),
            }
        )

    def save_watchlist(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            config = load_config(DEFAULT_CONFIG)
            stock = sanitize_watchlist_item(payload, config)

            existing = None
            for item in config.get("stocks", []):
                if normalize_symbol(item.get("symbol", "")) == stock["symbol"]:
                    existing = item
                    break

            if existing is None:
                config.setdefault("stocks", []).append(stock)
                saved_mode = "created"
            else:
                existing.update(stock)
                saved_mode = "updated"

            save_config(config)
            result = payload.get("result") or {}
            record_recent_activity(
                {
                    "event": "watchlist_save",
                    "symbol": stock.get("symbol"),
                    "name": stock.get("name"),
                    "price": stock.get("today_close"),
                    "action": "已加入观察池" if saved_mode == "created" else "已更新观察池",
                    "quant_label": result.get("quant_label"),
                    "quant_score": result.get("quant_score"),
                }
            )
            self.send_json(
                {
                    "ok": True,
                    "mode": saved_mode,
                    "stock": stock,
                    "watchlist_count": len(config.get("stocks", [])),
                    "watchlist": watchlist_snapshot(config),
                }
            )
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def save_valuation_snapshot(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            symbol = normalize_symbol(payload.get("symbol", ""))
            value = float(payload.get("value"))
            if not symbol or not (0 <= value <= 1):
                raise ValueError("估值分位请输入 0 到 1 之间的小数，例如 0.72。")
            config = load_config(DEFAULT_CONFIG)
            stock = None
            for item in config.get("stocks", []):
                if normalize_symbol(item.get("symbol", "")) == symbol:
                    stock = item
                    break
            if stock is None:
                raise ValueError("只能先为预设股票保存估值分位快照。")
            history = stock.setdefault("valuation_percentile_history", [])
            history.append({"date": payload.get("date") or dt.date.today().isoformat(), "value": value})
            stock["valuation_percentile_source"] = payload.get("source") or "手动录入"
            save_config(config)
            self.send_json({"ok": True, "history": history})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def send_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC / relative).resolve()
        if STATIC not in target.parents and target != STATIC:
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("Stock Guard running at http://127.0.0.1:8787")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
