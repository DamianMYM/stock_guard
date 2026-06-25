#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from typing import Any

from stock_guard import fetch_stock_announcements


KEYWORD_RULES = [
    {
        "tag": "订单",
        "sentiment": "positive",
        "weight": 2.2,
        "patterns": ["中标", "订单", "签署", "合同", "项目"],
        "impact": "新订单通常对应未来收入兑现，适合继续跟踪交付和利润率。",
    },
    {
        "tag": "扩产",
        "sentiment": "positive",
        "weight": 1.6,
        "patterns": ["扩建", "扩产", "投产", "技改", "产线"],
        "impact": "扩产更偏中期利好，但也要同步关注资本开支和产能利用率。",
    },
    {
        "tag": "回购分红",
        "sentiment": "positive",
        "weight": 1.3,
        "patterns": ["回购", "增持", "分红", "特别分红"],
        "impact": "股东回报动作通常改善市场情绪，但不替代基本面改善。",
    },
    {
        "tag": "政策支持",
        "sentiment": "positive",
        "weight": 1.4,
        "patterns": ["补贴", "支持", "获批", "示范", "专项"],
        "impact": "政策支持会提升主题热度，仍需区分一次性刺激和长期竞争力。",
    },
    {
        "tag": "出口管制",
        "sentiment": "mixed",
        "weight": 1.1,
        "patterns": ["出口", "配额", "关税", "限制", "许可证"],
        "impact": "出口与管制类消息要结合产业链位置判断，上游资源和下游制造的受益方向可能相反。",
    },
    {
        "tag": "涨价",
        "sentiment": "positive",
        "weight": 1.2,
        "patterns": ["提价", "涨价", "调价"],
        "impact": "提价通常改善盈利弹性，但也要防止需求承接不足。",
    },
    {
        "tag": "减持质押",
        "sentiment": "negative",
        "weight": -1.8,
        "patterns": ["减持", "质押", "解押"],
        "impact": "减持和质押更偏风险提示，容易压制估值与情绪。",
    },
    {
        "tag": "诉讼处罚",
        "sentiment": "negative",
        "weight": -2.6,
        "patterns": ["诉讼", "仲裁", "处罚", "立案", "监管函", "问询函"],
        "impact": "监管与诉讼事件要优先处理，通常是比题材更高优先级的风险信号。",
    },
    {
        "tag": "亏损减值",
        "sentiment": "negative",
        "weight": -2.3,
        "patterns": ["亏损", "预亏", "减值", "商誉", "计提"],
        "impact": "亏损和减值说明盈利质量承压，估值锚可能继续下修。",
    },
    {
        "tag": "停产事故",
        "sentiment": "negative",
        "weight": -2.8,
        "patterns": ["停产", "事故", "火灾", "安全", "爆炸"],
        "impact": "停产与事故对产能和市场预期打击更直接，需要优先关注恢复节奏。",
    },
]


def _classify_title(title: str) -> dict[str, Any]:
    tags: list[str] = []
    score = 0.0
    notes: list[str] = []
    sentiments: list[str] = []

    for rule in KEYWORD_RULES:
        if any(keyword in title for keyword in rule["patterns"]):
            tags.append(rule["tag"])
            score += rule["weight"]
            notes.append(rule["impact"])
            sentiments.append(rule["sentiment"])

    if not tags:
        sentiment = "neutral"
        summary = "标题未命中重点事件词，更适合作为背景材料，不宜单独下结论。"
    elif "negative" in sentiments and "positive" in sentiments:
        sentiment = "mixed"
        summary = "同一条公告里既有机会也有风险，需要结合正文进一步核实。"
    elif "negative" in sentiments:
        sentiment = "negative"
        summary = notes[0]
    elif "mixed" in sentiments:
        sentiment = "mixed"
        summary = notes[0]
    else:
        sentiment = "positive"
        summary = notes[0]

    return {
        "tags": tags,
        "sentiment": sentiment,
        "event_score": round(score, 2),
        "summary": summary,
    }


def analyze_announcements(symbol: str, limit: int = 8, announcements: list[dict[str, str]] | None = None) -> dict[str, Any]:
    items = announcements if announcements is not None else fetch_stock_announcements(symbol, limit=limit)
    items = items[:limit]

    enriched: list[dict[str, Any]] = []
    total_score = 0.0
    tag_counter: Counter[str] = Counter()
    sentiment_counter: Counter[str] = Counter()

    for item in items:
        title = str(item.get("title") or "")
        classified = _classify_title(title)
        tags = classified["tags"]
        for tag in tags:
            tag_counter[tag] += 1
        sentiment_counter[classified["sentiment"]] += 1
        total_score += classified["event_score"]
        enriched.append(
            {
                **item,
                "tags": tags,
                "sentiment": classified["sentiment"],
                "event_score": classified["event_score"],
                "summary": classified["summary"],
            }
        )

    top_tags = [tag for tag, _ in tag_counter.most_common(3)]
    opportunities = [item["summary"] for item in enriched if item["sentiment"] == "positive"][:2]
    risks = [item["summary"] for item in enriched if item["sentiment"] == "negative"][:2]

    if total_score >= 3:
        overall = "近期事件偏正面，可作为继续研究的催化线索。"
    elif total_score <= -3:
        overall = "近期事件偏风险项，适合先做风险核验，再谈估值。"
    elif enriched:
        overall = "近期公告更偏中性，需要结合财务与估值一起看。"
    else:
        overall = "最近没有抓到可分析的公告，事件层暂时空白。"

    return {
        "symbol": symbol,
        "headline_score": round(total_score, 2),
        "overall": overall,
        "top_tags": top_tags,
        "opportunities": opportunities,
        "risks": risks,
        "sentiment_counts": dict(sentiment_counter),
        "items": enriched,
    }
