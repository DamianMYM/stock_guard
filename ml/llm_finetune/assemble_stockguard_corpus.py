#!/usr/bin/env python3
"""Assemble a Gushou-focused mixed corpus from local financial datasets."""

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
DISC_DIR = ROOT / "datasets" / "processed" / "disc_stockguard"
FINCHINA_DIR = ROOT / "datasets" / "raw" / "FinChina-SA-main" / "dataset" / "FinChina SA"
CFEED_DIR = ROOT / "datasets" / "raw" / "CFEED-data" / "dataset"
LOCAL_DIR = ROOT / "datasets" / "local"
DEFAULT_OUTPUT = ROOT / "datasets" / "processed" / "stockguard_mix"
SYSTEM_PREFIX = "请以严谨的中文金融研究助手身份回答。区分已知事实、合理推断和未知信息；数据不足时明确说明，不编造实时数据，不承诺收益。"

CFEED_EVENT_MAP = {
    "PLEDGE_Data.json": "股权质押",
    "FREEZE_Data.json": "股份冻结",
    "OW&UW_Data.json": "增减持/被动减持预警",
}


def clean_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def stable_id(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_disc_rows(limit_per_split: int | None) -> dict[str, list[dict[str, Any]]]:
    splits: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "validation", "test"):
        path = DISC_DIR / f"{split}.jsonl"
        rows = read_jsonl(path)
        if limit_per_split is not None:
            rows = rows[:limit_per_split]
        splits[split] = rows
    return splits


def sentiment_text(level: str) -> str:
    mapping = {
        "-1": "偏利空",
        "0": "中性",
        "1": "偏利好",
    }
    return mapping.get(str(level), "中性")


def convert_finchina_row(row: dict[str, Any]) -> dict[str, Any] | None:
    title = clean_text(row.get("title"))
    text = clean_text(row.get("text"))
    institutions = row.get("institution") or []
    if not title or not text or not institutions:
        return None

    primary = institutions[0]
    subject = clean_text(primary.get("ins_name")) or "文中主体"
    labels = sorted({clean_text(item.get("label_type")) for item in institutions if clean_text(item.get("label_type"))})
    sentiment = sentiment_text(str(primary.get("sentiment_level")))
    facts = [
        f"主体: {subject}",
        f"事件标签: {' / '.join(labels) if labels else '未标注'}",
        f"情绪倾向: {sentiment}",
    ]

    prompt = (
        f"{SYSTEM_PREFIX}\n\n"
        "请阅读下面的资讯，并输出鼓手式研究摘要：\n"
        "1. 先提炼已知事实；\n"
        "2. 再判断事件偏利好、利空还是中性；\n"
        "3. 最后说明还缺什么信息，避免把新闻情绪直接当成投资结论。\n\n"
        f"标题: {title}\n\n正文:\n{text[:1400]}"
    )
    answer = (
        "已知事实:\n- "
        + "\n- ".join(facts)
        + "\n判断:\n- "
        + sentiment
        + "\n理由:\n- 这条资讯明确描述了主体与事件类型，情绪标签可作为初步线索，但不能替代财务与估值验证。\n"
        "待补充信息:\n- 需要结合公司最新利润、现金流、估值位置、行业景气度和后续公告再判断影响强弱。"
    )
    messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}]
    return {
        "messages": messages,
        "task": "event_sentiment",
        "source": "FinChina-SA",
        "id": stable_id(messages),
    }


def load_finchina_rows(train_limit: int, test_limit: int) -> dict[str, list[dict[str, Any]]]:
    result = {"train": [], "validation": [], "test": []}
    train_rows = json.loads((FINCHINA_DIR / "train.json").read_text(encoding="utf-8"))
    test_rows = json.loads((FINCHINA_DIR / "test.json").read_text(encoding="utf-8"))

    converted_train = [item for item in (convert_finchina_row(row) for row in train_rows[:train_limit]) if item]
    converted_test = [item for item in (convert_finchina_row(row) for row in test_rows[:test_limit]) if item]

    validation_size = max(1, int(len(converted_train) * 0.1))
    result["validation"] = converted_train[:validation_size]
    result["train"] = converted_train[validation_size:]
    result["test"] = converted_test
    return result


