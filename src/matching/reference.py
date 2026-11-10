"""Browse the Excel company snapshot beside project events."""
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from .company_repository import detail, summary
from .taxonomy_service import key, mentioned

TOPIC_FIELDS = {"sectors": "sub_tracks", "applications": "application_scenarios",
                "technologies": "technology_routes"}
EVIDENCE_FIELDS = ("business_description", "sub_tracks", "funding_stage", "website")


def name_forms(name):
    """The displayed name and its explicit aliases from the spreadsheet."""
    parts = re.split(r"[()（）]", name)
    return [part.strip() for part in parts if len(part.strip()) >= (4 if part.strip().isascii() else 2)]


def reference_page(service, query, sectors, offset, limit):
    companies = service.repository.companies()
    vocabulary = service.taxonomy
    labels = {vocabulary.sector(sector) for sector in sectors}
    if None in labels:
        raise HTTPException(422, detail="unknown_sector")

    text = key(query)
    topics = {field: set(vocabulary.matches(query, group))
              for group, field in TOPIC_FIELDS.items()} if text else {}
    ranked = []
    for company in companies:
        selected = labels.intersection(company["sub_tracks"])
        if labels and not selected:
            continue
        hits = [value for field, requested in topics.items()
                for value in company[field] if value in requested]
        names = name_forms(company["name"])
        name_hit = bool(text and (any(mentioned(name, text) for name in names) or
                                 (len(text) >= 2 and text in key(company["name"]))))
        if text and not (name_hit or hits or selected):
            continue
        ranked.append((name_hit, [*hits, *(value for value in company["sub_tracks"] if value in selected)], company))
    ranked.sort(key=lambda row: (-row[0], -len(row[1]), key(row[2]["name"])))
    return {"company_count": len(companies), "total": len(ranked),
            "items": [{**summary(company, service.repository).model_dump(),
                       "matched_topics": list(dict.fromkeys(hits))}
                      for _, hits, company in ranked[offset:offset + limit]]}


def reference_router():
    router = APIRouter(prefix="/api/v1/radar/references", tags=["company reference"])

    @router.get("")
    def list_references(
        request: Request,
        q: Annotated[str, Query(max_length=240)] = "",
        sector: Annotated[str, Query(max_length=120)] = "",
        sectors: Annotated[list[str] | None, Query(max_length=30)] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=30)] = 6,
    ):
        selected = [*(sectors or []), *([sector] if sector else [])]
        return reference_page(request.app.state.service, q, selected, offset, limit)

    @router.get("/{company_id}")
    def reference_detail(request: Request, company_id: UUID):
        repository = request.app.state.service.repository
        company = repository.get(str(company_id))
        if company is None:
            raise HTTPException(404, detail="unknown_company")
        origin = company["provenance"]
        evidence = []
        for field in EVIDENCE_FIELDS:
            cell = origin["cells"].get(field)
            if cell and cell["raw_value"]:
                evidence.append({"field": field, "value": cell["raw_value"],
                                 "workbook": origin["workbook"], "sheet": origin["sheet"],
                                 "cell": cell["coordinate"]})
        return {**detail(company, repository).model_dump(), "excel_evidence": evidence}

    return router

