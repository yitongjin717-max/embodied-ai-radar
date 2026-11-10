"""Collect 36Kr's official article RSS on demand."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from .project_events import EXTRACTOR_VERSION, extract_events

ROOT = Path(__file__).resolve().parents[1]
FEED_URL = "https://www.36kr.com/feed-article"
ROBOTS_URL = "https://www.36kr.com/robots.txt"
AGENT = "EmbodiedAI-Mapping-RSS/1.0"
TRANSIENT = {408, 500, 502, 503, 504}
TOPICS = ("具身智能", "具身大脑", "具身机器人", "具身模型", "人形机器人", "双足机器人",
          "四足机器人", "机器狗", "灵巧手", "机器人关节", "机器人大脑", "物理ai", "物理智能",
          "embodied ai", "humanoid robot", "dexterous hand")
ROUND = r"(?:种子|天使[+＋]*|Pre[- ]?[A-D][+＋]*|[A-H](?:[+＋]+|\d+)?)轮"
AMOUNT = (r"(?:约|近|超|逾)?(?:人民币|美元)?"
          r"(?:数千万级?|数百万级?|数十亿|数亿|千万元级?|千万级|百万级|"
          r"\d+(?:\.\d+)?(?:万亿|亿|万)元?)(?:级|以上)?(?:人民币|美元)?")


class FetchError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(value or "")
    parser.close()
    return " ".join("".join(parser.parts).split())


def http_get(url, headers, *, limit, sleep=time.sleep):
    opener = build_opener(NoRedirect())
    for attempt in range(2):
        try:
            request = Request(url, headers={"User-Agent": AGENT, **headers})
            with opener.open(request, timeout=8) as response:
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise FetchError(f"{url} 超过响应大小上限")
                return response.status, response.headers, body
        except HTTPError as exc:
            with exc:
                if exc.code in {304, 404, 410}:
                    return exc.code, exc.headers, b""
                if exc.code == 429 or exc.headers.get("Retry-After"):
                    delay = exc.headers.get("Retry-After")
                    hint = f"（Retry-After: {delay}）" if delay else ""
                    raise FetchError(f"{url} 返回 HTTP {exc.code}{hint}，请稍后再运行。") from exc
                if exc.code not in TRANSIENT or attempt:
                    raise FetchError(f"{url} 返回 HTTP {exc.code}。") from exc
        except (TimeoutError, OSError, URLError) as exc:
            if attempt:
                raise FetchError(f"{url} 请求失败：{exc}") from exc
        sleep(1)
    raise AssertionError("unreachable")


def read_feed(state, get):
    status, headers, body = get(ROBOTS_URL, {"Accept": "text/plain"}, limit=96 * 1024)
    if status == 200:
        rules_text = body.decode("utf-8-sig", errors="replace")
        if "html" in headers.get("Content-Type", "").lower() or rules_text.lstrip().startswith("<"):
            raise FetchError("robots.txt 返回 HTML，暂时无法确认自动访问规则。")
        rules = RobotFileParser(ROBOTS_URL)
        rules.parse(rules_text.splitlines())
        # Conservatively stop on advanced exclusions the stdlib parser may ignore.
        for line in rules_text.splitlines():
            name, _, pattern = line.split("#", 1)[0].partition(":")
            pattern = pattern.strip()
            if name.strip().casefold() == "disallow" and any(c in pattern for c in "*$"):
                regex = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
                if re.match(regex + ("$" if pattern.endswith("$") else ""), "/feed-article"):
                    raise FetchError("robots.txt 含可能适用于此 RSS 的通配排除规则。")
        if not rules.can_fetch(AGENT, FEED_URL):
            raise FetchError("robots.txt 不允许此客户端访问文章 RSS。")
        if rules.crawl_delay(AGENT) or rules.request_rate(AGENT):
            raise FetchError("站点设置了限速规则，需要先配置相应间隔。")
    elif status not in {404, 410}:
        raise FetchError(f"robots.txt 返回 HTTP {status}，无法确认自动访问规则。")

    request_headers = {"Accept": "application/rss+xml, application/xml, text/xml"}
    for key, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
        if state.get("extractor_version") == EXTRACTOR_VERSION and state["feed"].get(key):
            request_headers[header] = state["feed"][key]
    status, headers, body = get(FEED_URL, request_headers, limit=3 * 1024 * 1024)
    if status == 304 and len(request_headers) > 1:
        return None, None
    if status != 200:
        raise FetchError(f"文章 RSS 返回 HTTP {status}。")
    return body, {"etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified")}


def canonical_url(link):
    try:
        parsed = urlsplit(link)
        match = re.fullmatch(r"/p/(\d+)/?", parsed.path)
        if parsed.scheme in {"http", "https"} and parsed.netloc in {"36kr.com", "www.36kr.com"} and match:
            return f"https://www.36kr.com/p/{match[1]}"
    except ValueError:
        pass
    return None


def publication_date(raw):
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            # 36Kr also emits "YYYY-MM-DD HH:MM:SS  +0800".
            try:
                value = datetime.strptime(" ".join(raw.split()), "%Y-%m-%d %H:%M:%S %z")
            except ValueError:
                return None
    return value.isoformat() if value.tzinfo else None


def funding_fields(text):
    """Only extract an explicitly stated single deal. Keep its date unknown."""
    rounds = {match.group().casefold() for match in re.finditer(ROUND, text, re.I)}
    if len(rounds) != 1:
        return None
    deals = list(re.finditer(
        rf"「(?P<company>[^」]{{2,40}})」(?:于近日|近日|日前|近期)?"
        rf"(?:已)?(?:完成|获|获得)(?P<amount>{AMOUNT})?(?P<round>{ROUND})融资",
        text, re.I))
    if len(deals) != 1:
        return None
    match = deals[0]
    # Return one unambiguous organization if named directly after this deal.
    investor = re.match(r"，投资方包括([^，。；、及和]{2,60}?(?:有限公司|投资公司))(?=[及和，。；、]|$)",
                        text[match.end():])
    return {"company": match["company"], "round": match["round"],
            "amount_text": match["amount"], "event_date": None,
            "named_investors": [investor[1]] if investor else [],
            "evidence": match.group() + (investor[0] if investor else "")}


def parse_feed(body):
    try:
        xml = body.decode("utf-8-sig")
    except UnicodeError as exc:
        raise FetchError("RSS 不是预期的 UTF-8 编码。") from exc
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", xml, re.I):
        raise FetchError("收到含 DTD 或实体声明的响应，已停止解析。")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise FetchError("响应不是有效 RSS XML，可能是安全检测页或临时错误页。") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FetchError("响应不是 RSS 文档，可能是安全检测页。")
    items = channel.findall("item")
    if not items:
        raise FetchError("RSS 没有文章条目，保留已有数据。")
    records = {}
    valid = 0
    for item in items:
        url = canonical_url((item.findtext("link") or "").strip())
        title = plain(item.findtext("title"))
        if not url or not title:
            continue
        valid += 1
        description = plain(item.findtext("description"))[:12000]
        lead = (title + " " + plain(item.findtext("summary")) + " " + description[:600]).casefold()
        searchable = lead + " " + description.casefold()
        labels = [word for word in TOPICS if word in searchable]
        if not labels:
            continue
        raw_date = (item.findtext("pubDate") or "").strip() or None
        funding = funding_fields(description)
        row = {"source": "36Kr", "title": title, "url": url, "published_at": publication_date(raw_date),
               "published_at_raw": raw_date, "keywords": labels,
               "topic_focus": "primary" if any(word in lead for word in labels) else "mention",
               "event_type": "funding" if funding else "news", "funding": funding,
               "rss_description": description}
        row["events"] = extract_events(url, title, description, funding)
        old = records.get(url)
        if not old or (funding and not old["funding"]):
            records[url] = row
    if not valid:
        raise FetchError("RSS 条目缺少可识别的 36氪文章地址或标题。")
    return list(records.values()), len(items)


@contextmanager
def output_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Closing the file releases the lock even if the process was interrupted.
    with path.with_name(path.name + ".lock").open("a+b") as handle:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def read_state(path):
    if not path.exists():
        return {"version": 1, "feed": {"url": FEED_URL}, "articles": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("version") != 1 or
            not isinstance(state.get("feed"), dict) or state["feed"].get("url") != FEED_URL or
            not isinstance(state.get("articles"), list) or
            any(not isinstance(row, dict) or not isinstance(row.get("url"), str) or
                canonical_url(row["url"]) != row["url"] for row in state["articles"])):
        raise FetchError("已有 JSON 不是 36氪采集快照，请检查输出路径。")
    return state


def atomic_save(path, state):
    tmp = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
            tmp = Path(output.name)
            json.dump(state, output, ensure_ascii=False, indent=2)
            output.write("\n")
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def collect(path, *, get=http_get):
    with output_lock(path):
        state = read_state(path)
        body, validators = read_feed(state, get)
        if body is None:
            return {"status": "not_modified", "new": 0, "saved": len(state["articles"])}
        records, scanned = parse_feed(body)
        by_url = {row["url"]: row for row in state["articles"]}
        previous = set(by_url)
        for row in records:
            old = by_url.get(row["url"], {})
            if old.get("funding") and not row["funding"]:
                row["funding"], row["event_type"] = old["funding"], old["event_type"]
            if old.get("published_at") and not row["published_at"]:
                row["published_at"], row["published_at_raw"] = old["published_at"], old["published_at_raw"]
            by_url[row["url"]] = row
        state["feed"].update(validators)
        state["extractor_version"] = EXTRACTOR_VERSION
        state["last_batch"] = {"scanned": scanned, "matched": len(records),
                               "new": len(set(by_url) - previous)}
        state["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["articles"] = sorted(by_url.values(), key=lambda row: row.get("published_at") or "", reverse=True)
        atomic_save(path, state)
        return {"status": "ok", "scanned": scanned, "matched": len(records),
                "primary": sum(row["topic_focus"] == "primary" for row in records),
                "new": len(set(by_url) - previous), "saved": len(by_url)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="手动采集 36氪官方文章 RSS，导出具身智能新闻。")
    parser.add_argument("--output", type=Path, default=ROOT / "news" / "36kr.json")
    args = parser.parse_args(argv)
    try:
        stats = collect(args.output)
    except (FetchError, OSError, ValueError, KeyError) as exc:
        print(f"采集未完成：{exc}。未写入新数据。", file=sys.stderr)
        return 1
    print(json.dumps(stats, ensure_ascii=False))
    print(f"输出：{args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

