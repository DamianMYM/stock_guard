#!/usr/bin/env python3
"""Convert DISC-FinLLM samples into deterministic prompt-completion splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "datasets" / "raw" / "DISC-FinLLM-data"
DEFAULT_OUTPUT = ROOT / "datasets" / "processed" / "disc_stockguard"
TASK_FILES = {
    "computing": "computing_part.json",
    "consulting": "consulting_part.json",
    "retrieval": "retrieval_part.json",
    "task": "task_part.json",
}
DOMAIN_PREFIX = (
    "请以严谨的中文金融研究助手身份回答。区分已知事实、合理推断和未知信息；"
    "数据不足时明确说明，不编造实时数据，不承诺收益。\n\n"
)
TOOL_MARKER = re.compile(r"\[[^\[\]\n]*?→[^\[\]\n]*?\]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--validation-ratio", type=float, default=0.1)
    parser.add_argument("--limit-per-task", type=int, default=None)
    return parser.parse_args()


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    text = TOOL_MARKER.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def history_messages(history: Any) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in history or []:
        if not isinstance(turn, list) or len(turn) != 2:
            continue
        user, assistant = map(clean_text, turn)
        if user and assistant:
            messages.extend(
                [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]
            )
    return messages


def convert_row(row: dict[str, Any], task: str, source_file: str) -> dict[str, Any] | None:
    instruction = clean_text(row.get("instruction"))
    extra_input = clean_text(row.get("input"))
    answer = clean_text(row.get("output"))
    if not instruction or not answer:
        return None

    current_question = instruction
    if extra_input:
        current_question = f"{instruction}\n\n补充材料:\n{extra_input}"
    prompt = history_messages(row.get("history"))
    prompt.append({"role": "user", "content": DOMAIN_PREFIX + current_question})
    completion = [{"role": "assistant", "content": answer}]

    fingerprint_source = json.dumps([prompt, completion], ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    return {
        "messages": prompt + completion,
        "task": task,
        "source": f"FudanDISC/DISC-FinLLM:{source_file}",
        "id": fingerprint[:16],
    }


def split_task(rows: list[dict[str, Any]], train_ratio: float, validation_ratio: float) -> dict[str, list]:
    train_end = int(len(rows) * train_ratio)
    validation_end = train_end + int(len(rows) * validation_ratio)
    return {
        "train": rows[:train_end],
        "validation": rows[train_end:validation_end],
        "test": rows[validation_end:],
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    if args.train_ratio <= 0 or args.validation_ratio < 0:
        raise ValueError("Split ratios must be non-negative and train-ratio must be positive.")
    if args.train_ratio + args.validation_ratio >= 1:
        raise ValueError("train-ratio + validation-ratio must be less than 1.")

    rng = random.Random(args.seed)
    seen: set[str] = set()
    splits = {"train": [], "validation": [], "test": []}
    dropped = Counter()

    for task, filename in TASK_FILES.items():
        path = args.input_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing source file: {path}")
        raw_rows = json.loads(path.read_text(encoding="utf-8"))
        if args.limit_per_task is not None:
            raw_rows = raw_rows[: args.limit_per_task]

        converted = []
        for row in raw_rows:
            item = convert_row(row, task, filename)
            if item is None:
                dropped["empty"] += 1
                continue
            if item["id"] in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(item["id"])
            converted.append(item)

        rng.shuffle(converted)
        task_splits = split_task(converted, args.train_ratio, args.validation_ratio)
        for split_name, split_rows in task_splits.items():
            splits[split_name].extend(split_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seed": args.seed,
        "source": "FudanDISC/DISC-FinLLM official samples",
        "format": "conversational messages JSONL with assistant-only loss",
        "counts": {},
        "dropped": dict(dropped),
    }
    for split_name, rows in splits.items():
        rng.shuffle(rows)
        write_jsonl(args.output_dir / f"{split_name}.jsonl", rows)
        manifest["counts"][split_name] = {
            "total": len(rows),
            "tasks": dict(Counter(row["task"] for row in rows)),
        }

    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
