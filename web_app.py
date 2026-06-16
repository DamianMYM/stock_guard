#!/usr/bin/env python3
"""Local web UI for stock_guard."""

from __future__ import annotations

import json
import mimetypes
import re
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import parse_qs, urlparse

from stock_guard import (
    DEFAULT_CONFIG,
    evaluate,
    fetch_financial_snapshot,
    fetch_financial_trends,
    fetch_sina_quote,
    find_stock,
    load_config,
    normalize_symbol,
)


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web"
OLLAMA_BASE = "http://127.0.0.1:11434"


def save_config(config: dict) -> None:
    DEFAULT_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def strip_thinking(text: str) -> str:
    """DeepSeek R1 often returns <think> blocks; keep the user-facing answer only."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


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
        if parsed.path == "/api/trends":
            self.send_trends(parsed.query)
            return
        self.send_static(parsed.path)

    def do_POST(self) -> None:
        if self.path == "/api/llm/chat":
            self.send_llm_chat()
            return
        if self.path == "/api/valuation-snapshot":
            self.save_valuation_snapshot()
            return
        if self.path != "/api/evaluate":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            config = load_config(DEFAULT_CONFIG)
            stock = find_stock(config, payload.get("symbol", "")) or {}
            snapshot = fetch_financial_snapshot(normalize_symbol(payload.get("symbol", "")))
            if snapshot:
                stock.update({k: v for k, v in snapshot.items() if v is not None})
            stock.update({k: v for k, v in payload.items() if v not in ("", None)})
            if not stock.get("symbol"):
                raise ValueError("请输入股票代码")
            result = evaluate(stock, config, live=bool(payload.get("live")))
            self.send_json({"ok": True, "result": result})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def send_llm_models(self) -> None:
        try:
            with request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=6) as response:
                data = json.loads(response.read().decode("utf-8"))
            models = data.get("models", [])
            self.send_json({"ok": True, "models": models})
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": f"未连接到本地 Ollama：{exc}"}, status=502)

    def send_llm_chat(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            model = payload.get("model") or "deepseek-r1:8b"
            message = str(payload.get("message") or "").strip()
            context = payload.get("context") or {}
            if not message:
                raise ValueError("请输入要问本地模型的问题。")

            system_prompt = (
                "你是鼓手 Stock Guard 的本地投资研究助手。"
                "你只能基于用户提供的行情、估值、财务上下文做解释和风控建议；"
                "不要编造实时数据，不要承诺收益，不要给出确定性买卖指令。"
                "输出要简洁、具体、中文回答。"
            )
            user_prompt = (
                "当前鼓手页面上下文如下，可能包含股票代码、实时价、估值、仓位和用户输入参数：\n"
                f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
                f"用户问题：{message}"
            )
            ollama_payload = {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            req = request.Request(
                f"{OLLAMA_BASE}/api/chat",
                data=json_bytes(ollama_payload),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started = dt.datetime.now()
            with request.urlopen(req, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
            elapsed = (dt.datetime.now() - started).total_seconds()
            content = strip_thinking(data.get("message", {}).get("content", ""))
            self.send_json(
                {
                    "ok": True,
                    "model": model,
                    "answer": content or "本地模型没有返回内容。",
                    "basis": context_basis(context),
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
        stock = find_stock(config, symbol)
        if not stock:
            stock = {"symbol": normalize_symbol(symbol)}
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

    def send_trends(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        trends = fetch_financial_trends(symbol)
        if not trends:
            self.send_json({"ok": False, "error": "未能获取历史趋势"}, status=502)
            return
        config = load_config(DEFAULT_CONFIG)
        stock = find_stock(config, symbol) or {}
        history = stock.get("valuation_percentile_history", [])
        trends["valuation_percentile"] = history
        trends["valuation_percentile_source"] = stock.get("valuation_percentile_source", "待接入")
        self.send_json({"ok": True, "trends": trends})

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
            snapshot = {"date": payload.get("date") or dt.date.today().isoformat(), "value": value}
            history.append(snapshot)
            history.sort(key=lambda item: item["date"])
            stock["valuation_percentile_source"] = payload.get("source") or stock.get("valuation_percentile_source", "手动录入")
            save_config(config)
            self.send_json({"ok": True, "snapshot": snapshot, "history": history})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def send_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve():
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("Stock Guard web UI: http://127.0.0.1:8787")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
