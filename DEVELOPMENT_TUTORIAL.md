# 鼓手 Stock Guard 开发教程

这份文档用于学习如何从零写出一个本地股票监控工具。目标不是一次写完所有功能，而是按小步骤构建：先能计算，再能抓行情，再能显示页面，最后接入本地大模型。

说明：这里展示的是工程思路、拆解方法和关键代码写法，不是模型的隐藏推理链。你可以按顺序敲代码，每完成一步就运行一次验证。

## 0. 项目目标

我们要做一个本地应用，名字叫“鼓手 Stock Guard”。

它要完成几件事：

- 输入 A 股股票代码。
- 获取实时行情。
- 获取或手动填写 PE、EPS、BVPS 等估值参数。
- 用 Graham 风格公式计算安全边际。
- 用网页展示结果。
- 接入 Mac 本地 Ollama / DeepSeek，让模型基于当前页面数据回答问题。

它不做的事：

- 不自动交易。
- 不保证收益。
- 不把 Graham 公式当成短期股价预测。
- 不让本地模型编造页面外资讯。

## 1. 建立目录

先创建项目目录：

```bash
mkdir -p /Users/damianma/Documents/ownproject/stock_guard
cd /Users/damianma/Documents/ownproject/stock_guard
mkdir -p web web/assets
```

最初的目录结构可以很简单：

```text
stock_guard/
  stock_guard.py
  web_app.py
  config.json
  web/
    index.html
    app.js
    styles.css
```

## 2. 写第一个函数：格式化股票代码

为什么先写这个函数？

因为用户可能输入 `600879`、`600879.SH`、`sh600879`、`航天电子`。程序内部必须统一成一种格式，否则后面抓行情、查配置都会混乱。

先在 `stock_guard.py` 写：

```python
def normalize_symbol(value: str) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    if raw.endswith(".SH") or raw.endswith(".SZ"):
        return raw
    if raw.startswith("SH") and len(raw) == 8:
        return f"{raw[2:]}.SH"
    if raw.startswith("SZ") and len(raw) == 8:
        return f"{raw[2:]}.SZ"
    if raw.startswith("6") and len(raw) == 6:
        return f"{raw}.SH"
    if raw.startswith(("0", "3")) and len(raw) == 6:
        return f"{raw}.SZ"
    return raw
```

运行一个快速验证：

```bash
python3 -c "from stock_guard import normalize_symbol; print(normalize_symbol('600879'))"
```

你应该看到：

```text
600879.SH
```

这个函数的设计原则：

- 输入可以宽松。
- 内部格式必须严格。
- 失败时返回原始大写值，方便后续提示错误。

## 3. 写配置文件

创建 `config.json`：

```json
{
  "portfolio_cash": 100000,
  "planned_investment": 10000,
  "required_margin_of_safety": 0.3,
  "max_single_stock_weight": 0.35,
  "stocks": [
    {
      "symbol": "600879.SH",
      "name": "航天电子",
      "pe_ttm": 368,
      "eps_ttm": 0.07,
      "bvps": 6.3288,
      "target_pe": 20,
      "growth_rate": 0.08
    }
  ]
}
```

这里的关键点：

- `required_margin_of_safety` 用小数存储，`0.3` 表示 30%。
- 前端可以让用户输入 `30`，但后端计算时要转成 `0.3`。
- 配置文件只保存默认值，页面输入可以覆盖它。

## 4. 读取配置

在 `stock_guard.py` 中写：

```python
import json
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)
```

验证：

```bash
python3 -c "from stock_guard import load_config; print(load_config()['portfolio_cash'])"
```

应该输出：

```text
100000
```

## 5. 从配置中查股票

继续写：

```python
def find_stock(config: dict, query: str) -> dict | None:
    normalized = normalize_symbol(query)
    raw = str(query or "").strip()
    for stock in config.get("stocks", []):
        if normalize_symbol(stock.get("symbol", "")) == normalized:
            return dict(stock)
        if raw and raw == stock.get("name"):
            return dict(stock)
    return None
```

为什么返回 `dict(stock)`？

因为这样可以得到一份拷贝，后续合并实时行情或页面输入时，不会直接污染配置里的原始对象。

