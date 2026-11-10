"""Repository interface and local validated JSON snapshot implementation."""
from collections import defaultdict
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from ..supabase_client import load_import
from .models import CompanyDetail, CompanySummary, FundingSummary
from .taxonomy_service import hq_tokens

DATA_WARNING = "数据来自 Excel 快照，未独立核验；融资阶段、投资者及其他披露可能不完整或过时。"
FIT_WARNING = "分数衡量本次查询的相对匹配度，不是投资成功概率。"


class CompanyRepository(Protocol):
    def companies(self) -> list[dict]: ...
    def get(self, company_id: str) -> dict | None: ...
    def labels(self, group: str) -> list[str]: ...
    def funding(self, company_id: str) -> list[dict]: ...
    def urls(self, company_id: str) -> list[str]: ...
    def status(self, company_id: str) -> str: ...


def safe_url(value):
    try:
        parsed = urlsplit(value or "")
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and not parsed.username and not parsed.password)
    except ValueError:
        return False


class JsonCompanyRepository:
    def __init__(self, directory: Path):
        import json
        data = load_import(directory)
        self._companies = {c["id"]: c for c in data["companies"]}
        if not self._companies or len(self._companies) != len(data["companies"]):
            raise ValueError("公司数据为空或存在重复 ID")
        self._labels = defaultdict(list)
        self._funding = defaultdict(list)
        self._urls = defaultdict(list)
        for row in data["taxonomy"]:
            self._labels[row["field"]].append(row["label"])
        for row in data["funding_events"]:
            self._funding[row["company_id"]].append(row)
        for row in data["sources"]:
            if safe_url(row["url"]):
                self._urls[row["company_id"]].append(row["url"])
        report = json.loads((directory / "validation_report.json").read_text(encoding="utf-8"))
        self._reviews = {row["company_id"] for row in report["reviews"]}

    def companies(self):
        return list(self._companies.values())

    def get(self, company_id):
        return self._companies.get(company_id)

    def labels(self, group):
        return sorted(set(self._labels[group]))

    def funding(self, company_id):
        return self._funding[company_id]

    def urls(self, company_id):
        return self._urls[company_id]

    def status(self, company_id):
        return "needs_review" if company_id in self._reviews else "excel_only"


def summary(company, repository):
    return CompanySummary(company_id=company["id"], company_name=company["name"],
                          headquarters=" / ".join(hq_tokens(company["headquarters"])) or None,
                          sectors=company["sub_tracks"], funding_stage=company["funding_stage"],
                          data_status=repository.status(company["id"]))


def detail(company, repository):
    cid = company["id"]
    rows = [FundingSummary.model_validate({k: event[k] for k in FundingSummary.model_fields})
            for event in repository.funding(cid)]
    return CompanyDetail(**summary(company, repository).model_dump(),
                         website=company["website"] if safe_url(company["website"]) else None,
                         business_description=company["business_description"],
                         products=company["products"], technologies=company["technology_routes"],
                         applications=company["application_scenarios"], funding_events=rows,
                         source_urls=repository.urls(cid), data_warnings=[DATA_WARNING])

