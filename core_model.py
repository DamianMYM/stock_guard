#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


THEME_RULES = [
    {
        "id": "tungsten",
        "label": "钨产业链",
        "role": "上游资源 / 中游硬质合金材料",
        "keywords": ["钨", "中钨", "硬质合金", "刀具", "矿山"],
        "chain_view": "如果政策或出口端出现扰动，通常先影响上游资源品价格，再向冶炼、硬质合金和刀具环节传导。",
        "watch_items": ["看价格传导是否顺畅", "看出口限制是否改变供需结构", "看订单和毛利率能否同步兑现"],
    },
    {
        "id": "rare_earth",
        "label": "稀土产业链",
        "role": "资源 / 冶炼分离",
        "keywords": ["稀土", "中稀", "磁材", "氧化镨钕", "分离"],
        "chain_view": "稀土链更容易被政策、配额和价格波动驱动，上游资源与冶炼端弹性通常先体现，下游磁材要看成本转嫁。",
        "watch_items": ["看价格而不是只看题材热度", "看库存周期是否转正", "看现金流能否跟上利润改善"],
    },
    {
        "id": "military",
        "label": "军工链",
        "role": "军工制造 / 配套电子",
        "keywords": ["军工", "航天", "航空", "导弹", "电子", "长城军工"],
        "chain_view": "军工链的核心不是短期估值弹性，而是订单、交付和回款节奏。题材可以抬估值，但兑现决定估值能不能站住。",
        "watch_items": ["看订单签订和交付节奏", "看应收和回款压力", "看利润率是否改善而不是只看收入"],
    },
    {
        "id": "semiconductor",
        "label": "半导体链",
        "role": "芯片设计 / 特种器件",
        "keywords": ["芯片", "半导体", "国微", "器件", "封测", "FPGA"],
        "chain_view": "半导体链通常要把景气、国产替代和政策支持拆开看。估值提升可以很快，但真正决定持续性的仍是产品结构和盈利兑现。",
        "watch_items": ["看产品结构升级", "看毛利率与现金流是否同步", "看政策支持能否落到订单和份额"],
    },
    {
        "id": "equipment",
        "label": "高端制造链",
        "role": "设备 / 关键零部件",
        "keywords": ["精工", "轴承", "机床", "装备", "工具"],
        "chain_view": "高端制造链更像制造业景气度和国产替代的组合，要区分一次性催化和持续性的产能利用率改善。",
        "watch_items": ["看资本开支周期", "看产能利用率", "看新增订单能否转成稳定利润"],
    },
]


TAG_EFFECTS = {
    "订单": "订单类公告偏向需求验证，关键是后续交付节奏和毛利率，而不是只看签约金额。",
    "扩产": "扩产偏中期利好，但必须确认资本开支、产能利用率和新增需求是否匹配。",
    "回购分红": "回购和分红更像股东回报信号，能改善情绪，但不能替代基本面兑现。",
    "政策支持": "政策支持会抬高关注度，后续要确认是否真正落到订单、份额或盈利质量。",
    "出口管制": "出口约束会重排产业链利润分配，上游资源和替代能力更强的环节往往先受益，下游出口客户可能承压。",
    "涨价": "涨价若能顺利传导，最先利好议价能力更强的环节；若传导不动，反而会压缩下游利润。",
    "减持质押": "减持和质押更多是风险折价信号，往往压制估值，而不是创造新增逻辑。",
    "诉讼处罚": "诉讼和监管事项优先级很高，通常会先影响风险偏好，再影响估值上限。",
    "亏损减值": "亏损和减值说明盈利质量承压，估值锚可能继续下修。",
    "停产事故": "停产和事故对产能与交付的打击更直接，要先看恢复节奏和客户影响。",
}


