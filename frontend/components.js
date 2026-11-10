export async function api(path, options = {}) {
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers: options.body ? {"Content-Type": "application/json"} : undefined
  });
  if (!response.ok) throw new Error("API 请求失败（HTTP " + response.status + "）。");
  return response.json();
}

export function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function list(items) {
  const ul = element("ul", "");
  ul.append(...items.map(text => element("li", text)));
  return ul;
}

function button(text, action, className) {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

const statuses = {partial: "部分命中", not_matched: "未命中", missing_evidence: "证据不足"};
const reasonKinds = {hard_filter: "硬条件", preference: "偏好命中", corroboration: "交叉核对"};
const points = value => Number(value.toFixed(2)).toString();

function renderScoring(breakdown) {
  if (!breakdown) return null;
  const section = element("div", "", "scoring");
  if (!breakdown.possible) {
    section.append(element("p", "本次只核对硬条件，结果通过筛选。", "score-note"));
    return section;
  }
  section.append(element("p", "本次权重得分 " + points(breakdown.earned) + " / " +
    points(breakdown.possible), "score-note"));
  const list = element("ul", "", "factor-list");
  for (const factor of breakdown.factors) {
    const label = [factor.label, statuses[factor.status]].filter(Boolean).join(" · ");
    const row = element("li", "", "factor");
    row.append(element("span", label), element("strong", points(factor.earned) + " / " + points(factor.weight)));
    list.append(row);
  }
  section.append(list);
  return section;
}

export function renderCard(result, actions, expanded = false) {
  const node = element("article", "", "card");
  const top = element("div", "", "card-top");
  const identity = element("div", "");
  identity.append(element("h3", result.company_name),
    element("p", [result.headquarters, result.funding_stage || "融资阶段未提供"].filter(Boolean).join(" · "), "company-meta"));
  const score = element("div", "", "score");
  if (result.score_breakdown?.possible === 0) {
    score.append(element("strong", "通过"), element("small", "硬条件"));
  } else {
    score.append(element("strong", result.fit_score.toString()), element("small", "匹配度 / 100"));
  }
  top.append(identity, score);
  const tags = element("div", "", "tags");
  const review = result.data_status === "needs_review";
  tags.append(element("span", review ? "待复核" : "Excel 记录", review ? "badge review" : "badge"));
  for (const tag of [...result.matched_sectors, ...result.matched_technologies]) {
    tags.append(element("span", tag, "tag"));
  }
  node.append(top, tags);
  const scoring = renderScoring(result.score_breakdown);
  if (scoring || result.matching_reasons.length) {
    const details = element("details", "");
    details.open = expanded;
    details.append(element("summary", "匹配理由与原表证据 · " + result.matching_reasons.length + " 条"));
    if (scoring) details.append(scoring);
    const ul = element("ul", "", "evidence-list");
    for (const reason of result.matching_reasons) {
      const row = element("li", "", "evidence");
      row.append(element("strong", reason.criterion), element("blockquote", reason.evidence),
        element("small", [reasonKinds[reason.kind], reason.workbook, reason.sheet + "!" + reason.cell]
          .filter(Boolean).join(" · ")));
      ul.append(row);
    }
    details.append(ul);
    node.append(details);
  }
  if (result.unmet_preferences.length || result.missing_information.length) {
    const gaps = element("details", "");
    gaps.append(element("summary", "未命中与资料缺口"));
    if (result.unmet_preferences.length) gaps.append(element("p", "未命中 · " + result.unmet_preferences.join("、"), "data-note"));
    if (result.missing_information.length) gaps.append(element("p", "缺少证据 · " + result.missing_information.join("、"), "data-note"));
    node.append(gaps);
  }
  const row = element("div", "", "card-actions");
  row.append(button("公司详情", actions.detail, "button secondary"), button("为什么推荐", actions.explain, "text-button"));
  node.append(row);
  return node;
}

export function renderDetail(company) {
  const panel = element("section", "");
  panel.append(element("h2", company.company_name), element("p", company.headquarters || "总部未提供"),
               element("p", company.business_description || "主营业务未提供"),
               element("h3", "产品"), list(company.products),
               element("h3", "融资原表记录"), list(company.funding_events.map(event =>
                 [event.round_name, event.date_text, event.amount_text].map(v => v || "未提供").join(" · ")
                 + (event.needs_review ? " · 待复核" : ""))),
               element("h3", "原表来源"));
  const sources = element("ul", "");
  for (const value of company.source_urls) {
    try {
      const url = new URL(value);
      if (!["http:", "https:"].includes(url.protocol)) continue;
      const anchor = element("a", url.hostname);
      anchor.href = url.href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      const row = element("li", "");
      row.append(anchor);
      sources.append(row);
    } catch { /* URL 不合法时不生成链接 */ }
  }
  panel.append(sources, ...company.data_warnings.map(text => element("p", text, "warning")));
  return panel;
}

