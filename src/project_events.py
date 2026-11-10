"""Conservative, evidence-bound extraction from one RSS article."""
from datetime import date
from hashlib import sha256
import re

EXTRACTOR_VERSION = 2
KINDS = ("launch", "prototype", "plan", "funding")
TIME = r"(?:20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日|近日|日前|今日|今天|近期)"
ROBOT = r"(?:人形机器人|四足机器人|双足机器人|工业机器人|服务机器人|协作机器人|通用机器人|机器人|机器狗|灵巧手|具身大脑)"
QUOTED = r"[「“《][^」”》]{1,48}[」”》]"
PRODUCT = rf"(?:{QUOTED}|[A-Za-z][A-Za-z0-9-]{{0,14}}\d[A-Za-z0-9-]{{0,10}})"
CLAUSE = re.compile(
    rf"(?:^(?:(?P<leading>{TIME})[，,]\s*)?)"
    rf"(?P<subject>{QUOTED}|[A-Za-z\u3400-\u9fff][\w· -]{{1,23}}?)"
    rf"(?:(?:于)?(?P<when>{TIME})[，,]?)?"
    rf"(?P<qualifier>计划|拟|将于{TIME}|将)?(?:已经|正式|首次|对外|已)?(?P<verb>发布|推出|展示)了?\s*"
    rf"(?:其|旗下|自研的)?(?:首款|全新|新一代|一款)?"
    rf"(?P<before>{ROBOT})?(?:原型)?\s*(?P<object>{PRODUCT})\s*(?P<after>{ROBOT})?"
)
HINT = re.compile(r"(?:^|[｜|])\s*(?P<subject>[\w· -]{2,18}?)新品发布(?:\s*$|[｜|])")


def _event_date(raw):
    if not raw:
        return None
    match = re.fullmatch(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", raw)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            return None
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", raw):
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None
    return None


def _record(url, kind, subject, product, when, evidence, field, reason=None):
    identity = "\0".join((url, kind, subject or "", product or ""))
    day = _event_date(when)
    return {"id": sha256(identity.encode()).hexdigest()[:24], "kind": kind, "subject": subject,
            "product": product, "event_date": day, "time_text": when,
            "status": "review" if reason or not day else "supported",
            "review_reason": reason or (None if day else "date_unclear"),
            "evidence": evidence, "evidence_field": field}


def extract_events(url, title, description="", funding=None):
    events = {}
    for sentence in re.split(r"[。！？!?；;\n]", description):
        sentence = sentence.strip()
        match = CLAUSE.match(sentence)
        if not match or not (match["before"] or match["after"]):
            continue
        subject = match["subject"].strip("「」“”《》 ")
        product = match["object"].strip("「」“”《》 ")
        if re.search(r"宣布|报道|据悉|尚未|没有|可能|发布|展示|计划|透露|预计|或将|并未|如果|传闻|消息称|[将未会]$", subject):
            continue
        qualifier = match["qualifier"] or ""
        kind = ("plan" if qualifier.startswith(("计划", "拟", "将")) else
                "prototype" if match["verb"] == "展示" or "原型" in sentence else "launch")
        when = match["when"] or match["leading"]
        if qualifier.startswith("将于"):
            when = qualifier[2:]
        record = _record(url, kind, subject, product, when, sentence[:280], "rss_description")
        if record["id"] not in events or (record["status"] == "supported" and
                                          events[record["id"]]["status"] == "review"):
            events[record["id"]] = record
    if funding and funding.get("company") and funding.get("evidence"):
        record = _record(url, "funding", funding["company"], None, funding.get("event_date"),
                         funding["evidence"], "rss_description")
        events[record["id"]] = record
    if not any(event["kind"] in {"launch", "plan", "prototype"} for event in events.values()):
        if hint := HINT.search(title):
            record = _record(url, "launch", hint["subject"].strip(), None, None,
                             hint.group().strip("｜| "), "rss_title", "headline_only")
            events[record["id"]] = record
    return list(events.values())

