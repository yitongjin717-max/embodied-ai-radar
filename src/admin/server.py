"""Independent administrator service. Run with python -m src.admin.server."""
import base64
import binascii
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from src.admin import store, workflow
from src.admin.export import snapshot
from dotenv import load_dotenv
from src.news_36kr import FetchError, http_get, parse_feed, read_feed

PAGE = Path(__file__).with_name("index.html")


def handler_for(path, password, *, extract=workflow.extract, fetch=workflow.fetch_article):
    taxonomy = {}
    for row in json.loads((store.DATA / "taxonomy.json").read_text(encoding="utf-8")):
        taxonomy.setdefault(row["field"], set()).add(row["label"])

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
            data = body if isinstance(body, bytes) else store.encode(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def actor(self):
            scheme, _, token = self.headers.get("Authorization", "").partition(" ")
            try:
                decoded = base64.b64decode(token, validate=True).decode()
                name, separator, supplied = decoded.partition(":")
                if (scheme.lower() == "basic" and separator and name and len(name) <= 80
                        and hmac.compare_digest(supplied.encode(), password.encode())):
                    return name
            except (binascii.Error, UnicodeError):
                pass
            self.send(401, {"error": "Sign in to the administrator service."},
                      headers={"WWW-Authenticate": 'Basic realm="Embodied AI Radar Admin", charset="UTF-8"'})
            return None

        def do_GET(self):
            if self.path == "/healthz":
                self.send(200, {"status": "ok"})
                return
            if not self.actor():
                return
            route = urlsplit(self.path).path
            if route == "/":
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                return
            with store.database(path) as db:
                if route == "/api/companies":
                    self.send(200, store.companies(db))
                elif route == "/api/queue":
                    self.send(200, store.queue(db))
                elif route == "/api/candidates":
                    self.send(200, [json.loads(row[0]) for row in db.execute("SELECT payload FROM candidates")])
                elif route.startswith("/api/company/"):
                    company_id = route.rsplit("/", 1)[-1]
                    events = db.execute("SELECT payload FROM events WHERE company_id=?", (company_id,))
                    self.send(200, sorted((json.loads(row[0]) for row in events),
                                          key=lambda row: row["published_at"] or "", reverse=True))
                elif route == "/api/export":
                    try:
                        self.send(200, snapshot(db), "application/zip",
                                  headers={"Content-Disposition": 'attachment; filename="matching_data.zip"'})
                    except ValueError as exc:
                        self.send(400, {"error": str(exc)})
                else:
                    self.send(404, {"error": "Unknown page."})

        def do_POST(self):
            actor = self.actor()
            if not actor:
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if (self.headers.get_content_type() != "application/json"
                        or not 0 < size <= 250_000):
                    raise ValueError("Expected a JSON request under 250 KB.")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("Expected a JSON object.")
                result = self.process(urlsplit(self.path).path, request, actor)
            except (KeyError, TypeError, ValueError, OSError, FetchError) as exc:
                self.send(400, {"error": str(exc) if isinstance(exc, (ValueError, FetchError)) else
                                "Request failed. Check inputs or paste the article text."})
                return
            self.send(200, result)

        def process(self, route, request, actor):
            if route == "/api/feed":
                body, _ = read_feed({"feed": {}}, http_get)
                rows, _ = parse_feed(body)
                with store.database(path) as db:
                    db.executemany("INSERT OR REPLACE INTO candidates VALUES (?,?)",
                                   [(row["url"], store.encode(row)) for row in rows])
                return rows
            if route in {"/api/extract", "/api/rules"}:
                raw_url = request.get("url") or ""
                url = workflow.source_url(raw_url) if raw_url else None
                text = request.get("text") or ""
                published = request.get("published_at") or None
                if not text.strip() and url:
                    try:
                        text, found_date = fetch(url)
                    except (ValueError, OSError) as exc:
                        raise ValueError("Could not read the article. Paste its text and retry.") from exc
                    published = published or found_date
                if route == "/api/rules":
                    return {"rule_events": workflow.extract_events(
                        url or "", "", text, workflow.funding_fields(text))}
                result = extract(text, url, published, taxonomy)
                with store.database(path) as db:
                    return store.save_extraction(db, result)
            with store.database(path) as db:
                if route == "/api/review":
                    return store.decide(db, request, actor)
                if route == "/api/company":
                    row = db.execute("SELECT * FROM companies WHERE id=?", (request["id"],)).fetchone()
                    if row is None:
                        raise ValueError("Company not found.")
                    return store.save_company(db, row, request["fields"], actor, "manual")
            raise ValueError("Unknown endpoint.")

    return Handler


def make_server(address, path, password, **dependencies):
    if not password:
        raise ValueError("Set ADMIN_PASSWORD before starting the administrator service.")
    with store.database(path) as db:
        store.initialize(db)
    return ThreadingHTTPServer(address, handler_for(path, password, **dependencies))


if __name__ == "__main__":
    load_dotenv(store.ROOT / ".env")
    database = Path(os.getenv("ADMIN_DB_PATH", "var/admin.sqlite3"))
    with make_server((os.getenv("ADMIN_HOST", "127.0.0.1"), int(os.getenv("PORT", "8012"))),
                     database, os.getenv("ADMIN_PASSWORD")) as server:
        print(f"Administrator service listening on port {server.server_port}", flush=True)
        server.serve_forever()

