"""Weighted, deterministic fit ranking over already filtered candidates."""
from dataclasses import dataclass, field
import json
import math

from .candidate_retriever import industrial_evidence, normalized_rounds, stage_conflict
from .models import ScoreFactor
from .taxonomy_service import STAGE_ORDER, hq_tokens, key, stage

DEFAULT_WEIGHTS = {"sector": 5, "application": 3, "technology": 3, "stage": 5, "geography": 2,
                   "investor": 2, "industrial": 2, "business_text": 2}
DIMENSIONS = {"sector": "赛道覆盖", "application": "应用场景", "technology": "技术路线",
              "stage": "融资偏好", "geography": "总部地区", "investor": "指定投资方",
              "industrial": "产业投资方", "business_text": "业务文本"}


def load_weights(raw):
    if not raw:
        return DEFAULT_WEIGHTS.copy()
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) - set(DEFAULT_WEIGHTS):
        raise ValueError("MATCH_RANK_WEIGHTS 仅接受已定义权重键")
    if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 < v <= 100 for v in data.values()):
        raise ValueError("MATCH_RANK_WEIGHTS 的值须大于 0 且不超过 100")
    return {**DEFAULT_WEIGHTS, **data}


@dataclass
class Ranked:
    company: dict
    score: float = 0.0
    sectors: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    signals: list[tuple] = field(default_factory=list)
    factors: list[ScoreFactor] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def cite(self, label, column, needle=None, event=None, kind="preference"):
        self.signals.append((label, column, needle, event, kind))


def _strongest_round(events):
    comparable = [(STAGE_ORDER.index(stage), event)
                  for event in events for stage in normalized_rounds(event["round_name"])]
    return max(comparable, key=lambda pair: (
        pair[0], (pair[1]["event_date"] or {}).get("value", "")
    ))[1] if comparable else None


