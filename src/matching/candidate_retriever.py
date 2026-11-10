"""Apply explicit requirements before any fuzzy matching."""
import re

from .taxonomy_service import STAGE_ORDER, hq_tokens, key, stage

INDUSTRY_TERMS = re.compile(r"产业资本|产业投资方|产业方")
ROUND_PART = re.compile(r"(?:Pre-)?[A-D](?:\+{1,6}|\d{1,2})?轮|[A-D]\d{1,2}(?=及|和)|"
                        r"种子轮|天使\+*轮|E轮及以后|IPO|上市", re.I)


def normalized_rounds(raw):
    if not raw:
        return []
    if (s := stage(raw)) in STAGE_ORDER:
        return [s]
    result = []
    for text in ROUND_PART.findall(raw):
        label = "Angel+" if re.fullmatch(r"天使\+{2,}轮", text) else stage(text)
        if label in STAGE_ORDER:
            result.append(label)
    return result


def stage_conflict(company, events, ceiling):
    """Any visible later round excludes. Ambiguous newer records exclude too."""
    bound = STAGE_ORDER.index(ceiling)
    known = [e["event_date"]["value"] for e in events
             if e["event_date"] and normalized_rounds(e["round_name"])]
    for e in events:
        label = e["round_name"]
        rounds = normalized_rounds(label)
        if any(STAGE_ORDER.index(s) > bound for s in rounds):
            return True
        if not rounds:
            if label in {"更早轮次", "首轮"} and known:
                continue
            value = e["event_date"]["value"] if e["event_date"] else None
            latest = max(known, default="")
            # A month/year overlapping a known later-precision date is ambiguous.
            clearly_earlier = bool(value and latest and value < latest and not latest.startswith(value))
            if not clearly_earlier:
                return True
    return False


def industrial_evidence(events):
    return next((e for e in events if INDUSTRY_TERMS.search(e["investor_text"] or "")), None)


def meets(company, events, preferences):
    f = preferences.must_have
    sectors = set(preferences.selected_sectors)
    available = set(company["sub_tracks"])
    if sectors and (not sectors <= available if f.sector_match == "all" else not sectors & available):
        return False
    current = stage(company["funding_stage"])
    if f.funding_stages and current not in f.funding_stages:
        return False
    if f.max_funding_stage and (current not in STAGE_ORDER or
                               STAGE_ORDER.index(current) > STAGE_ORDER.index(f.max_funding_stage) or
                               stage_conflict(company, events, f.max_funding_stage)):
        return False
    if f.funding_stages and current in STAGE_ORDER and stage_conflict(company, events, current):
        return False
    if f.geography and not set(f.geography).intersection(hq_tokens(company["headquarters"])):
        return False
    if not set(f.required_applications) <= set(company["application_scenarios"]):
        return False
    if not set(f.required_technologies) <= set(company["technology_routes"]):
        return False
    if not {key(i) for i in f.required_investors} <= {key(i) for i in company["historical_investors"]}:
        return False
    return not f.require_industrial_investors or industrial_evidence(events) is not None


def retrieve(repository, preferences, scope=None):
    allowed = None if scope is None else set(scope)
    return [c for c in repository.companies() if (allowed is None or c["id"] in allowed)
            and meets(c, repository.funding(c["id"]), preferences)]

