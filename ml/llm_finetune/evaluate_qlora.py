#!/usr/bin/env python3
"""Compare the base model and a LoRA adapter on the held-out test split."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from train_qlora import DEEPSEEK_ASSISTANT_TEMPLATE, DEFAULT_DATA, DEFAULT_MODEL


ROOT = Path(__file__).resolve().parent
DEFAULT_ADAPTER = ROOT / "outputs" / "stockguard-qlora-v1" / "adapter"
DEFAULT_RESULTS = ROOT / "outputs" / "stockguard-qlora-v1" / "test_comparison.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--test-file", type=Path, default=DEFAULT_DATA / "test.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--max-samples", type=int, default=None)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode_example(tokenizer: AutoTokenizer, row: dict[str, Any], max_length: int) -> dict[str, torch.Tensor]:
    encoded = tokenizer.apply_chat_template(
        row["messages"],
        tokenize=True,
        add_generation_prompt=False,
        return_dict=True,
        return_assistant_tokens_mask=True,
    )
    input_ids = encoded["input_ids"][-max_length:]
    assistant_mask = encoded["assistant_masks"][-max_length:]
    labels = [token if mask else -100 for token, mask in zip(input_ids, assistant_mask)]
    if not any(label != -100 for label in labels[1:]):
        raise ValueError(f"Example {row.get('id')} has no assistant labels after truncation")
    return {
        "input_ids": torch.tensor([input_ids], dtype=torch.long, device="cuda"),
        "attention_mask": torch.ones((1, len(input_ids)), dtype=torch.long, device="cuda"),
        "labels": torch.tensor([labels], dtype=torch.long, device="cuda"),
    }


def evaluate_model(model: torch.nn.Module, encoded_rows: list[tuple[dict, dict]]) -> dict[str, Any]:
    model.eval()
    total_loss = 0.0
    total_tokens = 0
    total_correct = 0
    elapsed_start = time.perf_counter()
    per_example = []

    with torch.inference_mode():
        for row, batch in encoded_rows:
            outputs = model(**batch)
            shifted_labels = batch["labels"][:, 1:]
            active = shifted_labels.ne(-100)
            token_count = int(active.sum().item())
            predictions = outputs.logits[:, :-1].argmax(dim=-1)
            correct = int((predictions.eq(shifted_labels) & active).sum().item())
            loss = float(outputs.loss.item())
            total_loss += loss * token_count
            total_tokens += token_count
            total_correct += correct
            per_example.append(
                {
                    "id": row.get("id"),
                    "task": row.get("task"),
                    "loss": loss,
                    "tokens": token_count,
                    "accuracy": correct / token_count,
                }
            )

    mean_loss = total_loss / total_tokens
    by_task: dict[str, dict[str, float]] = {}
    grouped = defaultdict(list)
    for item in per_example:
        grouped[item["task"]].append(item)
    for task, items in sorted(grouped.items()):
        tokens = sum(item["tokens"] for item in items)
        task_loss = sum(item["loss"] * item["tokens"] for item in items) / tokens
        task_accuracy = sum(item["accuracy"] * item["tokens"] for item in items) / tokens
        by_task[task] = {
            "samples": len(items),
            "loss": round(task_loss, 6),
            "perplexity": round(math.exp(min(task_loss, 20)), 6),
            "token_accuracy": round(task_accuracy, 6),
        }

    return {
        "samples": len(per_example),
        "assistant_tokens": total_tokens,
        "loss": round(mean_loss, 6),
        "perplexity": round(math.exp(min(mean_loss, 20)), 6),
        "token_accuracy": round(total_correct / total_tokens, 6),
        "elapsed_seconds": round(time.perf_counter() - elapsed_start, 3),
        "by_task": by_task,
        "per_example": per_example,
    }


def main() -> int:
    args = parse_args()
    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Base model not found: {model_path}")
    if not (args.adapter / "adapter_model.safetensors").exists():
        raise FileNotFoundError(f"LoRA adapter not found: {args.adapter}")
    if not args.test_file.exists():
        raise FileNotFoundError(f"Test data not found: {args.test_file}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for evaluation")

    rows = read_jsonl(args.test_file)
    if args.max_samples:
        rows = rows[: args.max_samples]

    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, use_fast=True)
    tokenizer.chat_template = DEEPSEEK_ASSISTANT_TEMPLATE
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    encoded_rows = [(row, encode_example(tokenizer, row, args.max_length)) for row in rows]

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        model_path,
        quantization_config=quantization_config,
        dtype=torch.bfloat16,
        device_map={"": 0},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    base_model.config.use_cache = False
    print("Evaluating base model...")
    base_metrics = evaluate_model(base_model, encoded_rows)

    adapted_model = PeftModel.from_pretrained(base_model, args.adapter, is_trainable=False)
    print("Evaluating LoRA adapter...")
    adapter_metrics = evaluate_model(adapted_model, encoded_rows)

    loss_change = adapter_metrics["loss"] - base_metrics["loss"]
    accuracy_change = adapter_metrics["token_accuracy"] - base_metrics["token_accuracy"]
    result = {
        "base_model": str(model_path.resolve()),
        "adapter": str(args.adapter.resolve()),
        "test_file": str(args.test_file.resolve()),
        "base": base_metrics,
        "adapter_metrics": adapter_metrics,
        "comparison": {
            "loss_change": round(loss_change, 6),
            "loss_change_percent": round(loss_change / base_metrics["loss"] * 100, 3),
            "token_accuracy_change": round(accuracy_change, 6),
            "adapter_improved_loss": loss_change < 0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"base": base_metrics, "adapter": adapter_metrics, "comparison": result["comparison"]}, ensure_ascii=False, indent=2))
    print(f"Full results saved to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
