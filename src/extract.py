"""Locate observed layouts by header names; retain cell-level provenance."""
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from openpyxl import load_workbook

from .normalize import clean, labels, name_key, raw, stable_id

MAIN, TEAM, SOURCE, VOCAB = "公司主表", "团队表", "来源表", "词表"
COMPANY_FIELDS = {
    "公司名称": "name", "成立时间": "founded_date", "总部地域": "headquarters",
    "官网": "website", "创始人": "founders", "主营业务": "business_description",
    "一级赛道": "primary_tracks", "二级细分": "sub_tracks", "场景": "application_scenarios",
    "技术路线": "technology_routes", "当前阶段": "funding_stage", "融资历史": "funding_history",
    "老股东": "historical_investors", "最新估值": "valuation", "主要产品": "products",
    "标杆客户": "major_customers", "商业模式": "business_models", "出货量": "shipments",
    "营收规模": "revenue", "员工规模": "employee_scale", "整理日期": "compiled_date",
}
EXTRA_COMPANY_FIELDS = {
    "最近已核实融资披露": "latest_funding_disclosure_date", "访谈优先级（投研判断）": "interview_priority",
    "投资切入点（投研判断）": "investment_thesis", "首轮尽调问题（投研判断）": "diligence_questions",
    "口径与边界": "scope_notes", "公司ID": "source_company_id",
}
TEAM_FIELDS = {"姓名": "name", "角色": "role", "教育背景": "education", "工作背景": "work_history"}
SOURCE_FIELDS = {"URL": "url", "来源及标题": "title", "发布时间/证据时点": "publication_date",
                 "支持字段": "supported_fields", "来源类型/限制": "source_limits", "检索日期": "retrieved_date"}
VOCAB_FIELDS = {"二级细分（多选）": "sub_tracks", "场景（多选）": "application_scenarios",
                "技术路线（多选）": "technology_routes"}
NAME = "公司名称"
SOURCE_ID = "公司ID"
DIRECT = re.compile(r"='?公司主表'?!\$?([A-Z]+)\$?(\d+)", re.I)
INDEX_MATCH = re.compile(
    r"""=INDEX\('公司主表'!\$([A-Z]+)\$(\d+):\$\1\$(\d+),"""
    r"""MATCH\("([^"]+)",'公司主表'!\$([A-Z]+)\$\2:\$\5\$\3,0\)\)""", re.I)


@dataclass
class Row:
    workbook: str
    sheet: str
    cells: dict

    def value(self, header):
        return self.cells[header].value if header in self.cells else None

    def ref(self, field_map):
        return {"workbook": self.workbook, "sheet": self.sheet,
                "row": next(iter(self.cells.values())).row,
                "cells": {field_map[h]: {"coordinate": c.coordinate, "header": h,
                                          "raw_value": raw(c.value)}
                          for h, c in self.cells.items() if h in field_map}}


@dataclass
class Book:
    path: Path
    digest: str
    companies: dict
    children: dict
    taxonomy: dict
    issues: list


def find_headers(ws, required):
    """Search for the actual header row rather than assuming column positions."""
    candidates = []
    for row in ws.iter_rows():
        values = [c.value for c in row]
        if required <= set(values):
            duplicate = [v for v, n in Counter(values).items() if v is not None and n > 1]
            if duplicate:
                raise ValueError(f"{ws.title}: duplicate headers: {duplicate}")
            candidates.append((row[0].row, {c.value: c.column for c in row if c.value}))
    if len(candidates) != 1:
        raise ValueError(f"{ws.title}: expected one header with {sorted(required)}, found {len(candidates)}")
    return candidates[0]


def read_rows(ws, filename, required, guidance=True):
    header, columns = find_headers(ws, set(required))
    for row in range(header + (2 if guidance else 1), ws.max_row + 1):
        cells = {key: ws.cell(row, col) for key, col in columns.items()}
        if any(c.value not in ("", None) for c in cells.values()):
            yield Row(filename, ws.title, cells)


