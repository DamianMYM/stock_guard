# 鼓手

鼓手是一个本地优先的 A 股研究助手。它把估值、安全边际、公告解读、候选股排序、观察池记录和本地 LLM 放在一起，目标不是替你下单，而是帮助你更快完成研究判断。

![鼓手图标](web/assets/stock-guard-tiger.png)

## 项目定位

- 本地运行：核心服务跑在你的电脑上，不依赖云端数据库。
- 研究辅助：提供估值、财务快照、公告事件解读和候选股优先级排序。
- 模型可替换：默认接 Ollama，本地模型可继续微调和替换。
- 可打包：支持打包为 Windows EXE 和安装包。

## 当前能力

### 1. 个股估值与安全边际

- Graham 风格估值和安全边际判断
- 实时行情覆盖当前价
- 财务指标补齐与异常兜底
- 估值失败时给出原因，不直接返回空白结论

### 2. 公告与事件解读

- 抓取东方财富公告
- 用规则引擎识别订单、扩产、减持、诉讼、政策、涨价、出口限制等事件
- 输出偏利多、偏利空、偏中性的研究提示

### 3. 候选股优先级排序

- 不是“预测股价涨跌”
- 是把当前候选股按“谁更值得先研究”做本地排序
- 综合估值、成长、财务、公告线索和本地量化打分

### 4. 本地研究助手

- 对当前页面股票给出研究口径
- 支持显示思考过程
- 支持切换本地 Ollama 模型

### 5. 本地记录

- 观察池保存与更新
- 最近查看记录
- 本地历史不上传

## 技术结构

```text
Browser / EXE shell
  -> http://127.0.0.1:8787  (web_app.py)
  -> 估值 / 公告 / 排序 / 观察池 API
  -> http://127.0.0.1:11434 (Ollama)
```

主要目录：

- `web/`：前端页面
- `web_app.py`：本地 Web 服务
- `stock_guard.py`：估值与基础数据逻辑
- `intel_engine.py`：公告事件解读
- `quant_engine.py`：候选股排序与本地量化接口
- `core_model.py`：行业链路与研究框架补充
- `quant/`：本地排序模型训练脚本
- `ml/llm_finetune/`：本地 LLM 微调脚本

## 本地启动

### 方式 1：源码模式

```powershell
cd G:\Projects\Stock_guard
python web_app.py
```

打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。

### 方式 2：EXE

如果你已经打包：

```text
dist\Gushou\Gushou.exe
```

注意 `Gushou.exe` 需要和 `_internal` 目录放在一起。

## Ollama

默认本地接口：

- `http://127.0.0.1:11434`

常见检查命令：

```powershell
ollama list
ollama ps
```

## 微调与量化

### LLM 微调

训练脚本位于：

- `ml/llm_finetune/train_qlora.py`
- `ml/llm_finetune/evaluate_qlora.py`
- `ml/llm_finetune/merge_adapter.py`
- `ml/llm_finetune/assemble_stockguard_corpus.py`

说明文档位于：

- `ml/llm_finetune/README.md`

说明：

- 仓库默认不提交模型权重、训练输出、缓存和本地工具链
- 你需要自行下载基座模型与 `llama.cpp` / GGUF 工具

### 本地排序模型

脚本位于：

- `quant/run_local_pipeline.py`
- `quant/train_ranker.py`
- `quant/score_watchlist.py`

说明文档位于：

- `quant/README.md`

说明：

- 仓库默认不提交本地训练产物与导出的评分结果
- 当前量化模块更像“研究优先级排序器”，不是自动交易策略

## EXE 打包

如果你修改了代码，安装包不会自动更新。正常流程是：

1. 先在源码模式验证功能
2. 重新构建 EXE
3. 重新构建安装包
4. 再分发给其他人

本仓库包含：

- `stock_guard_desktop.spec`
- `installer.iss`
- `desktop_launcher.py`

## 仓库公开内容

这个仓库当前公开的是本地版能力，包括：

- 前端界面
- 本地估值逻辑
- 公告事件解读
- 观察池与本地记录
- Ollama 接入
- 本地候选股排序脚本
- 本地微调脚本

## 注意

- 这不是投资建议。
- 排序分数不等于未来涨幅预测。
- 本项目更适合做研究辅助和流程整理，不适合直接替代完整投研体系。
- 当前仓库里仍保留了一部分 `stock_guard` 命名的内部模块名，用于兼容既有脚本与代码结构；公开展示名称统一以“鼓手”为准。

## License

MIT
