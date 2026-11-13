"""SQLite persistence for the independent administrator service."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import re
from uuid import uuid4

from src.admin.workflow import FIELDS

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "matching_data"
FILTERS = ("primary_tracks", "sub_tracks", "application_scenarios", "technology_routes", "funding_stage")


def encode(value):
    return json.dumps(value, ensure_ascii=False)


@contextmanager
def database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS extractions (
            id INTEGER PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reviews (
            extraction_id INTEGER, revision INTEGER, subject_index INTEGER, state TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (extraction_id, revision, subject_index)
        );
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL, source TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS events (
            company_id TEXT, source_key TEXT, type TEXT, summary TEXT, payload TEXT NOT NULL,
            PRIMARY KEY (company_id, source_key, type, summary)
        );
        CREATE TABLE IF NOT EXISTS edits (
            id INTEGER PRIMARY KEY, company_id TEXT NOT NULL, actor TEXT NOT NULL,
            before_json TEXT, after_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS candidates (url TEXT PRIMARY KEY, payload TEXT NOT NULL);
    """)
    for company in json.loads((DATA / "companies.json").read_text(encoding="utf-8")):
        db.execute("INSERT OR IGNORE INTO companies (id,name,payload,source) VALUES (?,?,?,?)",
                   (company["id"], company["name"], encode(company), "manual"))


def save_extraction(db, data):
    key = data["url"] or "text:" + data["body_hash"]
    row = db.execute("""
        INSERT INTO extractions(source_key,payload) VALUES (?,?)
        ON CONFLICT(source_key) DO UPDATE SET payload=excluded.payload,
        revision=revision+1, updated_at=CURRENT_TIMESTAMP RETURNING id,revision
    """, (key, encode(data))).fetchone()
    for index in range(len(data["subjects"])):
        db.execute("INSERT INTO reviews VALUES (?,?,?,'pending',CURRENT_TIMESTAMP)",
                   (row["id"], row["revision"], index))
    return {**dict(row), "duplicate": row["revision"] > 1, **data}


def queue(db):
    rows = db.execute("""
        SELECT e.id,e.revision,e.payload,r.subject_index,r.updated_at FROM extractions e
        JOIN reviews r ON e.id=r.extraction_id AND e.revision=r.revision
        WHERE r.state='pending' ORDER BY r.updated_at DESC
    """)
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]


def companies(db):
    return [{**json.loads(row["payload"]), "_source": row["source"], "_updated": row["updated_at"]}
            for row in db.execute("SELECT * FROM companies ORDER BY name")]


def normalize_name(name):
    return " ".join(name.split()).casefold()


def match_company(db, name):
    target = normalize_name(name)
    rows = list(db.execute("SELECT * FROM companies"))
    exact = [row for row in rows if normalize_name(row["name"]) == target]
    aliases = [row for row in rows if any(normalize_name(alias) == target for alias in
               (json.loads(row["payload"]).get("aliases", []) or []) +
               re.split(r"[()（）]", row["name"]))]
    matches = exact or aliases
    if len(matches) > 1:
        raise ValueError("Several companies match. Select a company explicitly.")
    return matches[0] if matches else None


def save_company(db, row, changes, actor, source, url=None):
    original = json.loads(row["payload"]) if row else {}
    company = {**original}
    company.setdefault("id", str(uuid4()))
    sources = company.setdefault("admin_sources", {}).copy()
    for field, value in changes.items():
        if field not in FIELDS or not isinstance(value, (str, list, int, float, type(None))):
            raise ValueError("Invalid company field.")
        if field == "funding_history" and value and source == "ai":
            before = company.get(field) or []
            before = before if isinstance(before, list) else [before]
            after = value if isinstance(value, list) else [value]
            value = before + [item for item in after if item not in before]
        company[field] = value
        if url:
            sources[field] = url
        else:
            sources.pop(field, None)
    company["admin_sources"] = sources
    if not isinstance(company.get("name"), str) or not company["name"].strip():
        raise ValueError("Company name is required.")
    db.execute("""
        INSERT INTO companies(id,name,payload,source) VALUES (?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name,payload=excluded.payload,
        source=excluded.source,updated_at=CURRENT_TIMESTAMP
    """, (company["id"], company["name"], encode(company), source))
    db.execute("INSERT INTO edits(company_id,actor,before_json,after_json) VALUES (?,?,?,?)",
               (company["id"], actor, encode(original), encode(company)))
    return company


def decide(db, request, actor):
    db.execute("BEGIN IMMEDIATE")
    extraction = db.execute("SELECT * FROM extractions WHERE id=?", (request["id"],)).fetchone()
    index = request["subject_index"]
    action = request["action"]
    if extraction is None or request["revision"] != extraction["revision"] or action not in {"approved", "discarded", "pending"}:
        raise ValueError("Review was replaced or the decision is invalid. Reload the queue.")
    if action == "pending":
        result = db.execute("""
            SELECT 1 FROM reviews WHERE extraction_id=? AND revision=? AND subject_index=? AND state='pending'
        """, (request["id"], request["revision"], index)).fetchone()
        if result is None:
            raise ValueError("This review has already been decided.")
        payload = json.loads(extraction["payload"])
        subject = payload["subjects"][index]
        for field, value in request["fields"].items():
            if field not in subject["fields"]:
                raise ValueError("Review fields must come from this extraction.")
            subject["fields"][field]["draft_value"] = value
        db.execute("UPDATE extractions SET payload=? WHERE id=?", (encode(payload), request["id"]))
        return {"state": action}
    result = db.execute("""
        UPDATE reviews SET state=?,updated_at=CURRENT_TIMESTAMP
        WHERE extraction_id=? AND revision=? AND subject_index=? AND state='pending'
    """, (action, request["id"], request["revision"], index))
    if result.rowcount != 1:
        raise ValueError("This review has already been decided.")
    if action == "discarded":
        return {"state": action}
    payload = json.loads(extraction["payload"])
    subject = payload["subjects"][index]
    selection = request.get("company_id")
    if selection == "new":
        company = None
    elif selection:
        company = db.execute("SELECT * FROM companies WHERE id=?", (selection,)).fetchone()
        if company is None:
            raise ValueError("Selected company no longer exists.")
    else:
        company = match_company(db, subject["name"])
    changes = request["fields"]
    if not isinstance(changes, dict) or set(changes) - (set(subject["fields"]) | {"name"}):
        raise ValueError("Review fields must come from this extraction.")
    if company is None:
        changes.setdefault("name", subject["name"])
    saved = save_company(db, company, changes, actor, "ai", payload["url"])
    for event_index in set(request.get("events", [])):
        if not isinstance(event_index, int) or not 0 <= event_index < len(subject["events"]):
            raise ValueError("Invalid event selection.")
        event = subject["events"][event_index]
        db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)",
                   (saved["id"], extraction["source_key"], event["type"], event["summary"],
                    encode({**event, "published_at": payload["published_at"], "url": payload["url"]})))
    return {"state": action, "company": saved}