def _join(row, companies, ids, name_col, id_col, cached, main_ws):
    link = row.cells[NAME]
    source_id = clean(row.value(SOURCE_ID))
    if id_col:
        target = ids.get(source_id)
        if target is None:
            return None, "公司ID为空或在公司主表中找不到"
        if link.data_type == "f":
            m = INDEX_MATCH.fullmatch(link.value)
            if not m or (m[1], m[4], m[5]) != (name_col, source_id, id_col):
                return None, "名称公式和公司ID不一致或格式不受支持"
            if not int(m[2]) <= companies[target].cells[NAME].row <= int(m[3]):
                return None, "名称公式范围不含目标公司"
        elif clean(link.value) != clean(companies[target].value(NAME)):
            return None, "公司名称和公司ID不一致"
    elif link.data_type == "f":
        m = DIRECT.fullmatch(link.value)
        if not m or m[1].upper() != name_col:
            return None, "名称引用公式格式不受支持"
        reference = main_ws[f"{name_col}{int(m[2])}"]
        referenced_name = clean(reference.value)
        target = stable_id("company_name", name_key(referenced_name)) if referenced_name else None
        if target not in companies or companies[target].cells[NAME].coordinate != reference.coordinate:
            return None, "名称公式未指向有效公司数据行"
    else:
        name = clean(link.value)
        target = stable_id("company_name", name_key(name)) if name else None
        if target not in companies:
            return None, "名称未匹配公司主表"
    cached_value = cached[link.coordinate].value
    if link.data_type == "f" and cached_value is not None:
        if clean(cached_value) != clean(companies[target].value(NAME)):
            # The live row reference/ID is authoritative; stale cache is visible.
            return target, "名称公式缓存与主表不同，请在 Excel 中核对引用"
    return target, None


def read_book(path):
    with ExitStack() as stack:
        wb = load_workbook(path)
        stack.callback(wb.close)
        cache = load_workbook(path, data_only=True)
        stack.callback(cache.close)
        return _read_book(path, wb, cache)


def _read_book(path, wb, cache):
    filename = path.name
    missing_sheets = {MAIN, TEAM, SOURCE, VOCAB} - set(wb.sheetnames)
    if missing_sheets:
        raise ValueError(f"{filename}: 缺少工作表 {sorted(missing_sheets)}")
    ws = wb[MAIN]
    header, columns = find_headers(ws, set(COMPANY_FIELDS))
    id_col = ws.cell(header, columns[SOURCE_ID]).column_letter if SOURCE_ID in columns else None
    name_col = ws.cell(header, columns[NAME]).column_letter
    companies, ids, names = {}, {}, set()
    for row in read_rows(ws, filename, COMPANY_FIELDS):
        name, source_id = clean(row.value(NAME)), clean(row.value(SOURCE_ID))
        if not name or (id_col and not source_id):
            raise ValueError(f"{filename} {MAIN} {row.cells[NAME].coordinate}: 公司名称或公司ID缺失")
        key = name_key(name)
        cid = stable_id("source_company_id", source_id) if source_id else stable_id("company_name", key)
        if cid in companies or key in names:
            raise ValueError(f"{filename}: 重复公司名或公司ID: {name}")
        companies[cid] = row
        names.add(key)
        if source_id:
            ids[source_id] = cid
    taxonomy = {k: [] for k in VOCAB_FIELDS.values()}
    for row in read_rows(wb[VOCAB], filename, VOCAB_FIELDS, guidance=False):
        for header_name, key in VOCAB_FIELDS.items():
            if (value := clean(row.value(header_name))) and value not in taxonomy[key]:
                taxonomy[key].append(value)
    taxonomy["primary_tracks"] = ["具身智能"]
    model_rule = clean(ws.cell(header + 1, columns["商业模式"]).value) or ""
    taxonomy["business_models"] = labels(model_rule.partition("：")[2], delimiters="/")
    if not all(taxonomy.values()):
        raise ValueError(f"{filename}: 词表或商业模式填写说明为空")
    children, issues = {TEAM: [], SOURCE: []}, []
    for sheet, required in ((TEAM, [NAME, *TEAM_FIELDS]), (SOURCE, [NAME, "URL"])):
        for row in read_rows(wb[sheet], filename, required + ([SOURCE_ID] if id_col else [])):
            target, problem = _join(row, companies, ids, name_col, id_col, cache[sheet], ws)
            if problem:
                issues.append({"code": "link_cache_mismatch" if target else "unresolved_link",
                               "message": problem, "company_id": target,
                               "source": row.ref({NAME: "company_name", SOURCE_ID: "source_company_id"})})
            if target:
                children[sheet].append((target, row))
    return Book(path, sha256(path.read_bytes()).hexdigest(), companies, children, taxonomy, issues)

