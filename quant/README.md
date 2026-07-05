# 鼓手 Quant

这个目录是鼓手当前的本地量化模块。它的目标不是直接预测“明天涨不涨”，而是先把估值、财务、公告和仓位信息整理成结构化特征，再训练一个本地排序模型，为前端提供“更值得继续研究谁”的量化分数。

## 当前文件

- `build_training_frame.py`
  - 从当前观察池导出特征表
- `bootstrap_labeled_data.py`
  - 用当前特征生成可运行的 bootstrap 标注集
- `train_ranker.py`
  - 训练第一版表格模型，优先用 LightGBM，没有就退回 `HistGradientBoostingRegressor`
- `score_watchlist.py`
  - 给当前观察池打分
- `run_local_pipeline.py`
  - 一键串起整条本地训练链

## 当前已跑通的模型

模型目录：

```text
G:\Projects\Stock_guard\quant\outputs\future20_bootstrap
```

关键文件：

- `model.joblib`
- `metrics.json`

最近一次训练结果：

- 训练集：`1040` 行
- 测试集：`260` 行
- 目标：`future_20d_excess_return`
- 模型：`hist_gradient_boosting`
- `mae`: `0.02479`
- `r2`: `0.35348`

## 一键运行

```powershell
cd G:\Projects\Stock_guard\quant
python run_local_pipeline.py --samples-per-stock 260
```

会依次完成：

1. 生成 bootstrap 标注集
2. 训练排序模型
3. 生成当前观察池特征
4. 对当前观察池打分

输出文件：

- `data\training_labeled.bootstrap.csv`
- `outputs\future20_bootstrap\model.joblib`
- `outputs\future20_bootstrap\metrics.json`
- `data\watchlist_features.csv`
- `data\watchlist_scores.csv`

## 当前使用的特征

当前模型会用到这些方向的特征：

- 估值：`price`、`pe_ttm`、`pb`、`margin_of_safety`、`conservative_value`、`buy_below`
- 质量：`revenue_growth`、`profit_growth`、`roe`、`operating_cash_flow_growth`
- 风险：`high_pe_flag`、`high_pb_flag`、`negative_eps_flag`、`planned_weight`
- 事件：`headline_score`、`positive_news_count`、`negative_news_count`、`mixed_news_count`

## 当前版本的定位

这版量化模型是 bootstrap 版，重点是把以下链路做完整：

- 特征生成
- 本地训练
- 本地模型发现
- 前端接口接入
- 量化分数解释

也就是说，它已经是一个能跑、能接前端、能继续迭代的数据产品骨架，但还不是最终的真实历史回测版。

## 下一步建议

后面建议往这三个方向升级：

1. 用真实历史快照替代 bootstrap 标注
2. 接入更多行业事件和政策因子
3. 把排序分数和前端研究面板做更细的解释联动

## 真实历史版建议的数据结构

理想状态下，一行训练样本应该表示：

- 某只股票
- 某一天的可观测快照
- 当时能看到的估值、财务、事件、仓位特征
- 未来 20 / 60 个交易日的收益与回撤标签

目标标签建议继续沿用：

- `future_20d_excess_return`
- `future_60d_excess_return`
- `max_drawdown_20d`

## 与前端的关系

量化模型不会替代 LLM。

更合适的职责分工是：

- 量化模型负责排序、打分、给出因子
- LLM 负责把这些因子翻译成用户能理解的研究结论、风险提示和观察条件
