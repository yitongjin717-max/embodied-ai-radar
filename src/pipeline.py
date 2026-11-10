"""Command-line workflow: extract, normalize, validate, export."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from .extract import (COMPANY_FIELDS, EXTRA_COMPANY_FIELDS, NAME, SOURCE, SOURCE_FIELDS, SOURCE_ID,
                      TEAM, TEAM_FIELDS, read_book)
from .normalize import clean, funding_parts, iso_date, labels, name_key, stable_id
from .validate import validate, validate_export

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAMES = ["宇树科技", "智元机器人", "银河通用"]
DATASETS = ("companies", "funding_events", "team_members", "sources", "taxonomy", "llm_suggestions")
LIST_FIELDS = {"founders", "products", "major_customers", "historical_investors",
               "primary_tracks", "sub_tracks", "application_scenarios", "technology_routes",
               "business_models"}
DATE_FIELDS = {"founded_date", "compiled_date", "latest_funding_disclosure_date",
               "publication_date", "retrieved_date"}
SCOPE_RE = re.compile("网传|知情人士|预计|应有|另有|另据|目标|累计|招股书|下线|产能")
AMOUNT_RE = re.compile("近|数|超|约|累计|合计|多|逾|级|以上")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _web_url(value):
    if not value:
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not any(c.isspace() for c in value)
    except ValueError:
        return False


def build(books, requested, all_companies):
    data = {key: [] for key in DATASETS}
    reviews = []
    problems = []
    by_name, found_ids, term_sources = {}, set(), defaultdict(list)

    def review(code, cid, source, message, **extra):
        if "coordinate" in source:
            row = locations[cid]
            source = {"workbook": row.workbook, "sheet": row.sheet,
                      "row": row.cells[NAME].row, **source}
        reviews.append(dict(code=code, company_id=cid, source=source, message=message, **extra))

    for book in books:
        for cid, row in book.companies.items():
            name = clean(row.value(NAME))
            if name_key(name) in by_name or cid in found_ids:
                raise ValueError(f"输入工作簿之间出现重复公司或公司ID: {name}")
            by_name[name_key(name)] = (cid, book, row)
            found_ids.add(cid)
        for field, terms in book.taxonomy.items():
            for term in terms:
                term_sources[(field, term)].append(book.path.name)
    missing = [n for n in requested if name_key(n) not in by_name] if not all_companies else []
    if missing:
        raise ValueError(f"公司主表没有匹配: {'、'.join(missing)}。请用 --company 指定实际名称或 --all。")
    selected = list(by_name.values()) if all_companies else [by_name[key] for key in dict.fromkeys(map(name_key, requested))]
    if not selected:
        raise ValueError("没有可提取的公司")
    locations = {cid: row for cid, _, row in selected}
    selected_ids = {cid for cid, _, _ in selected}
    for book in books:
        for issue in book.issues:
            if issue["company_id"] in selected_ids or issue["company_id"] is None:
                (problems if issue["code"] == "unresolved_link" else reviews).append(issue)
    data["taxonomy"] = [{"id": stable_id("taxonomy", field, term), "field": field, "label": term,
                         "workbooks": names} for (field, term), names in sorted(term_sources.items())]

    children = defaultdict(list)
    for book in books:
        for sheet, rows in book.children.items():
            for cid, row in rows:
                if cid in selected_ids:
                    children[cid].append((sheet, row))

    company_map = COMPANY_FIELDS | EXTRA_COMPANY_FIELDS
    for cid, book, row in selected:
        origin = row.ref(company_map)
        company = {"id": cid, "provenance": origin}
        for header, key in company_map.items():
            value = row.value(header)
            if key in LIST_FIELDS:
                company[key] = labels(value, book.taxonomy.get(key, ()),
                                      delimiters="、；;\n/" if key == "business_models" else "、；;\n")
                if key in book.taxonomy:
                    for label in company[key]:
                        if label not in book.taxonomy[key]:
                            review("out_of_vocabulary", cid, origin["cells"][key],
                                   "保留原表中的词表外标签，待确认是否扩充词表", field=key, value=label)
            elif key in DATE_FIELDS:
                company[key] = iso_date(value)
                if clean(value) and company[key] is None:
                    review("date_unparsed", cid, origin["cells"][key], "无法可靠标准化日期", field=key)
            else:
                company[key] = clean(value)
        if company["website"] and not _web_url(company["website"]):
            review("website_syntax", cid, origin["cells"]["website"], "官网地址格式异常")
        for field in ("valuation", "revenue", "shipments"):
            if SCOPE_RE.search(company[field] or ""):
                review("check_disclosure_scope", cid, origin["cells"][field],
                       "请核对原披露时点、证据和统计口径", field=field)
        if company["funding_stage"] in {"上市", "IPO"}:
            review("check_listing_stage", cid, origin["cells"]["funding_stage"],
                   "复核申报、审核与正式挂牌是否被区分；保留表内原值")
        data["companies"].append(company)

        rounds = defaultdict(list)
        seen_segments = set()
        for i, (segment, parts) in enumerate(funding_parts(row.value("融资历史")), 1):
            round_name, amount, date_text, investors = parts or [None] * 4
            reasons = []
            if not parts:
                reasons.append("unparsed_segment")
            if date_text and not iso_date(date_text):
                reasons.append("date_unparsed")
            if date_text is None:
                reasons.append("date_missing")
            if AMOUNT_RE.search(amount or ""):
                reasons.append("approximate_or_aggregate_amount")
            if round_name and re.search("部分|另有|未披露|口径|新一轮|系列", round_name):
                reasons.append("round_scope_or_unspecified")
            # Investor remarks after semicolons can describe other rounds.
            investor_scope_ambiguous = bool(re.search("[；;]", investors or ""))
            if investor_scope_ambiguous:
                reasons.append("investor_scope_ambiguous")
            if segment.strip() in seen_segments:
                reasons.append("duplicate_segment")
            seen_segments.add(segment.strip())
            event = {"id": stable_id("funding", cid, str(i), segment), "company_id": cid,
                     "sequence": i, "round_name": round_name, "amount_text": amount,
                     "event_date": iso_date(date_text), "date_text": date_text,
                     "investor_text": investors,
                     "investors": [] if investor_scope_ambiguous else labels(investors, delimiters="、，,"),
                     "raw_value": segment, "parse_status": "parsed" if parts else "unparsed",
                     "review_reasons": reasons, "needs_review": bool(reasons),
                     "provenance": {**origin, "cells": {"funding_history": origin["cells"]["funding_history"]}}}
            data["funding_events"].append(event)
            if round_name:
                rounds[round_name].append(event)
        for same_round in rounds.values():
            if len(same_round) > 1:
                for event in same_round:
                    event["review_reasons"].append("repeated_round_label")
                    event["needs_review"] = True
        for event in (e for group in rounds.values() for e in group if e["needs_review"]):
            review("funding_review", cid, event["provenance"]["cells"]["funding_history"],
                   "核对原轮次的金额、时点或重复标记", record_id=event["id"], reasons=event["review_reasons"])
        # Unparsed events may lack a round label and hence do not appear in rounds.
        for event in (e for e in data["funding_events"] if e["company_id"] == cid and not e["round_name"]):
            review("funding_review", cid, event["provenance"]["cells"]["funding_history"],
                   "无法按四段式解析；保留原段供人工复核", record_id=event["id"], reasons=event["review_reasons"])

        member_names = set()
        for sheet, child in children[cid]:
            mapping = TEAM_FIELDS if sheet == TEAM else SOURCE_FIELDS
            ref = child.ref(mapping | {NAME: "company_name", SOURCE_ID: "source_company_id"})
            values = {key: clean(child.value(header)) for header, key in mapping.items()}
            if sheet == TEAM:
                person = values["name"]
                if not person:
                    problems.append(dict(code="team_name_missing", company_id=cid, source=ref))
                    continue
                member_names.add(name_key(person))
                for key in ("education", "work_history"):
                    values[key] = labels(values[key], delimiters="\n")
                row_id = stable_id("team", cid, name_key(person))
                dataset = "team_members"
            else:
                url = values["url"]
                if not url:
                    problems.append(dict(code="source_url_missing", company_id=cid, source=ref))
                    continue
                if not _web_url(url):
                    review("source_url_syntax", cid, ref, "来源链接格式异常")
                for header, key in mapping.items():
                    if key in DATE_FIELDS:
                        values[key] = iso_date(child.value(header))
                        if key == "retrieved_date" and clean(child.value(header)) and values[key] is None:
                            review("date_unparsed", cid, ref, "检索日期无法标准化", field=key)
                row_id, dataset = stable_id("source", cid, url), "sources"
            data[dataset].append({"id": row_id, "company_id": cid, **values, "provenance": ref})
        for founder in company["founders"]:
            # Roles and aliases in parentheses may differ between the two sheets.
            person = re.split("[（(]", founder, maxsplit=1)[0]
            if not any(re.split("[（(]", name, maxsplit=1)[0] == name_key(person) for name in member_names):
                review("founder_without_team_row", cid, origin["cells"]["founders"],
                       "主表创始人名单中该条目未与团队行匹配，核对名称、角色或补充来源", value=founder)
        if not any(sheet == SOURCE for sheet, _ in children[cid]):
            review("no_source_rows", cid, origin, "来源表无关联行")
    return data, reviews, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, action="append", help="可多次指定；默认 data/mapping_template.xlsx")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--company", action="append", help="指定主表公司全名；可多次使用")
    selection.add_argument("--all", action="store_true", help="提取指定工作簿的全部公司")
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--mode", choices=("mock", "llm"), default="mock")
    parser.add_argument("--provider", choices=("deepseek", "openai"), default="deepseek")
    parser.add_argument("--validate-only", action="store_true", help="重新读取 Excel 并校验已有 JSON，不发起 API 调用")
    args = parser.parse_args(argv)
    try:
        paths = args.workbook or [ROOT / "data" / "mapping_template.xlsx"]
        if len({p.name.casefold() for p in paths}) != len(paths):
            raise ValueError("工作簿文件名重复；请用不同文件名以区分溯源记录")
        for p in paths:
            if not p.is_file():
                raise ValueError(f"找不到 Excel: {p.resolve()}。请放入 data/ 或用 --workbook 指定。")
        books = [read_book(p) for p in paths]
        expected, reviews, problems = build(books, args.company or DEFAULT_NAMES, args.all)
        mode = "mock"
        if args.validate_only:
            data = {key: json.loads((args.output / (key + ".json")).read_text(encoding="utf-8")) for key in DATASETS}
            mode = "validate_only"
        else:
            data = dict(expected)
            if args.mode == "llm" and not problems:
                from .llm_parser import suggest
                data["llm_suggestions"] = suggest(data["companies"], args.provider)
                mode = "llm"
            for key, rows in data.items():
                write_json(args.output / (key + ".json"), rows)
        report = validate(data, reviews, problems, books, mode)
        validate_export(data, expected, report)
        write_json(args.output / "validation_report.json", report)
        print(f"公司 {report['counts']['companies']} | 融资 {report['counts']['funding_events']} | "
              f"团队 {report['counts']['team_members']} | 来源 {report['counts']['sources']} | "
              f"校验错误 {len(report['errors'])} | 待复核 {len(report['reviews'])}")
        print(f"输出目录: {args.output.resolve()}")
        return 0 if report["passed"] else 1
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"提取失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

