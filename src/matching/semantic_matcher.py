"""Explainable local semantic approximation; interchangeable with embeddings later."""
from dataclasses import dataclass
import re
from typing import Protocol

from .taxonomy_service import key


@dataclass(frozen=True)
class TextMatch:
    score: float
    field: str
    term: str
    partial: bool


class SemanticMatcher(Protocol):
    def match(self, company: dict, terms: list[str]) -> TextMatch | None: ...


class LexicalMatcher:
    """Exact term and bounded Chinese character-pair matching on business fields."""
    def match(self, company, terms):
        matches = []
        for field in ("business_description", "products", "technology_routes", "application_scenarios"):
            values = company[field]
            for value in values if isinstance(values, list) else [values or ""]:
                haystack = key(value)
                for term in terms:
                    needle = key(term)
                    exact = (bool(re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack))
                             if needle.isascii() else needle in haystack)
                    if exact:
                        matches.append(TextMatch(1.0, field, term, False))
                    elif len(needle) >= 5 and re.fullmatch(r"[\u3400-\u9fff]+", needle):
                        pairs = {needle[i:i + 2] for i in range(len(needle) - 1)}
                        hits = [pair for pair in pairs if pair in haystack and pair not in {"机器", "器人", "智能"}]
                        if len(hits) >= 2 and len(hits) / len(pairs) >= 0.5:
                            matches.append(TextMatch(0.6 * len(hits) / len(pairs), field, sorted(hits)[0], True))
        return max(matches, key=lambda m: m.score, default=None)

