"""Application layer: compose parser, retrieval, ranking and session operations."""
import re
from uuid import uuid4

from .candidate_retriever import retrieve
from .company_repository import DATA_WARNING, FIT_WARNING
from .conversation import Session, Sessions
from .models import ParsedPreferences, RecommendationResponse
from .preference_parser import INDUSTRIAL, ONLY_INDUSTRIAL, PreferenceParser
from .ranking_engine import load_weights, rank
from .recommendation_generator import message, recommendation
from .semantic_matcher import LexicalMatcher
from .taxonomy_service import Taxonomy, key

EXPLAIN = re.compile(r"为什么|为何|why\b", re.I)
COMPARE = re.compile(r"对比|比较|\bcompare\b", re.I)
REFINE = re.compile(r"只(?:看|显示|保留|筛选)|筛掉|缩小范围|这些公司|刚才|上次|\bonly show\b|\bof those\b", re.I)


class MatchingService:
    def __init__(self, repository, config=None, matcher=None):
        self.repository = repository
        self.taxonomy = Taxonomy(repository)
        self.parser = PreferenceParser(self.taxonomy,
                                       {v for c in repository.companies() for v in c["historical_investors"]},
                                       config)
        self.matcher = matcher or LexicalMatcher()
        self.weights = load_weights((config or {}).get("MATCH_RANK_WEIGHTS"))
        self.sessions = Sessions()

    def recommend(self, request):
        old = self.sessions.get(request.session_id)
        sid = request.session_id if old else uuid4()
        industrial_follow_up = bool(INDUSTRIAL.search(request.query) and ONLY_INDUSTRIAL.search(request.query.strip()))
        action = request.action
        if action is None:
            action = ("explain" if EXPLAIN.search(request.query) else
                      "compare" if COMPARE.search(request.query) else
                      "refine" if request.session_id and (REFINE.search(request.query) or industrial_follow_up)
                      else "search")
        warnings = [DATA_WARNING, FIT_WARNING]
        if request.session_id and not old:
            warnings.append("上次会话已过期或不存在。")
        clarification, rows, count = None, [], 0
        mode = old.mode if old and action in {"explain", "compare"} else "fallback"
        prefs = (old.preferences.model_copy(update={"query": request.query})
                 if old and action in {"explain", "compare"} else ParsedPreferences(query=request.query))

        if action in {"explain", "compare", "refine"} and not old:
            clarification = "请先搜索一次，再对上次推荐进行筛选、解释或比较。"
        elif action == "compare":
            rows = list(old.results[:min(request.limit, 3)])
            count = len(rows)
            if not rows:
                clarification = "上次没有推荐结果。请先运行一次有结果的搜索。"
        elif action == "explain":
            selected = [r for r in old.results if r.company_id == request.company_id] if request.company_id else [
                r for r in old.results if key(r.company_name) in key(request.query)
                or key(re.split(r"[（(]", r.company_name, maxsplit=1)[0]) in key(request.query)]
            if not request.company_id and not selected:
                if re.search(r"第一|首个|\bfirst\b", request.query, re.I) or len(old.results) == 1:
                    selected = list(old.results[:1])
            if len(selected) != 1:
                clarification = "你想了解上次推荐中的哪一家公司？请提供公司名，或点击卡片上的「为什么推荐」。"
            else:
                rows, count = selected, 1
        else:
            previous = old.preferences if old and action == "refine" else None
            prefs, clarification, mode, extra = self.parser.parse(request, previous)
            warnings += extra
            if not clarification:
                scope = [str(r.company_id) for r in old.results] if previous and industrial_follow_up else None
                candidates = retrieve(self.repository, prefs, scope)
                count = len(candidates)
                rows = [recommendation(r, self.repository) for r in
                        rank(candidates, prefs, self.repository, self.matcher, self.weights)[:request.limit]]
                self.sessions.put(sid, Session(prefs, tuple(rows), mode))
        return RecommendationResponse(assistant_message=message(action, rows, count, clarification),
                                      parsed_preferences=prefs, results=rows, clarification_question=clarification,
                                      matching_mode=mode, data_warnings=warnings, session_id=sid,
                                      action=action, candidates_considered=count)