验证：

```bash
python3 -c "from stock_guard import load_config, find_stock; print(find_stock(load_config(), '600879')['name'])"
```

## 6. 写 Graham 估值函数

Graham 风格估值不是一个万能买卖公式，它主要用于提醒“贵不贵”。先把公式写清楚。

```python
import math


def graham_growth_value(eps: float, growth_rate: float, aaa_yield: float = 4.4) -> float:
    return eps * (8.5 + 2 * growth_rate * 100) * 4.4 / aaa_yield


def graham_number(eps: float, bvps: float) -> float | None:
    if eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)
```

注意 `growth_rate`：

- 配置里写 `0.08`。
- 公式中 `2g` 常用的是百分数口径，所以要乘 `100`。

验证：

```bash
python3 -c "from stock_guard import graham_growth_value; print(graham_growth_value(0.07, 0.08))"
```

## 7. 写核心评估函数

核心评估函数要做四件事：

1. 确认价格、EPS、BVPS。
2. 计算三种估值。
3. 取最保守的估值。
4. 输出安全边际、买入线、仓位风险。

简化版：

```python
def evaluate(stock: dict, config: dict) -> dict:
    price = float(stock["today_close"])
    pe_ttm = float(stock.get("pe_ttm") or 0)
    eps = float(stock.get("eps_ttm") or 0)
    bvps = float(stock.get("bvps") or 0)
    target_pe = float(stock.get("target_pe") or 20)
    growth_rate = float(stock.get("growth_rate") or 0)

    if eps <= 0 and pe_ttm > 0:
        eps = price / pe_ttm

    target_pe_value = eps * target_pe
    growth_value = graham_growth_value(eps, growth_rate)
    number_value = graham_number(eps, bvps)

    candidates = [target_pe_value, growth_value]
    if number_value is not None:
        candidates.append(number_value)
    conservative_value = min(candidates)

    required_margin = float(
        stock.get("required_margin_of_safety")
        or config.get("required_margin_of_safety")
        or 0.3
    )
    buy_below = conservative_value * (1 - required_margin)
    margin = (conservative_value - price) / conservative_value

    planned_amount = float(
        stock.get("planned_amount")
        or config.get("planned_investment")
        or 0
    )
    portfolio_cash = float(config.get("portfolio_cash") or 1)
    planned_weight = planned_amount / portfolio_cash

    return {
        "symbol": stock["symbol"],
        "name": stock.get("name", stock["symbol"]),
        "price": price,
        "pe_ttm": pe_ttm,
        "eps_ttm": eps,
        "bvps": bvps,
        "target_pe_value": target_pe_value,
        "graham_growth_value": growth_value,
        "graham_number": number_value,
        "conservative_value": conservative_value,
        "buy_below": buy_below,
        "margin_of_safety": margin,
        "required_margin_of_safety": required_margin,
        "planned_weight": planned_weight,
    }
```

这一版先不追求完整，只要能跑。之后再增加 `value_view`、`position_view`、`entry_timing_view`。

## 8. 写命令行入口

让程序先能在命令行工作：

