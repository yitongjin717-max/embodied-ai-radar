"""Versioned HTTP request/response types."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Mode = Literal["fallback", "deepseek+fallback"]
SectorMode = Literal["any", "all"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filters(Contract):
    funding_stages: list[Label] = Field(default_factory=list, max_length=20)
    max_funding_stage: Label | None = None
    geography: list[Label] = Field(default_factory=list, max_length=20)
    required_applications: list[Label] = Field(default_factory=list, max_length=20)
    required_technologies: list[Label] = Field(default_factory=list, max_length=30)
    required_investors: list[Label] = Field(default_factory=list, max_length=20)
    require_industrial_investors: bool = False
    sector_match: SectorMode = "any"


class RecommendationRequest(Contract):
    query: str = Field(default="", max_length=1200)
    selected_sectors: list[Label] = Field(default_factory=list, max_length=20)
    filters: Filters = Field(default_factory=Filters)
    limit: int = Field(default=5, ge=1, le=20)
    session_id: UUID | None = None
    company_id: UUID | None = None
    action: Literal["search", "refine", "explain", "compare"] | None = None


class ParsedPreferences(Contract):
    query: str
    selected_sectors: list[str] = Field(default_factory=list)
    target_sectors: list[str] = Field(default_factory=list)
    target_applications: list[str] = Field(default_factory=list)
    target_technologies: list[str] = Field(default_factory=list)
    funding_stages: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    preferred_investors: list[str] = Field(default_factory=list)
    prefer_industrial_investors: bool = False
    prefer_technical_barriers: bool = False
    must_have: Filters = Field(default_factory=Filters)
    nice_to_have: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class Evidence(Contract):
    criterion: str
    field: str
    evidence: str
    workbook: str
    sheet: str
    cell: str
    kind: Literal["hard_filter", "preference", "corroboration"] = "preference"


class ScoreFactor(Contract):
    key: str
    label: str
    earned: float = Field(ge=0)
    weight: float = Field(gt=0)
    status: Literal["matched", "partial", "not_matched", "missing_evidence"]


class ScoreBreakdown(Contract):
    earned: float = Field(ge=0)
    possible: float = Field(ge=0)
    factors: list[ScoreFactor]


class CompanySummary(Contract):
    company_id: UUID
    company_name: str
    headquarters: str | None
    sectors: list[str]
    funding_stage: str | None
    data_status: Literal["excel_only", "needs_review"]


class CompanyPage(Contract):
    total: int
    offset: int
    limit: int
    items: list[CompanySummary]


class FundingSummary(Contract):
    round_name: str | None
    amount_text: str | None
    date_text: str | None
    needs_review: bool


class CompanyDetail(CompanySummary):
    website: str | None
    business_description: str | None
    products: list[str]
    technologies: list[str]
    applications: list[str]
    funding_events: list[FundingSummary]
    source_urls: list[str]
    data_warnings: list[str]


class Recommendation(CompanySummary):
    fit_score: int = Field(ge=0, le=100)
    score_breakdown: ScoreBreakdown | None = None
    matched_sectors: list[str]
    matched_technologies: list[str]
    matching_reasons: list[Evidence]
    unmet_preferences: list[str]
    missing_information: list[str]
    source_urls: list[str]


class RecommendationResponse(Contract):
    assistant_message: str
    parsed_preferences: ParsedPreferences
    results: list[Recommendation]
    clarification_question: str | None
    matching_mode: Mode
    data_warnings: list[str]
    session_id: UUID
    action: Literal["search", "refine", "explain", "compare"]
    candidates_considered: int = Field(ge=0)


class TaxonomyResponse(Contract):
    sectors: list[str]
    applications: list[str]
    technologies: list[str]
    funding_stages: list[str]
    geography: list[str]
    company_count: int


class HealthResponse(Contract):
    status: Literal["ok"]
    api_version: Literal["v1"]
    company_count: int
    preference_provider: Literal["fallback", "deepseek"]
    semantic_mode: Literal["lexical"]

