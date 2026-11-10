"""Project-event search and the shared, on-demand news refresh job."""
import csv
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import logging
import re
from threading import Lock, Thread
from time import monotonic
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..news_36kr import FetchError, collect, read_state
from ..project_events import KINDS, extract_events
from .taxonomy_service import key

CHINA = timezone(timedelta(hours=8))
LOG = logging.getLogger(__name__)
Kind = Literal["auto", "all", "launch", "prototype", "plan", "funding"]
Scope = Literal["auto", "all", "event", "reported"]
TYPE_TERMS = (
    ("plan", r"计划|拟发布|将发布|发布计划|\bplan(?:s|ned)?\b"),
    ("prototype", r"原型|展示|\bprototype\b"),
    ("funding", r"融资|投资事件|\bfunding\b|\bfinancing\b"),
    ("launch", r"发布|推出|\blaunch(?:ed|es)?\b|\breleas(?:e|ed|es)\b"),
)
FILLER = re.compile(
    r"今天|今日|最近|过去一周|当天|哪些|哪家|哪个公司|哪家公司|谁|有没有|帮我|查找|找出|"
    r"找|看看|给我|新一代机器人|新机器人|了|的项目|项目动态|公司|报道|"
    r"\b(?:today|recent|last\s+7\s+days|who|what|which|companies|company|reported|report|find|me|"
    r"show|demos?|new\s+robots?|a|the|has|have)\b", re.I)
ALIASES = {
    "humanoid": "人形机器人", "humanoid robot": "人形机器人",
    "quadruped": "四足机器人", "robot dog": "机器狗",
    "dexterous hand": "灵巧手", "embodied ai": "具身智能", "physical ai": "物理智能",
}


class EventQuery(BaseModel):
    query: str = Field(default="", max_length=240)
    kind: Kind = "auto"
    scope: Scope = "auto"
    day: date | None = None
    sectors: list[str] = Field(default_factory=list, max_length=30)


class StructureQuery(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=1000)


SECTOR_TERMS = {
    "人形机器人本体": ("人形机器人",),
    "关节模组": ("关节模块",),
    "机器人大脑（VLA、具身大模型）": ("机器人大脑", "具身大脑", "具身大模型", "VLA"),
}


def _local_day(value):
    if not value:
        return None
    try:
        instant = datetime.fromisoformat(value)
        return instant.astimezone(CHINA).date().isoformat() if instant.tzinfo else None
    except (TypeError, ValueError):
        return None


def _article_events(article):
    events = article.get("events")
    if not isinstance(events, list):
        events = extract_events(article["url"], article.get("title", ""))
    return [event for event in events if isinstance(event, dict) and
            event.get("kind") in KINDS and event.get("evidence")]


def _event_source(article):
    return {"source_url": article["url"], "article_title": article["title"],
            "published_at": article.get("published_at"), "keywords": article.get("keywords", [])}


def event_rows(state):
    rows = []
    for article in state["articles"]:
        # Snapshots written before event extraction can contribute headline hints.
        for event in _article_events(article):
            rows.append({**event, **_event_source(article)})
    return sorted(rows, key=lambda row: row["event_date"] or _local_day(row["published_at"]) or "", reverse=True)


def structure_articles(state, urls):
    articles = {article["url"]: article for article in state["articles"]}
    unique = list(dict.fromkeys(urls))
    if any(url not in articles for url in unique):
        raise HTTPException(422, detail="unknown_article")
    rows, reused = [], 0
    for url in unique:
        article = articles[url]
        description = article.get("rss_description")
        if isinstance(description, str) and description:
            events = extract_events(url, article["title"], description, article.get("funding"))
        else:
            reused += 1
            events = _article_events(article)
        source = {**_event_source(article), "topic_focus": article.get("topic_focus")}
        if events:
            rows.extend({**event, **source} for event in events)
        else:
            rows.append({**source, "kind": None, "subject": None, "product": None,
                         "event_date": None, "time_text": None, "status": "article_only",
                         "evidence": None, "review_reason": "no_explicit_event"})
    return {"rows": rows, "article_count": len(unique),
            "event_count": sum(row["kind"] is not None for row in rows),
            "archived_only": reused}