```python
def main() -> int:
    config = load_config()
    stock = find_stock(config, "600879.SH")
    stock["today_close"] = 23.13
    result = evaluate(stock, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

运行：

```bash
python3 stock_guard.py
```

工程原则：先让核心逻辑脱离网页运行。这样后面页面出问题时，你能判断是计算错了，还是前端展示错了。

## 9. 接入新浪实时行情

新浪行情接口格式大致是：

```text
http://hq.sinajs.cn/list=sh600879
```

A 股代码转换：

```python
def sina_code(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    code, market = normalized.split(".")
    return f"{market.lower()}{code}"
```

抓行情：

```python
from dataclasses import dataclass
from urllib import request


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float
    amount: float
    time: str


def fetch_sina_quote(symbol: str) -> Quote | None:
    code = sina_code(symbol)
    req = request.Request(
        f"http://hq.sinajs.cn/list={code}",
        headers={
            "Referer": "http://finance.sina.com.cn/",
            "User-Agent": "Mozilla/5.0",
        },
    )
    text = request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
    payload = text.split('"')[1]
    parts = payload.split(",")
    if len(parts) < 32:
        return None
    return Quote(
        symbol=normalize_symbol(symbol),
        name=parts[0],
        open=float(parts[1]),
        prev_close=float(parts[2]),
        price=float(parts[3]),
        high=float(parts[4]),
        low=float(parts[5]),
        volume=float(parts[8]),
        amount=float(parts[9]),
        time=f"{parts[30]} {parts[31]}",
    )
```

验证：

```bash
python3 -c "from stock_guard import fetch_sina_quote; print(fetch_sina_quote('600879.SH'))"
```

## 10. 建立本地 Web 服务

不用一开始就上 Flask。这个项目只需要本地服务，用 Python 标准库够用。

创建 `web_app.py`：

```python
#!/usr/bin/env python3

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from stock_guard import load_config, find_stock, evaluate, fetch_sina_quote, normalize_symbol

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web"


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
```

定义 Handler：

```python
class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/quote":
            self.send_quote(parsed.query)
            return
        self.send_static(parsed.path)

    def send_quote(self, query: str) -> None:
        symbol = normalize_symbol(parse_qs(query).get("symbol", [""])[0])
        quote = fetch_sina_quote(symbol)
        if not quote:
            self.send_json({"ok": False, "error": "未能获取实时行情"}, status=502)
            return
        self.send_json({"ok": True, "quote": quote.__dict__})

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
        data = target.read_bytes()
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
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
```

启动服务：

```python
def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("Stock Guard web UI: http://127.0.0.1:8787")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

运行：

```bash
python3 web_app.py
```

测试：

```bash
curl "http://127.0.0.1:8787/api/quote?symbol=600879.SH"
```

## 11. 写第一个网页

`web/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>鼓手 Stock Guard</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <main class="shell">
      <section class="panel">
        <h1>鼓手</h1>
        <input id="symbol" value="600879.SH" />
        <button id="quoteButton">只拉行情</button>
        <pre id="output"></pre>
      </section>
    </main>
    <script src="app.js"></script>
  </body>
</html>
```

`web/app.js`：

```javascript
const output = document.querySelector("#output");
const symbolInput = document.querySelector("#symbol");

async function requestJson(path, options) {
  const response = await fetch(path, options);
  return response.json();
}

async function loadQuote() {
  const symbol = symbolInput.value.trim();
  const data = await requestJson(`/api/quote?symbol=${encodeURIComponent(symbol)}`);
  output.textContent = JSON.stringify(data, null, 2);
}

document.querySelector("#quoteButton").addEventListener("click", loadQuote);
```

`web/styles.css`：

```css
body {
  margin: 0;
  background: #f5f5f7;
  color: #1d1d1f;
  font: 16px/1.45 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
}

.shell {
  width: min(960px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 40px 0;
}

.panel {
  background: white;
  border-radius: 8px;
  padding: 20px;
}
```

现在访问：

```text
http://127.0.0.1:8787
```

点击按钮，应该能看到行情 JSON。

## 12. 增加 `/api/evaluate`

网页不能只拉行情，还要得到投资纪律判断。因此增加 POST 接口。

在 `web_app.py` 的 `do_POST`：

```python
def do_POST(self) -> None:
    if self.path != "/api/evaluate":
        self.send_error(404)
        return
    size = int(self.headers.get("Content-Length", "0"))
    try:
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        config = load_config()
        stock = find_stock(config, payload.get("symbol", "")) or {}
        stock.update({k: v for k, v in payload.items() if v not in ("", None)})
        result = evaluate(stock, config)
        self.send_json({"ok": True, "result": result})
    except Exception as exc:
        self.send_json({"ok": False, "error": str(exc)}, status=400)
```

前端提交：

```javascript
async function evaluateStock() {
  const payload = {
    symbol: symbolInput.value.trim(),
    today_close: Number(document.querySelector("#price").value),
    pe_ttm: Number(document.querySelector("#pe_ttm").value),
    eps_ttm: Number(document.querySelector("#eps_ttm").value),
    bvps: Number(document.querySelector("#bvps").value),
  };
  const data = await requestJson("/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  output.textContent = JSON.stringify(data, null, 2);
}
```

## 13. 前端表单的关键坑

前端输入框里的数字实际是字符串。

错误写法：

```javascript
payload.required_margin_of_safety = value;
```

如果用户输入 `30`，后端会当成 3000%。

正确写法：

```javascript
payload.required_margin_of_safety = Number(value) / 100;
```

这就是之前“输入 24 后买入线变负数”的根源之一：百分数口径必须在前端和后端明确。

## 14. 页面布局的演进

最早版本只有一个表单。后来用户需要边看结果边提问，所以布局改成三栏：

```text
左侧：查询参数
中间：股票评估结果
右侧：本地模型研究助手
```

CSS 核心：

```css
.workspace {
  display: grid;
  grid-template-columns: 380px minmax(560px, 1fr) 380px;
  gap: 18px;
  align-items: start;
}
```

为什么右侧助手要并排？

因为本地模型的价值不是“聊天”，而是“针对当前股票数据提问”。如果聊天框在页面底部，用户看不到数据，问题质量会下降。

## 15. 小老虎交互入口

一开始小老虎只是品牌图。后来把它改成按钮：

```html
<button type="button" class="mascot-stage" id="mascotAsk" aria-label="点击小老虎，向本地模型提问">
  <img src="assets/stock-guard-tiger.png" alt="敲鼓的可爱小老虎" />
  <span>点我提问</span>
</button>
```

JavaScript：

```javascript
function askFromMascot() {
  const label = lastEvaluation?.name || document.querySelector("#symbol").value.trim() || "这只股票";
  chatInput.value = `结合当前页面抓取的数据，判断${label}现在是否适合继续买入或加仓，并给出仓位、观察价位和止损纪律。`;
  chatInput.focus();
  chatInput.scrollIntoView({ behavior: "smooth", block: "center" });
}

document.querySelector("#mascotAsk").addEventListener("click", askFromMascot);
```

设计理由：

- 用户不用自己组织复杂问题。
- 小老虎不只是装饰，而是“提问入口”。
- 问题会自动带上当前股票名，降低使用成本。

## 16. 接入 Ollama

Ollama 默认服务地址：

```text
http://127.0.0.1:11434
```

查看模型接口：

```text
GET /api/tags
```

聊天接口：

```text
POST /api/chat
```

在 `web_app.py` 中增加：

```python
OLLAMA_BASE = "http://127.0.0.1:11434"
```

列模型：

```python
def send_llm_models(self) -> None:
    try:
        with request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
        self.send_json({"ok": True, "models": data.get("models", [])})
    except Exception as exc:
        self.send_json({"ok": False, "error": f"未连接到本地 Ollama：{exc}"}, status=502)
```

聊天：

```python
def send_llm_chat(self) -> None:
    size = int(self.headers.get("Content-Length", "0"))
    payload = json.loads(self.rfile.read(size).decode("utf-8"))
    model = payload.get("model") or "deepseek-r1:8b"
    message = payload.get("message") or ""
    context = payload.get("context") or {}

    ollama_payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": "你是鼓手 Stock Guard 的本地投资研究助手。不要编造实时数据，不要承诺收益。",
            },
            {
                "role": "user",
                "content": f"当前页面上下文：{json.dumps(context, ensure_ascii=False)}\n\n用户问题：{message}",
            },
        ],
    }
```

再把请求发给 Ollama：

```python
req = request.Request(
    f"{OLLAMA_BASE}/api/chat",
    data=json_bytes(ollama_payload),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with request.urlopen(req, timeout=180) as response:
    data = json.loads(response.read().decode("utf-8"))
```

## 17. 为什么不展示原始思考链

DeepSeek R1 类模型可能返回 `<think>...</think>`。在投资工具里，不建议把这段原样展示给用户。

原因：

- 原始推理链很长，降低阅读效率。
- 推理链并不等于事实依据。
- 投资判断更需要“用了哪些数据”和“结论是什么”。

所以鼓手采用：

```text
处理进度 + 依据摘要 + 最终回答
```

例如：

```text
读取当前页面数据 -> 发送给本地模型 -> 等待模型返回。

依据：股票：航天电子 / 当前价：23.13 / PE(TTM)：368 / 计划仓位：48.0%
耗时：21.9s
```

去掉 `<think>`：

```python
import re


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
```

## 18. 前端调用本地模型

前端读取模型列表：

```javascript
async function loadLlmModels() {
  const data = await requestJson("/api/llm/models");
  const models = data.models || [];
  llmModel.innerHTML = "";
  models
    .filter((model) => !String(model.name || model.model || "").includes("bge"))
    .forEach((model) => {
      const option = document.createElement("option");
      option.value = model.name || model.model;
      option.textContent = model.name || model.model;
      llmModel.appendChild(option);
    });
}
```

发送问题：

```javascript
async function sendChat() {
  const message = chatInput.value.trim();
  if (!message) return;

  const data = await requestJson("/api/llm/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: llmModel.value,
      message,
      context: {
        form: readForm(),
        evaluation: lastEvaluation,
      },
    }),
  });
}
```

关键点：

- `form` 是用户当前输入。
- `evaluation` 是鼓手刚算出的结果。
- 模型回答必须基于这两个对象。

## 19. Ollama 是否会自动启动

当前版本不会自动启动 Ollama。

原因：

- `ollama serve` 是独立服务，可能已经由 Ollama App 或后台服务管理。
- 鼓手自动拉起系统服务需要处理路径、权限、端口冲突和进程生命周期。
- 对本地工具来说，先显式检测和提示更稳。

当前使用方式：

```bash
ollama serve
```

然后启动鼓手：

```bash
python3 web_app.py
```

未来可以加一个自动启动逻辑：

```python
import subprocess


def ensure_ollama_running() -> None:
    try:
        request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
    except Exception:
        subprocess.Popen(["ollama", "serve"])
```

但这一步要谨慎，因为如果用户电脑上已有 Ollama App 管理进程，重复启动可能引起端口占用。

## 20. 验证清单

每次改完代码，至少跑这些：

```bash
python3 -m py_compile stock_guard.py web_app.py
```

检查前端语法：

```bash
node --check web/app.js
```

启动服务：

```bash
python3 web_app.py
```

检查模型：

```bash
curl http://127.0.0.1:8787/api/llm/models
```

检查股票评估：

```bash
curl -X POST http://127.0.0.1:8787/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600879.SH","live":true,"planned_amount":48000,"required_margin_of_safety":0.3}'
```

检查本地模型聊天：

```bash
curl -X POST http://127.0.0.1:8787/api/llm/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-r1:8b","message":"用一句话回答你是否收到上下文","context":{"evaluation":{"symbol":"600879.SH","name":"航天电子","price":23.13}}}'
```

## 21. 常见问题

### 页面显示未连接 Ollama

先运行：

```bash
ollama serve
```

再刷新页面。

### 模型很慢

本地模型速度取决于机器性能和模型大小。

优先使用：

```text
deepseek-r1:8b
```

`deepseek-r1:14b` 通常回答质量更好，但更慢。

### 安全边际为什么极低

因为公式里的保守价值很低，而当前价很高。

例如：

```text
EPS(TTM) = 0.07
目标 PE = 20
目标PE估值 = 1.40
当前价 = 23.13
```

这时 Graham 口径会认为它非常贵。这个结论不是预测股价会跌到 1.40，而是提示“这只股票不适合用低估值安全边际逻辑买入”。

### 为什么本地模型不能直接给实时新闻

因为当前接入方式只把页面上下文传给 Ollama。Ollama 本身没有联网能力，除非你额外开发新闻抓取接口，再把新闻摘要一起传给模型。

## 22. 下一步可以怎么做

后续可以继续增强：

- 自动启动 Ollama，并处理端口冲突。
- 增加资金流监控和异动预警。
- 给持仓增加成本价、买入日期、浮盈浮亏。
- 把新闻抓取结果传给本地模型。
- 增加“长线精选池”和“观察价位提醒”。
- 用 PyInstaller 打包成可双击启动的应用。

推荐学习顺序：

1. 先理解 `stock_guard.py` 的计算逻辑。
2. 再理解 `web_app.py` 如何把 Python 函数变成 API。
3. 再看 `web/app.js` 如何把表单和 API 连接起来。
4. 最后看 Ollama 接入，因为它本质上只是另一个 HTTP API。
