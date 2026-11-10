"""Compose responses exclusively from exported fields and rule outcomes."""
import math
import re
import unicodedata

from .company_repository import summary
from .models import Evidence, Recommendation, ScoreBreakdown


def excerpt(value, needle, limit=480):
    if len(value) <= limit:
        return value
    if needle and (match := re.search(re.escape(needle), value, re.I)):
        start = max(0, match.start() - 35)
        return value[start:start + max(limit, len(needle) + 35)]
    if needle:
        # Keep original glyphs in the quote even when matching normalized text.
        chars = [unicodedata.normalize("NFKC", char).casefold() for char in value]
        target = unicodedata.normalize("NFKC", needle).casefold()
        position = "".join(chars).find(target)
        if position >= 0:
            offset = 0
            for index, char in enumerate(chars):
                offset += len(char)
                if offset > position:
                    start = max(0, index - 35)
                    return value[start:start + max(limit, len(needle) + 35)]
    return value[:limit]


def recommendation(item, repository):
    company = item.company
    reasons = []
    seen = set()
    for label, field, needle, event, kind in item.signals:
        signal_key = (label, field, needle, event["id"] if event else None, kind)
        if signal_key in seen:
            continue
        seen.add(signal_key)
        origin = event["provenance"] if event else company["provenance"]
        cell = origin["cells"].get(field)
        if cell and cell["raw_value"] is not None:
            raw = str(cell["raw_value"])
            segment = event["raw_value"] if event else None
            quote = excerpt(segment if segment and segment in raw else raw, needle)
            reasons.append(Evidence(criterion=label, field=field, evidence=quote, workbook=origin["workbook"],
                                    sheet=origin["sheet"], cell=cell["coordinate"], kind=kind))
    return Recommendation(**summary(company, repository).model_dump(),
                          fit_score=int(round(item.score)), matched_sectors=item.sectors,
                          score_breakdown=ScoreBreakdown(earned=math.fsum(f.earned for f in item.factors),
                                                         possible=math.fsum(f.weight for f in item.factors),
                                                         factors=item.factors),
                          matched_technologies=item.technologies, matching_reasons=reasons,
                          unmet_preferences=item.unmet, missing_information=item.missing,
                          source_urls=repository.urls(company["id"]))


def message(action, rows, considered, clarification):
    if clarification:
        return clarification
    if not rows:
        return "当前 Excel 数据没有足够证据匹配这些条件。你可以放宽条件或换一个赛道。"
    if action == "compare":
        lines = [f"{r.company_name}：{r.funding_stage or '阶段未提供'}；"
                 f"命中赛道：{'、'.join(r.matched_sectors) or '无'}；匹配分 {r.fit_score}"
                 for r in rows]
        return "以下按上次结果对比（均为 Excel 口径）：\n" + "\n".join(lines)
    if action == "explain":
        row = rows[0]
        labels = "；".join(r.criterion for r in row.matching_reasons)
        return f"{row.company_name}：{labels or '当前没有可引用的匹配理由'}。下方可查看原表证据。"
    return f"硬筛选后检查了 {considered} 家公司，返回 {len(rows)} 家；每张卡片列出了对应的 Excel 证据。"

