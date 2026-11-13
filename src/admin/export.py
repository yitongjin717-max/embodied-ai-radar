"""Export a validated snapshot consumable by the public application's existing loader."""
import io
import json
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZIP_DEFLATED, ZipFile

from src.admin.store import DATA, companies, encode
from src.supabase_client import TABLES
from src.validate import SCHEMA, payload_digest, schema_errors

COMPANY_FIELDS = SCHEMA["$defs"]["company"]["properties"]
ARRAYS = {key for key, spec in COMPANY_FIELDS.items() if spec.get("type") == "array"}


def date_value(value):
    if isinstance(value, dict) or value is None:
        return value
    for precision, width in (("day", 10), ("month", 7), ("year", 4)):
        if isinstance(value, str) and len(value) == width:
            candidate = {"value": value, "precision": precision}
            if not schema_errors(candidate, "partial_date"):
                return candidate
    return None


def snapshot(db):
    data = {table: json.loads((DATA / f"{table}.json").read_text(encoding="utf-8")) for table in TABLES}
    source_pairs = {(row["company_id"], row["url"]) for row in data["sources"]}
    data["companies"] = []
    for entry in companies(db):
        record = {}
        for field in COMPANY_FIELDS:
            value = entry.get(field)
            if field in ARRAYS:
                value = value if isinstance(value, list) else [str(value)] if value else []
                value = [str(item) for item in value if item]
            elif field == "founded_date":
                value = date_value(value)
            elif field == "funding_history" and isinstance(value, list):
                value = "\n".join(str(item) for item in value) or None
            elif field != "provenance" and value is not None and not isinstance(value, (dict, str)):
                value = str(value)
            record[field] = value
        provenance = {"workbook": "Admin review", "sheet": "Confirmed companies", "row": 1,
                      "cells": {"name": {"coordinate": "A1", "header": "Company name", "raw_value": entry["name"]}}}
        record["provenance"] = record["provenance"] or provenance
        data["companies"].append(record)
        for url in set(entry.get("admin_sources", {}).values()):
            if (entry["id"], url) in source_pairs:
                continue
            data["sources"].append({
                "id": str(uuid5(NAMESPACE_URL, entry["id"] + url)), "company_id": entry["id"],
                "url": url, "title": None, "publication_date": None, "retrieved_date": None,
                "source_limits": "Manually reviewed article extraction",
                "supported_fields": ", ".join(k for k, v in entry["admin_sources"].items() if v == url),
                "provenance": provenance,
            })
    report = json.loads((DATA / "validation_report.json").read_text(encoding="utf-8"))
    for table, rows in data.items():
        errors = schema_errors(rows, table)
        if errors:
            raise ValueError(f"Snapshot validation failed for {table}: {errors[0]['path']}")
        report["payload_sha256"][table] = payload_digest(rows)
        report["counts"][table] = len(rows)
    data["validation_report"] = report
    data["admin_events"] = [json.loads(row[0]) for row in db.execute("SELECT payload FROM events")]
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for table, rows in data.items():
            archive.writestr(f"matching_data/{table}.json", encode(rows))
    return output.getvalue()