def search_events(state, request, today=None):
    today = today or datetime.now(CHINA).date()
    query = request.query.strip().lower()
    explicit = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", query)
    day = request.day
    if explicit and not day:
        try:
            day = date.fromisoformat(explicit[0])
        except ValueError as exc:
            raise HTTPException(422, detail="invalid_date") from exc
    recent = bool(re.search(r"最近|过去一周|\brecent\b|\blast\s+7\s+days\b", query))
    date_prompt = bool(day or re.search(r"今天|今日|\btoday\b", query))
    scope = request.scope
    if scope == "auto":
        scope = ("reported" if re.search(r"报道|\breport(?:ed)?\b", query) else "event"
                 ) if date_prompt or recent else "all"
    end = day or today
    start = end - timedelta(days=6) if recent and not date_prompt else end
    start_iso, end_iso = start.isoformat(), end.isoformat()

    kind = request.kind
    if kind == "auto":
        kind = next((name for name, pattern in TYPE_TERMS if re.search(pattern, query)), "all")
    clean = explicit and query.replace(explicit[0], "") or query
    for pattern in sorted(ALIASES, key=len, reverse=True):
        clean = clean.replace(pattern, " " + ALIASES[pattern] + " ")
    for _, pattern in TYPE_TERMS:
        clean = re.sub(pattern, " ", clean)
    clean = FILLER.sub(" ", clean)
    terms = [term.strip() for term in re.split(r"[\s？?，,。；;：:、()]+", clean)
             if len(term.strip()) >= 2]

    results, review = [], []
    for row in event_rows(state):
        if kind != "all" and row["kind"] != kind:
            continue
        haystack = " ".join(str(row.get(key) or "") for key in ("subject", "product", "article_title", "evidence"))
        if request.sectors:
            evidence_text = key(haystack)
            if not any(key(term) in evidence_text for sector in request.sectors
                       for term in (sector, sector.split("（", 1)[0], *SECTOR_TERMS.get(sector, ()))):
                continue
        haystack += " " + " ".join(row["keywords"])
        if any(term not in haystack.lower() for term in terms):
            continue
        reported = _local_day(row["published_at"])
        event_day = row.get("event_date")
        reference = reported if scope == "reported" else event_day
        if scope != "all" and not (reference and start_iso <= reference <= end_iso):
            if not (scope == "event" and not event_day and reported and start_iso <= reported <= end_iso):
                continue
            review.append(row)
        else:
            (results if row.get("status") == "supported" else review).append(row)
    return {"results": results, "review": review, "kind": kind, "scope": scope,
            "from": start_iso if scope != "all" else None, "to": end_iso if scope != "all" else None,
            "fetched_at": state.get("fetched_at")}


class RefreshJob:
    def __init__(self, path, collector, cooldown):
        self.path, self.collector, self.cooldown = path, collector, cooldown
        self.lock = Lock()
        self.state = {"status": "idle", "stats": None}
        self.last_start = None

    def view(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.state["status"] == "running":
                return {**self.state, "accepted": False}
            remaining = self.cooldown - (monotonic() - self.last_start) if self.last_start is not None else 0
            if remaining > 0:
                return {**self.state, "accepted": False, "retry_after": int(remaining) + 1}
            self.last_start = monotonic()
            self.state = {"status": "running", "stats": None}
            Thread(target=self._run, name="radar-rss-refresh", daemon=True).start()
            return {**self.state, "accepted": True}

    def _run(self):
        try:
            stats = self.collector(self.path)
            result = {"status": "succeeded", "stats": stats}
        except (FetchError, OSError, ValueError):
            LOG.warning("Radar RSS refresh failed", exc_info=True)
            result = {"status": "failed", "stats": None}
        except Exception:
            LOG.exception("Unexpected radar refresh error")
            result = {"status": "failed", "stats": None}
        with self.lock:
            self.state = result


def _csv_cell(value):
    text = "" if value is None else str(value)
    # A source string must not become a spreadsheet formula.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def router(path, *, collector=collect, cooldown=60):
    api = APIRouter(prefix="/api/v1/radar", tags=["project radar"])
    job = RefreshJob(path, collector, cooldown)

    def state():
        try:
            return read_state(path)
        except (OSError, ValueError, FetchError) as exc:
            LOG.warning("Unreadable radar snapshot: %s", exc)
            raise HTTPException(503, detail="snapshot_unavailable") from exc

    @api.get("/snapshot")
    def snapshot():
        data = state()
        articles = [{key: row.get(key) for key in ("title", "url", "published_at", "topic_focus")}
                    for row in data["articles"]]
        return {"fetched_at": data.get("fetched_at"), "last_batch": data.get("last_batch"),
                "articles": articles, "events": event_rows(data), "refresh": job.view()}

    @api.post("/refresh", status_code=202)
    def refresh():
        return job.start()

    @api.post("/search")
    def search(body: EventQuery, request: Request):
        taxonomy = request.app.state.service.taxonomy
        labels = [taxonomy.sector(value) for value in body.sectors]
        if None in labels:
            raise HTTPException(422, detail="unknown_sector")
        return search_events(state(), body.model_copy(update={"sectors": labels}))

    @api.post("/structure")
    def structure(body: StructureQuery):
        return structure_articles(state(), body.urls)

    @api.get("/events.csv", response_class=Response)
    def export():
        file = StringIO()
        file.write("\ufeff")
        writer = csv.writer(file)
        columns = ("kind", "subject", "product", "event_date", "time_text", "published_at",
                   "status", "evidence", "evidence_field", "source_url")
        writer.writerow(columns)
        for row in event_rows(state()):
            writer.writerow([_csv_cell(row.get(column)) for column in columns])
        return Response(file.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="project-events.csv"'})

    return api

