# 鼓手 LLM Fine-tuning

这个目录用于在 Windows 11 本机上完成鼓手的本地微调、评估、合并、GGUF 导出和 Ollama 接入。

## 当前环境

当前训练环境：

```powershell
conda activate stock_llm
cd G:\Projects\Stock_guard\ml\llm_finetune
```

模型目录：

```text
G:\Projects\Stock_guard\ml\llm_finetune\models\DeepSeek-R1-Distill-Qwen-7B
```

## 数据集

### 1. DISC 基础数据

```powershell
python prepare_data.py
```

输出：

```text
datasets\processed\disc_stockguard
```

### 2. 鼓手混合数据集

```powershell
python assemble_stockguard_corpus.py
```

输出：

```text
datasets\processed\stockguard_mix
```

这版混合数据集包含：

- DISC-FinLLM 的基础金融问答
- FinChina-SA 的事件情绪样本
- CFEED 的公告事件抽取样本
- 本地手工整理的鼓手研究口径样本

## 训练

### 烟雾测试

```powershell
python train_qlora.py --smoke-test
```

### 轻量训练

```powershell
python train_qlora.py `
  --train-file datasets\processed\stockguard_mix\train.jsonl `
  --validation-file datasets\processed\stockguard_mix\validation.jsonl `
  --epochs 1 `
  --max-train-samples 256 `
  --max-validation-samples 64 `
  --gradient-accumulation 8 `
  --max-length 1536 `
  --output-dir outputs\stockguard-qlora-v2-mini
```

当前已完成的产物：

- adapter：`outputs\stockguard-qlora-v2-mini\adapter`
- 评估结果：`outputs\stockguard-qlora-v2-mini\test_comparison.json`

## 评估

```powershell
python evaluate_qlora.py `
  --adapter outputs\stockguard-qlora-v2-mini\adapter `
  --test-file datasets\processed\stockguard_mix\test.jsonl `
  --output outputs\stockguard-qlora-v2-mini\test_comparison.json `
  --max-samples 64 `
  --max-length 1536
```

本次已验证：

- base loss：`3.784885`
- adapter loss：`0.765677`
- base token accuracy：`0.453743`
- adapter token accuracy：`0.839747`

## 合并与导出

### 合并 LoRA

```powershell
python merge_adapter.py `
  --adapter outputs\stockguard-qlora-v2-mini\adapter `
  --output-dir outputs\stockguard-merged-v2-mini-bf16
```

### 导出 BF16 GGUF

```powershell
python tools\llama.cpp-b9758\convert_hf_to_gguf.py `
  outputs\stockguard-merged-v2-mini-bf16 `
  --outfile outputs\stockguard-ft-v2-mini-bf16.gguf `
  --outtype bf16
```

### 量化成 Q4_K_M

```powershell
tools\llama-bin\llama-quantize.exe `
  outputs\stockguard-ft-v2-mini-bf16.gguf `
  outputs\stockguard-ft-v2-mini-q4_k_m.gguf `
  Q4_K_M
```

## 接入 Ollama

`Modelfile.stockguard-ft` 当前已经指向：

```text
outputs\stockguard-ft-v2-mini-q4_k_m.gguf
```

创建模型：

```powershell
ollama create stockguard-ft-v2:q4 -f Modelfile.stockguard-ft
```

查看：

```powershell
ollama list
ollama show stockguard-ft-v2:q4
```

## Windows 注意事项

- 训练前尽量停掉占显存的 ComfyUI、视频模型或其他大模型任务。
- Ollama 中已加载的大模型也会占显存，必要时先 `ollama stop <model>`。
- 第一版训练不需要 FlashAttention，当前脚本使用 PyTorch SDPA。
- `dataloader_num_workers=0` 更适合 Windows。
- 长路径和大文件都建议放在 G 盘。

## 推荐的继续优化方向

- 增加更多行业链、政策解读、公告摘要、财报问答样本
- 引入更严格的人工评测集，而不只看 token accuracy
- 做多轮版本对比，例如 `v2-mini`、`v2-full`、`v3-sector`
- 根据前端真实对话日志补“用户问法 -> 研究结论”的高频样本
