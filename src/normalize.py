"""Pure functions for conservative, reproducible normalization."""
from datetime import date, datetime
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5

MISSING = {"", "-", "—", "--", "/", "na", "n/a", "null", "none", "未知",
           "不详", "未公开", "未披露", "未透露", "未核实", "暂无", "无数据"}
PAIRS = {"(": ")", "（": "）", "【": "】", "[": "]", "《": "》", "“": "”", "「": "」"}


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return None if value.casefold() in MISSING else value


def raw(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def name_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def stable_id(kind, *parts):
    return str(uuid5(NAMESPACE_URL, "embodied-ai-mapping/" + kind + "/" +
                     "/".join(f"{len(p)}:{p}" for p in parts)))


def iso_date(value):
    """Retain day/month/year precision and never guess unrecognised dates."""
    if isinstance(value, date):
        return {"value": value.strftime("%Y-%m-%d"), "precision": "day"}
    match = re.fullmatch(
        r"(\d{4})(?:[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?|月)?)?年?"
        r"\s*(?:披露|报道|发布|报道时点|报道追溯|合并披露|工商披露|（融资库）)?", clean(value) or "")
    if not match:
        return None
    year, month, day = match.groups()
    try:
        date(int(year), int(month or "1"), int(day or "1"))
    except ValueError:
        return None
    parts = [year] + [p.zfill(2) for p in (month, day) if p is not None]
    return {"value": "-".join(parts), "precision": ("year", "month", "day")[len(parts) - 1]}


def segments(value, delimiters):
    """Split only outside paired punctuation. Preserve inner separators."""
    stack, start = [], 0
    for i, char in enumerate(value):
        if stack and char == stack[-1]:
            stack.pop()
        elif char in PAIRS:
            stack.append(PAIRS[char])
        elif not stack and char in delimiters:
            yield value[start:i]
            start = i + 1
    yield value[start:]


def labels(value, vocabulary=(), delimiters="、；;\n"):
    value = clean(value)
    if value is None:
        return []
    if re.match(r"^[①-⑳]", value) and "\n" in value:
        return [line.strip() for line in value.splitlines() if line.strip()]
    # Recombine known labels with internal top-level delimiters, longest first.
    tokens = list(segments(value, delimiters))
    terms = {tuple(p.strip() for p in segments(v, delimiters)): v for v in vocabulary}
    lengths = sorted({len(k) for k in terms}, reverse=True)
    result, i = [], 0
    while i < len(tokens):
        for size in lengths:
            key = tuple(p.strip() for p in tokens[i:i + size])
            if i + size <= len(tokens) and key in terms:
                result.append(terms[key])
                i += size
                break
        else:
            if token := clean(tokens[i]):
                result.append(token)
            i += 1
    return result


def funding_parts(value):
    """Return each original segment and its four fields, if parseable."""
    def parse(segment):
        body = re.sub(r"^[①-⑳]\s*", "", segment.strip())
        parts = [clean(part) for part in segments(body, "|｜")]
        return parts if len(parts) == 4 and parts[0] else None

    text = clean(value) or ""
    # In both workbooks, numbered lines are authoritative. Semicolons
    # often belong to investor notes (sometimes citing a different round).
    for line in text.splitlines():
        chunks = list(segments(line, "；;"))
        if len(chunks) > 1 and all(parse(chunk) for chunk in chunks):
            yield from ((chunk, parse(chunk)) for chunk in chunks)
        elif line.strip():
            yield line, parse(line)

