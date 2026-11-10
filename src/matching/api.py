"""FastAPI v1 application and local static demo."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..pipeline import ROOT
from ..news_36kr import collect
from .company_repository import JsonCompanyRepository, detail, summary
from .models import (CompanyDetail, CompanyPage, HealthResponse, RecommendationRequest,
                     RecommendationResponse, TaxonomyResponse)
from .service import MatchingService
from .radar import router as radar_router
from .reference import reference_router
from .taxonomy_service import key

FRONTEND = ROOT / "frontend"


def create_app(config=None, repository=None, *, radar_collect=collect):
    config = config if config is not None else {**dotenv_values(ROOT / ".env"), **os.environ}

    @asynccontextmanager
    async def lifespan(app):
        path = Path(config.get("MATCH_DATA_DIR") or ROOT / "matching_data")
        if not path.is_absolute():
            path = ROOT / path
        app.state.service = MatchingService(repository if repository is not None else JsonCompanyRepository(path),
                                            config)
        yield

    app = FastAPI(title="Embodied AI Investment Matching Demo", version="1.0.0", lifespan=lifespan)
    news_path = Path(config.get("RADAR_NEWS_PATH") or ROOT / "news" / "36kr.json")
    if not news_path.is_absolute():
        news_path = ROOT / news_path
    app.include_router(radar_router(news_path, collector=radar_collect))
    app.include_router(reference_router())
    origins = [s.strip() for s in (config.get("MATCH_CORS_ORIGINS") or
                                   "http://localhost:5173,http://127.0.0.1:5173").split(",") if s.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)

    def service(request):
        return request.app.state.service

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health(request: Request):
        svc = service(request)
        return HealthResponse(status="ok", api_version="v1", company_count=svc.taxonomy.company_count,
                              preference_provider=svc.parser.provider, semantic_mode="lexical")

    @app.get("/api/v1/taxonomy", response_model=TaxonomyResponse)
    def taxonomy(request: Request):
        return service(request).taxonomy.view()

    @app.get("/api/v1/companies", response_model=CompanyPage)
    def companies(request: Request, offset: Annotated[int, Query(ge=0)] = 0,
                  limit: Annotated[int, Query(ge=1, le=100)] = 20,
                  sector: Annotated[str | None, Query(max_length=120)] = None,
                  q: Annotated[str | None, Query(max_length=120)] = None):
        svc = service(request)
        label = svc.taxonomy.sector(sector) if sector else None
        if sector and not label:
            raise HTTPException(422, detail="未知赛道，请先读取 taxonomy")
        rows = sorted(svc.repository.companies(), key=lambda c: key(c["name"]))
        if label:
            rows = [c for c in rows if label in c["sub_tracks"]]
        if q and q.strip():
            rows = [c for c in rows if key(q) in key(c["name"])]
        return CompanyPage(total=len(rows), offset=offset, limit=limit,
                           items=[summary(c, svc.repository) for c in rows[offset:offset + limit]])

    @app.get("/api/v1/companies/{company_id}", response_model=CompanyDetail)
    def company(request: Request, company_id: UUID):
        svc = service(request)
        value = svc.repository.get(str(company_id))
        if not value:
            raise HTTPException(404, detail="未找到该公司")
        return detail(value, svc.repository)

    @app.post("/api/v1/recommendations", response_model=RecommendationResponse)
    def recommendations(request: Request, body: RecommendationRequest):
        return service(request).recommend(body)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND / "radar.html", headers={"Cache-Control": "no-store"})

    @app.get("/company-matching", include_in_schema=False)
    def company_matching():
        return FileResponse(FRONTEND / "index.html")

    app.mount("/demo-assets", StaticFiles(directory=FRONTEND), name="demo-assets")
    return app


app = create_app()

