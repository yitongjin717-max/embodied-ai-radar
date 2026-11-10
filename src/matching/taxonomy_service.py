"""Vocabulary from the exported Excel taxonomy; aliases only resolve existing labels."""
import re
import unicodedata

from .models import TaxonomyResponse

STAGE_ORDER = ("Unfunded", "Seed", "Angel", "Angel+", "Pre-A", "Pre-A+", "A", "A+",
               "Pre-B", "B", "B+", "Pre-C", "C", "C+", "Pre-D", "D", "D+", "E+", "IPO", "Listed")
OTHER_STAGES = ("Strategic", "Undisclosed")
EARLY_STAGES = ("Seed", "Angel", "Angel+", "Pre-A", "Pre-A+", "A")
STAGE_ALIASES = {"未融资": "Unfunded", "种子": "Seed", "天使": "Angel", "天使+": "Angel+",
                 "上市": "Listed", "战略投资": "Strategic", "战略融资": "Strategic",
                 "股权融资(轮次未披露)": "Undisclosed", "轮次未披露": "Undisclosed",
                 "E轮及以后": "E+", "E及以后": "E+"}
ENGLISH_SECTORS = {
    "dexterous hand": "灵巧手", "dexterous hands": "灵巧手", "robotic hand": "灵巧手",
    "joint module": "关节模组", "joint modules": "关节模组",
    "humanoid robot": "人形机器人本体", "humanoid robots": "人形机器人本体",
    "quadruped": "四足机器人", "quadrupeds": "四足机器人",
    "robot brain": "机器人大脑（VLA、具身大模型）", "robotic arm": "机械臂（工业、协作）",
    "灵巧手部件": "灵巧手", "关节模块": "关节模组", "人形机器人": "人形机器人本体",
}
ENGLISH_GEO = {"china": "中国", "beijing": "北京", "shanghai": "上海", "shenzhen": "深圳",
               "hangzhou": "杭州", "suzhou": "苏州", "wuxi": "无锡", "dongguan": "东莞"}


def key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def stage(value):
    if not value:
        return None
    token = unicodedata.normalize("NFKC", value).strip()
    if token in STAGE_ALIASES:
        return STAGE_ALIASES[token]
    token = re.sub(r"^series\s+", "", token, flags=re.I)
    # Parenthetical qualifiers and compound stages are ambiguous; do not guess.
    token = re.sub(r"轮$", "", token)
    if token in STAGE_ALIASES:
        return STAGE_ALIASES[token]
    for label in (*STAGE_ORDER, *OTHER_STAGES):
        if key(label) == key(token):
            return label
    if m := re.fullmatch(r"(Pre-)?([A-D])(?:\++|\d+)", token, re.I):
        return (("Pre-" if m[1] else "") + m[2].upper() + "+") if not m[1] or m[2].upper() == "A" else None
    return None


def hq_tokens(value):
    # Stop at scope notes: registration, factories or financing entities are not HQ.
    primary = re.split(r"[（(;；]", value or "", maxsplit=1)[0]
    return [p.strip() for p in primary.split("/") if p.strip()]


def mentioned(alias, text):
    pattern = re.escape(key(alias))
    if alias.isascii():
        pattern = r"(?<![\w-])" + pattern + r"(?![\w-])"
    return re.search(pattern, text) is not None


class Taxonomy:
    def __init__(self, repository):
        self.sectors = repository.labels("sub_tracks")
        self.applications = repository.labels("application_scenarios")
        self.technologies = repository.labels("technology_routes")
        self.geography = sorted({token for c in repository.companies() for token in hq_tokens(c["headquarters"])})
        self.company_count = len(repository.companies())

    def view(self):
        return TaxonomyResponse(sectors=self.sectors, applications=self.applications,
                                technologies=self.technologies, geography=self.geography,
                                funding_stages=list(STAGE_ORDER + OTHER_STAGES), company_count=self.company_count)

    def sector(self, value):
        exact = next((v for v in self.sectors if key(v) == key(value)), None)
        alias = ENGLISH_SECTORS.get(key(value))
        return exact or (alias if alias in self.sectors else None)

    def place(self, value):
        normalized = ENGLISH_GEO.get(key(value), value.strip())
        return next((v for v in self.geography if key(v) == key(normalized)), None)

    def matches(self, query, group):
        text = key(query)
        if group == "sectors":
            aliases = {**{label: label for label in self.sectors}, **ENGLISH_SECTORS}
            aliases = {a: l for a, l in aliases.items() if l in self.sectors}
        elif group == "technologies":
            aliases = {label: label for label in self.technologies}
            for label in self.technologies:
                short = label.partition("】")[2]
                if short:
                    aliases.setdefault(short, label)
            if "【大脑层】VLA端到端" in self.technologies:
                aliases["VLA"] = "【大脑层】VLA端到端"
        elif group == "geography":
            aliases = {**{label: label for label in self.geography}, **ENGLISH_GEO}
            aliases = {a: l for a, l in aliases.items() if l in self.geography}
        else:
            aliases = {label: label for label in self.applications}
        return list(dict.fromkeys(label for alias, label in aliases.items() if mentioned(alias, text)))

