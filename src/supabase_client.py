"""Offline import preview by default; optional explicit PostgREST upserts."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from dotenv import dotenv_values

from .llm_parser import post_json
from .validate import ROOT, payload_digest, schema_errors

TABLES = ("taxonomy", "companies", "funding_events", "team_members", "sources")


def load_import(directory):
    report = json.loads((directory / "validation_report.json").read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise ValueError("导入需要通过的 validation_report.json")
    data = {}
    for table in TABLES:
        records = json.loads((directory / f"{table}.json").read_text(encoding="utf-8"))
        if schema_errors(records, table) or payload_digest(records) != report["payload_sha256"].get(table):
            raise ValueError(f"{table}: Schema 不符或文件在校验后变化，请重新校验")
        data[table] = records
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--apply", action="store_true", help="实际写入 Supabase；可能更新同 ID 记录")
    args = parser.parse_args(argv)
    try:
        data = load_import(args.output)
        for table, rows in data.items():
            print(f"{table}: {len(rows)} 行")
        if not args.apply:
            print("仅预览；未连接 Supabase。")
            return 0
        config = {**dotenv_values(ROOT / ".env"), **os.environ}
        url = (config.get("SUPABASE_URL") or "").strip().rstrip("/")
        key = (config.get("SUPABASE_KEY") or "").strip()
        if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", url) or not key:
            raise ValueError("请配置 Supabase HTTPS 项目地址和仅用于服务端的写入密钥")
        headers = {"apikey": key, "Prefer": "resolution=merge-duplicates,return=minimal"}
        if not key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {key}"
        for table, rows in data.items():
            if rows:
                try:
                    post_json(f"{url}/rest/v1/{table}?on_conflict=id", headers, rows)
                except RuntimeError as exc:
                    raise RuntimeError(f"{table}: {exc}。前面表可能已写入；修正后可以按同一 ID 重试。") from None
                print(f"已写入 {table}: {len(rows)} 行")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"导入未完成: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