def summarize_event_fields(event: dict[str, list[str]]) -> list[str]:
    pieces: list[str] = []
    for key, label in (("NAME", "主体"), ("ORG", "机构"), ("BEG", "开始时间"), ("END", "结束时间"), ("NUM", "关键数值")):
        values = [clean_text(item) for item in event.get(key, []) if clean_text(item)]
        if values:
            pieces.append(f"{label}: {' / '.join(values[:3])}")
    return pieces


def convert_cfeed_row(row: dict[str, Any], event_name: str) -> dict[str, Any] | None:
    title = clean_text(row.get("Title"))
    doc = clean_text(row.get("Doc"))
    events = row.get("Event") or []
    if not title or not doc or not events:
        return None

    first_event = events[0]
    facts = summarize_event_fields(first_event)
    prompt = (
        f"{SYSTEM_PREFIX}\n\n"
        "请根据公告材料提取结构化事件，并给出一段面向投资研究的简要影响说明。"
        "不要把不确定影响说成既定事实。\n\n"
        f"公告标题: {title}\n"
        f"事件类型候选: {event_name}\n\n公告正文:\n{doc[:1500]}"
    )
    answer = (
        f"事件类型: {event_name}\n"
        + ("\n".join(facts) if facts else "主体: 未明确\n")
        + "\n研究提示:\n- 这类事件先看融资约束、控制权风险、质押比例或冻结比例，再看是否影响主营经营。\n"
        "- 若没有同步出现盈利恶化、现金流收缩或大比例减持，通常不能仅凭标题直接下投资结论。"
    )
    messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}]
    return {
        "messages": messages,
        "task": "event_extraction",
        "source": f"CFEED:{event_name}",
        "id": stable_id(messages),
    }


def load_cfeed_rows(limit_per_file: int, seed: int) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    result = {"train": [], "validation": [], "test": []}
    for filename, event_name in CFEED_EVENT_MAP.items():
        path = CFEED_DIR / filename
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= limit_per_file:
                    break
                line = line.strip()
                if not line:
                    continue
                item = convert_cfeed_row(json.loads(line), event_name)
                if item:
                    rows.append(item)
        rng.shuffle(rows)
        validation_size = max(1, int(len(rows) * 0.1))
        test_size = max(1, int(len(rows) * 0.1))
        result["validation"].extend(rows[:validation_size])
        result["test"].extend(rows[validation_size : validation_size + test_size])
        result["train"].extend(rows[validation_size + test_size :])
    return result


def load_local_rows() -> dict[str, list[dict[str, Any]]]:
    result = {"train": [], "validation": [], "test": []}
    path = LOCAL_DIR / "stockguard_manual.jsonl"
    rows = read_jsonl(path)
    validation_size = max(1, int(len(rows) * 0.15))
    test_size = max(1, int(len(rows) * 0.15))
    result["validation"] = rows[:validation_size]
    result["test"] = rows[validation_size : validation_size + test_size]
    result["train"] = rows[validation_size + test_size :]
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--disc-limit-per-split", type=int, default=600)
    parser.add_argument("--finchina-train-limit", type=int, default=900)
    parser.add_argument("--finchina-test-limit", type=int, default=200)
    parser.add_argument("--cfeed-limit-per-file", type=int, default=260)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    splits = {"train": [], "validation": [], "test": []}
    seen: set[str] = set()
    source_counter: dict[str, Counter] = {split: Counter() for split in splits}

    for group in (
        load_disc_rows(args.disc_limit_per_split),
        load_finchina_rows(args.finchina_train_limit, args.finchina_test_limit),
        load_cfeed_rows(args.cfeed_limit_per_file, args.seed),
        load_local_rows(),
    ):
        for split_name, rows in group.items():
            for row in rows:
                row_id = row["id"]
                if row_id in seen:
                    continue
                seen.add(row_id)
                splits[split_name].append(row)
                source_counter[split_name][row["source"]] += 1

    rng = random.Random(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "seed": args.seed,
        "format": "messages JSONL with assistant-only loss",
        "counts": {},
    }
    for split_name, rows in splits.items():
        rng.shuffle(rows)
        write_jsonl(args.output_dir / f"{split_name}.jsonl", rows)
        manifest["counts"][split_name] = {
            "total": len(rows),
            "sources": dict(source_counter[split_name]),
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
