# 鼓手 Stock Guard

这个小工具用 Benjamin Graham 风格的安全边际做观察清单。它不会自动交易，只会根据你设置的估值假设、目标仓位和当前价格给出纪律性提示。

## 运行

```bash
cd /Users/damianma/Documents/ownproject/stock_guard
python3 stock_guard.py
```

使用实时行情：

```bash
python3 stock_guard.py --live
```

记录每天信号：

```bash
python3 stock_guard.py --live --log
```

出现可行动信号时弹出 macOS 通知：

```bash
python3 stock_guard.py --live --log --notify
```

## 网页版

启动本地页面：

```bash
cd /Users/damianma/Documents/ownproject/stock_guard
python3 web_app.py
```

然后打开：

```text
http://127.0.0.1:8787
```

页面支持输入股票代码或简称，自动拉取实时行情，并从新浪财务指标页抓取最新可得的研究指标；也可以手动覆盖 `PE(TTM)`、`EPS(TTM)`、`BVPS`、计划投入和最低安全边际门槛。

## 本地模型助手

鼓手可以连接 Mac 本地的 Ollama / DeepSeek 模型。当前逻辑是：

- 鼓手不会自动启动 Ollama。
- 鼓手启动后，会访问 `http://127.0.0.1:11434/api/tags` 检测本地模型。
- 如果 Ollama 已经在后台运行，页面右侧会显示 `已连接 Ollama`。
- 如果 Ollama 没有运行，聊天框会提示先运行 `ollama serve`。

手动启动 Ollama：

```bash
ollama serve
```

如果你已经通过 Ollama App 或后台服务启动过 Ollama，通常不需要重复执行上面的命令。

查看本机已有模型：

```bash
ollama list
```

鼓手当前会优先选择：

```text
deepseek-r1:8b
```

如果没有 8B 模型，会尝试使用其它 DeepSeek 模型。`bge-m3` 属于向量/Embedding 模型，不适合作为聊天模型，页面会默认过滤掉。

本地模型助手会读取当前页面上下文，包括：

- 股票代码和名称
- 当前价
- PE(TTM)、EPS(TTM)、BVPS
- 安全边际、买入线、仓位
- 鼓手已经计算出的纪律判断

注意：本地模型不会自动获得页面外新闻和实时资讯。它解释的是鼓手已经抓取到的数据，不替代实时行情源或人工判断。

新增研究面板会展示：

- 营收同比
- 净利同比
- ROE
- 经营现金流指标
- 四轨判断：价值纪律、成长观察、仓位风险、基本面研究

## 配置

编辑 `config.json`：

- `portfolio_cash`: 当前总资金。
- `planned_investment`: 本轮计划投入资金。
- `required_margin_of_safety`: 要求安全边际，`0.3` 表示 30%。
- `max_single_stock_weight`: 单只股票最高仓位，`0.35` 表示最多 35%。
- `pe_ttm`: 滚动市盈率。
- `eps_ttm`: 滚动 12 个月每股收益；不填时会用 `价格 / PE(TTM)` 估算。
- `bvps`: 每股净资产，用来计算 Graham Number。
- `target_pe`: 你愿意给这家公司多少倍合理市盈率。
- `growth_rate`: 未来长期增长假设，`0.08` 表示 8%。
- `aaa_yield`: Graham 增长公式中的债券收益率假设。

## 公式

```text
EPS(TTM) = 当前股价 / PE(TTM)
目标PE估值 = EPS(TTM) * 目标PE
Graham增长估值 = EPS(TTM) * (8.5 + 2g) * 4.4 / Y
Graham Number = sqrt(22.5 * EPS(TTM) * BVPS)
保守价值 = min(目标PE估值, Graham增长估值, Graham Number)
实际安全边际 = (保守价值 - 当前价格) / 保守价值
买入线 = 保守价值 * (1 - 最低安全边际门槛)
```

注意：最低安全边际门槛由投资者设定，实际安全边际由价格和估算价值计算出来。

## 定时运行

最简单的方式是用 Mac 的 `cron` 或 `launchd` 定时执行：

```bash
python3 /Users/damianma/Documents/ownproject/stock_guard/stock_guard.py --live --log --notify
```

建议只在交易日交易时间内运行，比如上午 10:00、下午 14:30、收盘后 15:10 各跑一次。

本目录已经放了一个 `launchd` 模板：`com.local.stockguard.plist`。启用方式：

```bash
cp /Users/damianma/Documents/ownproject/stock_guard/com.local.stockguard.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.local.stockguard.plist
```

停止方式：

```bash
launchctl unload ~/Library/LaunchAgents/com.local.stockguard.plist
```

## 更新日志

### 2026-05-12

- 新增 Web 页面和 Mac 本地服务。
- 修复安全边际门槛百分数输入逻辑，`24` 表示 `24%`。
- 修复股票切换时旧财务参数残留的问题。
- 修复 BVPS 四位小数输入校验。
- 左侧当前价会与实时行情同步。
- 品牌更新为 `鼓手 Stock Guard`，形象更新为敲鼓小老虎。
- 新增长线精选与进场节奏判断，用于辅助长线投资机会筛选。
- 新增第四条 `基本面研究` 判断。
- 新增研究面板与轻量图表。
- 新增新浪财务指标自动抓取，默认刷新最新报告期的 `最新报告期EPS / BVPS / ROE / 营收增速 / 净利增速 / 每股经营现金流`。
- 明确区分 `最新报告期 EPS` 与估值公式中的 `EPS(TTM)`，避免把单季/单期 EPS 误用于估值。
- 新增估值分位快照接入：首页和趋势页可展示最近可得的 PE 分位记录。
- 估值分位当前采用公开页面搜索快照，适合观察位置变化，不应视为逐日完备历史库。
- 趋势页新增 `保存估值快照`，可手动追加新的分位记录并持久化到 `config.json`。
- 新增 `刷新研究指标` 按钮，并保留手动覆盖能力。
- 新增本地模型研究助手：通过 Ollama 调用本机 DeepSeek 模型，对当前股票页面数据提问。
- 小老虎形象变成交互入口：点击后自动生成当前股票的仓位/进场问题。
- 本地模型回复新增依据摘要和耗时显示，便于核对模型使用了哪些页面数据。
- 新增开发教程文档：`DEVELOPMENT_TUTORIAL.md`。

## 后续方向

- 历史趋势页已加入：从详情页进入，可查看近四个报告期的营收增速、净利增速和 ROE 趋势图。
- 股票对比页已加入：首页点击 `股票对比`，输入两支股票即可比较。
- Windows 简易安装包：已补 `desktop_launcher.py` 与 `stock_guard_desktop.spec`。

### PyInstaller 打包

先安装：

```bash
python3 -m pip install pyinstaller
```

在 macOS 上可先验证：

```bash
pyinstaller stock_guard_desktop.spec
```

Windows 版建议在 Windows 机器上执行同一条命令，这样产出的 `StockGuard.exe` 更适合直接分发给家人使用。