def _score(company, p, events, matcher, weights):
    c = company
    r = Ranked(c)
    f = p.must_have

    def factor(dimension, coverage, missing=False):
        state = ("missing_evidence" if missing else "matched" if coverage == 1 else
                 "partial" if coverage else "not_matched")
        weight = weights[dimension]
        r.factors.append(ScoreFactor(key=dimension, label=DIMENSIONS[dimension], earned=coverage * weight,
                                     weight=weight, status=state))

    def match_group(dimension, requested, column, caption, required=()):
        given = c[column]
        hits = [value for value in requested if value in given]
        if requested:
            factor(dimension, len(hits) / len(requested), missing=not given)
            if not given:
                r.missing.append(caption)
            elif absent := [value for value in requested if value not in given]:
                r.unmet.append(f"{caption}未命中 {'、'.join(absent)}")
        for hit in dict.fromkeys([*required, *hits]):
            kind = "hard_filter" if hit in required else "preference"
            r.cite(f"{caption}命中 · {hit}", column, hit, kind=kind)
        return list(dict.fromkeys([*hits, *required]))

    sectors = list(dict.fromkeys(p.selected_sectors + p.target_sectors))
    selected_hits = [value for value in p.selected_sectors if value in c["sub_tracks"]]
    r.sectors = match_group("sector", sectors, "sub_tracks", "赛道", selected_hits)
    r.technologies = match_group("technology", p.target_technologies, "technology_routes", "技术路线",
                                 f.required_technologies)
    match_group("application", p.target_applications, "application_scenarios", "应用场景", f.required_applications)

    current = stage(c["funding_stage"])
    if p.funding_stages:
        ambiguous = (current is None or current == "Undisclosed" or
                     (current in STAGE_ORDER and stage_conflict(c, events, current)))
        hit = not ambiguous and current in p.funding_stages
        factor("stage", float(hit), missing=ambiguous)
        if hit:
            r.cite(f"融资偏好命中 · {c['funding_stage']}", "funding_stage")
        elif ambiguous or current == "Strategic":
            r.missing.append("可比较的融资阶段")
        else:
            r.unmet.append("融资阶段不在偏好列表")
    if f.funding_stages or f.max_funding_stage:
        conditions = []
        if f.funding_stages:
            conditions.append(f"范围 {' / '.join(f.funding_stages)}")
        if f.max_funding_stage:
            conditions.append(f"上限 {f.max_funding_stage}")
        r.cite(f"融资条件通过 · {'，'.join(conditions)}", "funding_stage", kind="hard_filter")
        if event := _strongest_round(events):
            r.cite(f"历史交叉核对 · 表内最高可比较轮次 {event['round_name']}",
                   "funding_history", event["round_name"], event, kind="corroboration")

    places = hq_tokens(c["headquarters"])
    if p.geography:
        hits = [value for value in p.geography if value in places]
        factor("geography", float(bool(hits)), missing=not places)
        for hit in hits:
            r.cite(f"总部偏好命中 · {hit}", "headquarters", hit)
        if not places:
            r.missing.append("总部")
        elif not hits:
            r.unmet.append("总部不在偏好地区")
    if f.geography:
        hit = next(value for value in f.geography if value in places)
        r.cite(f"总部条件通过 · {hit}", "headquarters", hit, kind="hard_filter")

    investors = {key(value): value for value in c["historical_investors"]}
    if p.preferred_investors:
        hits = [investors[key(value)] for value in p.preferred_investors if key(value) in investors]
        factor("investor", len(hits) / len(p.preferred_investors), missing=not investors)
        for hit in hits:
            r.cite(f"历轮投资方命中 · {hit}", "historical_investors", hit)
        if not investors:
            r.missing.append("历史投资方")
        elif len(hits) != len(p.preferred_investors):
            r.unmet.append("部分或全部偏好投资方未见于表内名单")
    for value in f.required_investors:
        hit = investors[key(value)]
        r.cite(f"投资方条件通过 · {hit}", "historical_investors", hit, kind="hard_filter")

    if p.prefer_industrial_investors or f.require_industrial_investors:
        industrial = industrial_evidence(events)
        if p.prefer_industrial_investors:
            factor("industrial", float(industrial is not None), missing=industrial is None)
        if industrial:
            r.cite(f"{industrial['round_name'] or '融资记录'} · 原文明确提到产业方",
                   "funding_history", industrial["investor_text"], industrial,
                   kind="hard_filter" if f.require_industrial_investors else "preference")
        else:
            r.missing.append("明确的产业投资方证据")
    if p.prefer_technical_barriers:
        r.missing.append("可核验的技术壁垒证据")

    if p.search_terms:
        found = [matcher.match(c, [term]) for term in p.search_terms]
        has_text = any(c[field] for field in ("business_description", "products",
                                             "technology_routes", "application_scenarios"))
        factor("business_text", sum(hit.score for hit in found if hit) / len(found), missing=not has_text)
        for term, hit in zip(p.search_terms, found):
            if hit:
                label = "文本片段命中" if hit.partial else "原文词语命中"
                r.cite(f"{label} · {hit.term}", hit.field, hit.term)
            elif has_text:
                r.unmet.append(f"业务文本未命中 {term}")
        if not has_text:
            r.missing.append("可搜索的业务文本")
    for column, title in (("technology_routes", "技术路线"), ("application_scenarios", "应用场景"),
                          ("valuation", "估值"), ("revenue", "营收"), ("employee_scale", "员工规模")):
        if not c[column]:
            r.missing.append(title)
    if current is None or current in {"Undisclosed", "Strategic"}:
        r.missing.append("可比较的融资阶段")
    r.missing = list(dict.fromkeys(r.missing))
    return r


def rank(candidates, p, repository, matcher, weights, include_zero=False):
    ranked = []
    f = p.must_have
    has_filter = any((p.selected_sectors, f.funding_stages, f.max_funding_stage, f.geography,
                      f.required_technologies, f.required_applications, f.required_investors,
                      f.require_industrial_investors))
    for company in candidates:
        result = _score(company, p, repository.funding(company["id"]), matcher, weights)
        earned = math.fsum(factor.earned for factor in result.factors)
        possible = math.fsum(factor.weight for factor in result.factors)
        if possible and not earned and not include_zero and not has_filter:
            continue
        result.score = 100 * earned / possible if possible else 100.0
        ranked.append(result)
    return sorted(ranked, key=lambda result: (-result.score, -len(result.sectors),
                                             key(result.company["name"]), result.company["id"]))

