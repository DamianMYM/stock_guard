#!/usr/bin/env python3
"""Merge the trained LoRA adapter into the BF16 base model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from train_qlora import DEFAULT_MODEL, DEEPSEEK_ASSISTANT_TEMPLATE


ROOT = Path(__file__).resolve().parent
DEFAULT_ADAPTER = ROOT / "outputs" / "stockguard-qlora-v1" / "adapter"
DEFAULT_OUTPUT = ROOT / "outputs" / "stockguard-merged-bf16"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-shard-size", default="5GB")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.model / "config.json").exists():
        raise FileNotFoundError(f"Base model is incomplete: {args.model}")
    if not (args.adapter / "adapter_model.safetensors").exists():
        raise FileNotFoundError(f"LoRA adapter not found: {args.adapter}")

    print("Loading BF16 base model on the RTX GPU...")
    base_model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=torch.bfloat16,
        device_map={"": 0},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    print("Loading and safely merging the LoRA adapter...")
    peft_model = PeftModel.from_pretrained(base_model, args.adapter, is_trainable=False)
    merged_model = peft_model.merge_and_unload(safe_merge=True)
    merged_model.config.use_cache = True

    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, use_fast=True)
    tokenizer.chat_template = DEEPSEEK_ASSISTANT_TEMPLATE
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Saving merged model to {args.output_dir}...")
    merged_model.save_pretrained(
        args.output_dir,
        safe_serialization=True,
        max_shard_size=args.max_shard_size,
    )
    tokenizer.save_pretrained(args.output_dir)
    metadata = {
        "base_model": str(args.model.resolve()),
        "adapter": str(args.adapter.resolve()),
        "dtype": "bfloat16",
        "merged": True,
    }
    (args.output_dir / "stockguard_merge.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total_bytes = sum(path.stat().st_size for path in args.output_dir.rglob("*") if path.is_file())
    print(f"Merged model saved successfully ({total_bytes / 1024**3:.2f} GiB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
