#!/usr/bin/env python3
"""Fine-tune DeepSeek-R1-Distill-Qwen-7B with 4-bit QLoRA on Windows."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

if os.name != "nt":
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from accelerate import PartialState
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
from trl import SFTConfig, SFTTrainer


ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "DeepSeek-R1-Distill-Qwen-7B"
DEFAULT_DATA = ROOT / "datasets" / "processed" / "disc_stockguard"
DEFAULT_OUTPUT = ROOT / "outputs" / "stockguard-qlora"
DEEPSEEK_ASSISTANT_TEMPLATE = """{% if not add_generation_prompt is defined %}{% set add_generation_prompt = false %}{% endif %}{{ bos_token }}{% for message in messages %}{% if message['role'] == 'user' %}{{ '<｜User｜>' + message['content'] }}{% elif message['role'] == 'assistant' %}{{ '<｜Assistant｜>' }}{% generation %}{{ message['content'] + '<｜end▁of▁sentence｜>' }}{% endgeneration %}{% endif %}{% endfor %}{% if add_generation_prompt %}{{ '<｜Assistant｜><think>\n' }}{% endif %}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--train-file", type=Path, default=DEFAULT_DATA / "train.jsonl")
    parser.add_argument("--validation-file", type=Path, default=DEFAULT_DATA / "validation.jsonl")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--warmup-steps", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=16)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume-from-checkpoint", default=None)
    parser.add_argument("--max-train-samples", type=int, default=None)
    parser.add_argument("--max-validation-samples", type=int, default=None)
    parser.add_argument("--smoke-test", action="store_true")
    return parser.parse_args()


def require_local_model(model_path: str) -> str:
    path = Path(model_path).expanduser()
    if path.exists():
        required = ["config.json", "tokenizer_config.json"]
        missing = [name for name in required if not (path / name).exists()]
        index_path = path / "model.safetensors.index.json"
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            shard_names = sorted(set(index.get("weight_map", {}).values()))
        else:
            shard_names = [file.name for file in path.glob("*.safetensors")]
        missing_shards = [name for name in shard_names if not (path / name).exists()]
        empty_shards = [name for name in shard_names if (path / name).exists() and (path / name).stat().st_size == 0]
        if missing or not shard_names or missing_shards or empty_shards:
            details = missing + (["model weight shards"] if not shard_names else [])
            details += [f"missing {name}" for name in missing_shards]
            details += [f"empty {name}" for name in empty_shards]
            raise FileNotFoundError(f"Model directory is incomplete; missing: {details}")
        return str(path.resolve())
    if model_path == str(DEFAULT_MODEL):
        raise FileNotFoundError(
            f"Model not found at {path}. Download it with:\n"
            "hf download deepseek-ai/DeepSeek-R1-Distill-Qwen-7B "
            "--local-dir models\\DeepSeek-R1-Distill-Qwen-7B"
        )
    return model_path


def main() -> int:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. QLoRA training requires the RTX 4090 CUDA device.")
    if not args.train_file.exists() or not args.validation_file.exists():
        raise FileNotFoundError("Prepared data is missing. Run the dataset preparation script first.")

    if args.smoke_test:
        args.max_steps = 2
        args.max_train_samples = min(args.max_train_samples or 20, 20)
        args.max_validation_samples = min(args.max_validation_samples or 8, 8)
        args.gradient_accumulation = min(args.gradient_accumulation, 2)
        args.output_dir = args.output_dir.parent / "smoke-test"

    model_source = require_local_model(args.model)
    set_seed(args.seed)
    PartialState()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data_files = {"train": str(args.train_file), "validation": str(args.validation_file)}
    dataset = load_dataset("json", data_files=data_files)
    if args.max_train_samples:
        count = min(args.max_train_samples, len(dataset["train"]))
        dataset["train"] = dataset["train"].select(range(count))
    if args.max_validation_samples:
        count = min(args.max_validation_samples, len(dataset["validation"]))
        dataset["validation"] = dataset["validation"].select(range(count))

    tokenizer = AutoTokenizer.from_pretrained(model_source, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    tokenizer.chat_template = DEEPSEEK_ASSISTANT_TEMPLATE

    compute_dtype = torch.bfloat16
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_source,
        quantization_config=quantization_config,
        dtype=compute_dtype,
        device_map={"": 0},
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )

    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules="all-linear",
    )
    model = get_peft_model(model, lora_config)

    eval_steps = 1 if args.smoke_test else 20
    save_steps = 1 if args.smoke_test else 20
    training_config = SFTConfig(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_steps=args.warmup_steps,
        weight_decay=0.01,
        max_grad_norm=1.0,
        bf16=True,
        tf32=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        use_cache=False,
        max_length=args.max_length,
        truncation_mode="keep_end",
        assistant_only_loss=True,
        loss_type="nll",
        packing=False,
        eval_strategy="steps",
        eval_steps=eval_steps,
        save_strategy="steps",
        save_steps=save_steps,
        save_total_limit=2,
        logging_steps=1,
        logging_first_step=True,
        report_to="none",
        dataloader_num_workers=0,
        dataloader_pin_memory=True,
        dataset_num_proc=None,
        seed=args.seed,
        data_seed=args.seed,
    )
    trainer = SFTTrainer(
        model=model,
        args=training_config,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
    )

    trainable, total = trainer.model.get_nb_trainable_parameters()
    print(
        json.dumps(
            {
                "model": model_source,
                "gpu": torch.cuda.get_device_name(0),
                "train_samples": len(dataset["train"]),
                "validation_samples": len(dataset["validation"]),
                "trainable_parameters": trainable,
                "total_parameters": total,
                "trainable_percent": round(trainable / total * 100, 4),
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(str(args.output_dir / "adapter"))
    tokenizer.save_pretrained(str(args.output_dir / "adapter"))
    metrics = dict(result.metrics)
    metrics["train_samples"] = len(dataset["train"])
    trainer.log_metrics("train", metrics)
    trainer.save_metrics("train", metrics)
    print(f"LoRA adapter saved to: {args.output_dir / 'adapter'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
