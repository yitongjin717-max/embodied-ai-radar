"""Validate structure, workbook consistency and review-only model output."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .extract import COMPANY_FIELDS
from .normalize import funding_parts, name_key

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "company.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)


def schema_errors(value, definition):
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker())
    return [{"code": "schema", "dataset": definition, "path": list(e.absolute_path), "message": e.message}
            for e in validator.iter_errors(value)]


def payload_digest(value):
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(body.encode("utf-8")).hexdigest()


def llm_evidence_errors(suggestion, company):
    """Check literal grounding. A matching excerpt still requires semantic review."""
    errors = []
    cells = company["provenance"]["cells"]
    result = suggestion["result"]
    for group in ("business_claims", "funding_candidates", "ambiguities"):
        for i, item in enumerate(result[group]):
            field = item.get("field", "funding_history")
            original = cells.get(field, {}).get("raw_value")
            quote = item["evidence"]
            reason = None
            if not quote.strip() or not isinstance(original, str) or quote not in original:
                reason = "证据不是指定单元格的原文片段"
            elif group == "business_claims":
                if item["status"] == "explicit" and (not item["claim"] or item["claim"] not in quote):
                    reason = "明确事实须逐字出现在证据中"
                if item["status"] != "explicit" and not item["needs_review"]:
                    reason = "推断和不确定内容必须人工复核"
                if item["status"] == "uncertain" and item["claim"] is not None:
                    reason = "无法确认的 claim 必须为 null"
            elif group == "funding_candidates":
                keys = ("round_name", "amount_text", "date_text", "investor_text")
                candidates = {segment.strip(): parts for segment, parts in funding_parts(original)}
                fields = candidates.get(quote.strip())
                if quote.strip() not in candidates:
                    reason = "融资候选须引用完整的单轮原文"
                elif any(item[key] is not None and item[key] not in quote for key in keys):
                    reason = "融资候选值须逐字出现在同一证据中"
                elif fields and any(item[key] not in (None, value) for key, value in zip(keys, fields)):
                    reason = "四段式融资候选须保留字段原值及其口径"
            if reason:
                errors.append({"code": "llm_ungrounded", "company_id": company["id"],
                               "path": [group, i], "message": reason})
    return errors


def validate(data, reviews, problems, books, mode):
    errors = list(problems)
    reviews = list(reviews)
    counts = {key: len(value) if isinstance(value, list) else 0 for key, value in data.items()}
    invalid = set()
    for key, value in data.items():
        current = schema_errors(value, key)
        errors.extend(current)
        if current:
            invalid.add(key)
    valid = {key: value if key not in invalid else [] for key, value in data.items()}
    companies = {c["id"]: c for c in valid["companies"]}
    for key, records in valid.items():
        id_field = "company_id" if key == "llm_suggestions" else "id"
        duplicate = [v for v, n in Counter(r[id_field] for r in records).items() if n > 1]
        errors.extend({"code": "duplicate_id", "dataset": key, "id": d} for d in duplicate)
        for row in records:
            if "company_id" in row and row["company_id"] not in companies:
                errors.append({"code": "orphan", "dataset": key, "company_id": row["company_id"]})
    if len(set(name_key(c["name"]) for c in companies.values())) != len(companies):
        errors.append({"code": "duplicate_company_name"})

    for suggestion in valid["llm_suggestions"]:
        if company := companies.get(suggestion["company_id"]):
            errors.extend(llm_evidence_errors(suggestion, company))
            if any(suggestion["result"].values()):
                reviews.append({"code": "llm_suggestion", "company_id": company["id"],
                                "message": "模型建议单独保存，需复核语义及证据后才可采纳"})
    fields = list(COMPANY_FIELDS.values())
    missing = Counter({f: 0 for f in fields})
    completeness = []
    for c in companies.values():
        absent = [f for f in fields if c[f] in (None, [], "")]
        missing.update(absent)
        completeness.append({"company_id": c["id"], "name": c["name"], "missing_fields": absent,
                             "present": len(fields) - len(absent), "total": len(fields)})
    missing_total = sum(missing.values())
    denominator = len(fields) * len(companies)
    return {"passed": not errors, "mode": mode, "counts": counts, "errors": errors, "reviews": reviews,
            "source_workbooks": [{"file": b.path.name, "sha256": b.digest} for b in books],
            "payload_sha256": {key: payload_digest(value) for key, value in data.items()},
            "missing_fields": dict(missing), "company_completeness": completeness,
            "completeness": {"present": denominator - missing_total, "total": denominator,
                             "ratio": round((denominator - missing_total) / denominator, 4) if denominator else None},
            "parse_failures": {"funding_segments": sum(e["parse_status"] == "unparsed"
                                                     for e in valid["funding_events"]),
                               "dates": (sum(r["code"] == "date_unparsed" for r in reviews)
                                         + sum("date_unparsed" in e["review_reasons"]
                                               for e in valid["funding_events"])),
                               "unresolved_links": sum(p["code"] == "unresolved_link" for p in problems)},
            "verification_scope": "Excel 一致性和字面证据校验；未访问外部链接，未独立核验现实事实。"}


def validate_export(data, expected, report):
    """Compare all deterministic values and provenance, including missing/extra rows."""
    for key, records in expected.items():
        if key == "llm_suggestions":
            continue
        if data[key] == records:
            continue
        actual = data[key]
        if isinstance(actual, list) and len(actual) == len(records):
            mismatch = next((i for i, pair in enumerate(zip(actual, records)) if pair[0] != pair[1]), None)
        else:
            mismatch = None
        report["errors"].append({"code": "excel_mismatch", "dataset": key, "first_index": mismatch,
                                 "message": "与当前源 Excel 的重新提取结果不同"})
    report["passed"] = not report["errors"]

