"""Optional, review-only Chat Completions integration. Mock never calls this module."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dotenv import dotenv_values

from .validate import ROOT, llm_evidence_errors, schema_errors

PROMPT_VERSION = "1.0"
PROMPT_PATH = ROOT / "prompts" / "extraction_prompt.txt"
ALLOWED_FIELDS = ("business_description", "products", "technology_routes", "funding_history",
                  "funding_stage", "valuation", "scope_notes")
PROVIDERS = {
    "deepseek": ("https://api.deepseek.com/chat/completions", "DEEPSEEK_API_KEY", "deepseek-chat"),
    "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", None),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url, headers, payload):
    """No redirects or automatic retries; avoid exposing credentials in errors."""
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=45) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"远端返回 HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("无法连接远端或请求超时；没有自动重试") from None


def suggest(companies, provider):
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    url, key_name, default_model = PROVIDERS[provider]
    key = (config.get(key_name) or "").strip()
    model = ((config.get("DEEPSEEK_MODEL") if provider == "deepseek" else config.get("OPENAI_MODEL"))
             or default_model or "").strip()
    if not key or not model:
        raise ValueError(f"LLM 模式需要 {key_name} 和有效的模型名；可改用默认 mock。")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    suggestions = []
    for company in companies:
        cells = company["provenance"]["cells"]
        excerpts = {k: cells.get(k, {}).get("raw_value") for k in ALLOWED_FIELDS}
        request = {"model": model, "messages": [{"role": "system", "content": prompt},
                   {"role": "user", "content": json.dumps(excerpts, ensure_ascii=False)}],
                   "response_format": {"type": "json_object"}}
        try:
            response = json.loads(post_json(url, {"Authorization": f"Bearer {key}"}, request))
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("response incomplete")
            result = json.loads(choice["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError(f"{company['name']}: LLM 返回空内容、截断内容或无效 JSON。") from None
        record = {"company_id": company["id"], "provider": provider, "model": model,
                  "prompt_version": PROMPT_VERSION, "result": result}
        if schema_errors(record, "llm_suggestion") or llm_evidence_errors(record, company):
            raise ValueError(f"{company['name']}: LLM 建议未通过结构或原文证据校验，未导出。")
        suggestions.append(record)
    return suggestions