def _text_blob(row: dict[str, Any], intel: dict[str, Any] | None) -> str:
    parts = [
        str(row.get("symbol") or ""),
        str(row.get("name") or ""),
        str(row.get("notes") or ""),
        str(row.get("research_source") or ""),
    ]
    if intel:
        parts.extend(str(item.get("title") or "") for item in intel.get("items", [])[:6])
    return " ".join(parts)


def infer_theme(row: dict[str, Any], intel: dict[str, Any] | None = None) -> dict[str, Any] | None:
    blob = _text_blob(row, intel)
    best_rule = None
    best_score = 0
    for rule in THEME_RULES:
        score = sum(1 for keyword in rule["keywords"] if keyword in blob)
        if score > best_score:
            best_rule = rule
            best_score = score
    return best_rule


def _valuation_view(row: dict[str, Any]) -> str:
    margin = row.get("margin_of_safety")
    quant_score = row.get("quant_score")
    if margin is not None and margin >= 0.2:
        return "估值侧接近可讨论区间，可以把重点放到兑现质量和仓位节奏。"
    if quant_score is not None and quant_score >= 75:
        return "量化优先级不低，但估值仍需和事件兑现一起交叉验证。"
    if margin is not None and margin < 0:
        return "估值还没有给出安全边际，当前更像观察和等价格，而不是急着下结论。"
    return "估值信息还不够强，需要和行业链、财务质量一起看。"


def _event_view(intel: dict[str, Any] | None) -> str:
    if not intel:
        return "近期没有抓到足够的事件线索，事件侧暂时不构成单独结论。"
    top_tags = intel.get("top_tags") or []
    for tag in top_tags:
        if tag in TAG_EFFECTS:
            return TAG_EFFECTS[tag]
    return intel.get("overall") or "事件侧暂时偏中性，需要和财务与估值放在一起看。"


def build_core_model_brief(row: dict[str, Any], intel: dict[str, Any] | None = None) -> dict[str, Any]:
    theme = infer_theme(row, intel)
    action = row.get("action") or "继续观察"
    quant_label = row.get("quant_label") or action

    if theme:
        theme_label = theme["label"]
        role = theme["role"]
        chain_view = theme["chain_view"]
        watch_items = list(theme["watch_items"])
    else:
        theme_label = "通用研究框架"
        role = "待识别产业位置"
        chain_view = "先确认公司处在上游资源、中游制造还是下游应用，再决定应该盯价格、订单还是利润率。"
        watch_items = ["看行业景气方向", "看利润兑现质量", "看估值是否给出安全边际"]

    if intel and intel.get("top_tags"):
        for tag in intel["top_tags"]:
            if tag in TAG_EFFECTS and TAG_EFFECTS[tag] not in watch_items:
                watch_items.append(TAG_EFFECTS[tag])
                break

    risk_items: list[str] = []
    if row.get("pe_ttm") and row["pe_ttm"] >= 80:
        risk_items.append("高 PE 说明市场已经提前透支不少预期。")
    if row.get("pb") and row["pb"] >= 5:
        risk_items.append("高 PB 阶段更依赖成长兑现，回撤也会更敏感。")
    if row.get("eps_ttm") is not None and row["eps_ttm"] <= 0:
        risk_items.append("EPS 仍弱时，估值锚容易失真，要谨慎把题材当成基本面。")
    if intel and (intel.get("sentiment_counts") or {}).get("negative", 0) > 0:
        risk_items.append("公告里已经有风险线索，优先级要高于题材叙事。")
    if not risk_items:
        risk_items.append("当前最大的风险不是没有逻辑，而是逻辑兑现速度慢于市场预期。")

    return {
        "headline": f"{theme_label} / {quant_label}",
        "theme": theme_label,
        "industry_role": role,
        "decision_anchor": f"{action}。先看产业链位置，再看事件是否真的改善盈利兑现。",
        "valuation_view": _valuation_view(row),
        "event_view": _event_view(intel),
        "industry_chain_view": chain_view,
        "watch_items": watch_items[:3],
        "risk_items": risk_items[:3],
    }
