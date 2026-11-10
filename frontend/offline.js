/* Browser-side matching for the self-contained HTML export. */
const demoSessions = new Map();
let demoSessionCount = 0;
const normalize = value => (value || "").normalize("NFKC").trim().toLowerCase();
const unique = values => [...new Set(values)];
const roundToken = "(?:pre-)?[a-d](?:\\+|\\d+)?";
const stageLimit = new RegExp("(" + roundToken + ")\\s*轮?\\s*(?:及以前|及以下|以前|以下|或更早|之前|or earlier|or below)", "i");
const prefixLimit = new RegExp("(?:不超过|至多|最高|at most|up to)\\s*(?:series\\s+)?(" + roundToken + ")\\s*轮?", "i");
const explicit = /只(?:看|选|要|找|保留|显示)|仅|必须|要求|限定|\b(?:only|must|require)\b/i;
const industrialText = /产业资本|产业投资方|产业方|industrial (?:capital|investor)/i;
const exclude = /排除|不要|不含|不包括|除外|\b(?:exclude|without|except)\b/i;
const topics = [
  ["application", "应用场景", "applications", "application_scenarios"],
  ["technology", "技术路线", "technologies", "technology_routes"],
];

function canonicalStage(raw) {
  const match = /^(pre-)?([a-d])(\+|\d+)?$/i.exec(raw);
  return match ? (match[1] ? "Pre-" : "") + match[2].toUpperCase() + (match[3] ? "+" : "") : null;
}

function mention(text, list, aliases = {}) {
  const allowed = new Set(list);
  const matches = list.filter(value => text.includes(normalize(value)));
  for (const [alias, value] of Object.entries(aliases)) {
    if (allowed.has(value) && text.includes(normalize(alias))) matches.push(value);
  }
  return unique(matches);
}

function combineFilter(previous, current) {
  if (!previous.length || !current.length) return previous.length ? previous : current;
  const result = previous.filter(value => current.includes(value));
  if (!result.length) throw new Error("新旧筛选条件没有交集。可点「新会话」重新搜索。");
  return result;
}

function parseDemo(request, prior) {
  const tax = offlineData.taxonomy;
  const pref = prior ? structuredClone(prior) : {
    sectors: [], targets: [], allSectors: false, ceiling: null, exact: [], preferredStages: [],
    places: [], preferredPlaces: [], industrial: false, industrialRequired: false,
    application: [], technology: [], required: {application: [], technology: []}, text: [],
  };
  if (request.selected_sectors?.length) pref.sectors = request.selected_sectors;
  const clauses = normalize(request.query).split(/[，,。；;!?！？\n]|[.](?:\s|$)/).filter(Boolean);
  for (const clause of clauses) {
    const hard = explicit.test(clause);
    const sectors = mention(clause, tax.sectors, offlineData.sector_aliases);
    const places = mention(clause, tax.geography, offlineData.place_aliases);
    const sectorTopics = topics.map(([id, , list]) => [id, mention(clause, tax[list],
      id === "technology" ? Object.fromEntries(tax[list].map(label => [label.replace(/^【[^】]+】/, ""), label])) : {})]);
    const bound = stageLimit.exec(clause) || prefixLimit.exec(clause);
    const boundStage = bound ? canonicalStage(bound[1]) : null;
    const exactStage = new RegExp("(?:series\\s+(" + roundToken + ")(?![a-z0-9+])|(" + roundToken + ")\\s*轮)", "i").exec(clause);
    const exact = exactStage && canonicalStage(exactStage[1] || exactStage[2]);
    const early = /早期|early[ -]stage/i.test(clause);
    const industry = industrialText.test(clause);
    const found = Boolean(sectors.length || places.length || boundStage || exact || early || industry ||
      sectorTopics.some(([, matches]) => matches.length));
    if (exclude.test(clause) || (hard && (!found || /营收|员工|估值|出货|专利|注册地|至少|以后|revenue|valuation|technical barriers/i.test(clause) ||
        (!places.length && /总部|位于|based in|headquartered in/i.test(clause)))) ||
        (boundStage && !tax.funding_stages.includes(boundStage))) {
      throw new Error("这个筛选条件在离线版无法可靠识别。可用赛道选项、总部地区或明确的融资阶段重试。");
    }
    if (hard && sectors.length) {
      if (pref.sectors.length && (pref.sectors.length !== sectors.length || !pref.sectors.every(v => sectors.includes(v)))) {
        throw new Error("文字与已选赛道不同。请统一赛道，再补充筛选条件。");
      }
      pref.sectors = sectors;
      pref.allSectors ||= sectors.length > 1 && /同时|并且|都要|\band\b/i.test(clause);
    } else pref.targets.push(...sectors);
    if (boundStage) {
      if (!pref.ceiling || tax.funding_stages.indexOf(boundStage) < tax.funding_stages.indexOf(pref.ceiling)) pref.ceiling = boundStage;
    } else {
      const stages = exact ? [exact] : early ? offlineData.early : [];
      if (hard) pref.exact = combineFilter(pref.exact, stages);
      else pref.preferredStages.push(...stages);
    }
    if (hard) pref.places = combineFilter(pref.places, places);
    else pref.preferredPlaces.push(...places);
    for (const [id, matches] of sectorTopics) {
      (hard ? pref.required[id] : pref[id]).push(...matches);
    }
    if (industry) {
      if (hard || /^(?:哪些|哪家|which)/i.test(clause)) pref.industrialRequired = true;
      else pref.industrial = true;
    }
    if (!found && !hard) {
      const phrase = clause.replace(/^(?:我想找|想找|帮我找|查一下|请推荐|推荐|搜索)\s*/, "")
        .replace(/(?:的公司|的企业|相关公司)$/, "").trim();
      if (phrase.length >= 2 && !/^(?:你好|谢谢|随便|继续|公司|hello|help)$/.test(phrase)) pref.text.push(phrase);
    }
  }
  for (const name of ["targets", "preferredStages", "preferredPlaces", "application", "technology", "text"]) {
    pref[name] = unique(pref[name]);
  }
  return pref;
}

function acceptable(record, pref) {
  const d = record.detail;
  if (pref.sectors.length && !(pref.allSectors ? pref.sectors.every(v => d.sectors.includes(v))
    : pref.sectors.some(v => d.sectors.includes(v)))) return false;
  if (pref.ceiling && !record.eligible_ceilings.includes(pref.ceiling)) return false;
  if (pref.exact.length && (!pref.exact.includes(record.stage) || !record.eligible_ceilings.includes(record.stage))) return false;
  if (pref.places.length && !pref.places.some(v => record.places.includes(v))) return false;
  if (pref.industrialRequired && !record.industrial_evidence) return false;
  return topics.every(([id, , field]) => pref.required[id].every(value => d[field].includes(value)));
}

function scoreDemo(record, pref) {
  const d = record.detail;
  const factors = [], reasons = [], unmet = [], missing = [];
  function score(key, label, coverage, absent = false) {
    const weight = offlineData.weights[key];
    factors.push({key, label, weight, earned: coverage * weight,
      status: absent ? "missing_evidence" : coverage === 1 ? "matched" : coverage ? "partial" : "not_matched"});
  }
  function cite(criterion, field, kind = "preference", evidence = record.evidence[field]) {
    if (evidence) reasons.push({...evidence, criterion, kind});
  }
  function group(id, label, values, target, required, field) {
    const hits = target.filter(value => values.includes(value));
    if (target.length) {
      score(id, label, hits.length / target.length, !values.length);
      if (!values.length) missing.push(label);
      else if (hits.length < target.length) unmet.push(label + "未命中 " + target.filter(v => !hits.includes(v)).join("、"));
    }
    for (const hit of unique([...required, ...hits])) {
      cite(label + "命中 · " + hit, field, required.includes(hit) ? "hard_filter" : "preference");
    }
    return unique([...hits, ...required]);
  }
  const sectors = group("sector", "赛道覆盖", d.sectors, unique([...pref.sectors, ...pref.targets]),
    pref.sectors.filter(value => d.sectors.includes(value)), "sub_tracks");
  let technologies = [];
  for (const [id, label, field, evidenceField] of topics) {
    const hits = group(id, label, d[field], pref[id], pref.required[id], evidenceField);
    if (id === "technology") technologies = hits;
  }
  if (pref.preferredStages.length) {
    const credible = record.eligible_ceilings.includes(record.stage);
    const hit = credible && pref.preferredStages.includes(record.stage);
    score("stage", "融资偏好", Number(hit), !credible);
    if (hit) cite("融资偏好命中 · " + d.funding_stage, "funding_stage");
    else if (credible) unmet.push("融资阶段不在偏好范围");
    else missing.push("可比较的融资阶段");
  }
  if (pref.ceiling || pref.exact.length) {
    cite("融资条件通过 · " + (pref.ceiling ? "上限 " + pref.ceiling : pref.exact.join(" / ")), "funding_stage", "hard_filter");
    cite("融资历史交叉核对", "funding_history", "corroboration", record.round_evidence);
  }
  if (pref.preferredPlaces.length) {
    const hits = pref.preferredPlaces.filter(place => record.places.includes(place));
    score("geography", "总部地区", Number(Boolean(hits.length)), !record.places.length);
    if (hits.length) cite("总部偏好命中 · " + hits.join("、"), "headquarters");
    else if (record.places.length) unmet.push("总部不在偏好地区");
    else missing.push("总部地区");
  }
  if (pref.places.length) cite("总部条件通过 · " + pref.places.find(v => record.places.includes(v)), "headquarters", "hard_filter");
  if (pref.industrial || pref.industrialRequired) {
    const evidence = record.industrial_evidence;
    if (pref.industrial) score("industrial", "产业投资方", Number(Boolean(evidence)), !evidence);
    if (evidence) cite("融资原文明确提到产业方", "funding_history", pref.industrialRequired ? "hard_filter" : "preference", evidence);
    else missing.push("明确的产业投资方证据");
  }
  if (pref.text.length) {
    let hits = 0;
    for (const term of pref.text) {
      const field = ["business_description", "products", "application_scenarios", "technology_routes"]
        .find(key => normalize(record.evidence[key]?.evidence).includes(term));
      if (field) {
        hits++;
        cite("原文词语命中 · " + term, field);
      } else unmet.push("业务文本未命中 " + term);
    }
    score("business_text", "业务文本", hits / pref.text.length);
  }
  const earned = factors.reduce((sum, f) => sum + f.earned, 0);
  const possible = factors.reduce((sum, f) => sum + f.weight, 0);
  const ratio = possible ? earned / possible : 1;
  const {company_id, company_name, headquarters, funding_stage, data_status, source_urls} = d;
  return {ratio, row: {company_id, company_name, headquarters, funding_stage, data_status, source_urls,
    fit_score: Math.round(ratio * 100), score_breakdown: {earned, possible, factors},
    matched_sectors: sectors, matched_technologies: technologies, matching_reasons: reasons,
    unmet_preferences: unique(unmet), missing_information: unique(missing)}};
}

function recommendDemo(request) {
  const query = request.query || "";
  const old = demoSessions.get(request.session_id);
  const id = old ? request.session_id : "offline-" + ++demoSessionCount;
  const action = request.action || (/为什么|为何|\bwhy\b/i.test(query) ? "explain"
    : /对比|比较|\bcompare\b/i.test(query) ? "compare"
    : old && /只看|只保留|这些公司|哪些公司有产业|\bonly show\b/i.test(query) ? "refine" : "search");
  const base = {session_id: id, action, matching_mode: "fallback", data_warnings: offlineData.warnings,
    clarification_question: null, results: [], candidates_considered: 0};
  const clarify = message => ({...base, clarification_question: message, assistant_message: message});
  if (action === "explain" || action === "compare") {
    if (!old?.rows.length) return clarify("请先搜索一次，再查看理由或比较结果。");
    const matches = action === "compare" ? old.rows.slice(0, 3) : old.rows.filter((row, index) =>
      request.company_id ? row.company_id === request.company_id
        : query.includes(row.company_name) || (index === 0 && (old.rows.length === 1 || /第一|first/i.test(query))));
    if (!matches.length) return clarify("请点选具体公司卡片上的「为什么推荐」。");
    const lines = matches.map(row => row.company_name + " · " + (row.funding_stage || "阶段未提供") +
      " · " + (row.score_breakdown.possible ? row.fit_score + " 分" : "通过硬条件"));
    return {...base, results: matches, candidates_considered: matches.length,
      assistant_message: action === "compare" ? "以下按上次结果对比\n" + lines.join("\n")
        : matches[0].company_name + "的匹配依据已展开，可查看分项得分和原表证据。"};
  }
  let pref;
  try { pref = parseDemo(request, action === "refine" ? old?.pref : null); }
  catch (error) { return clarify(error.message); }
  const hard = Boolean(pref.sectors.length || pref.places.length || pref.ceiling || pref.exact.length ||
    pref.industrialRequired || topics.some(([key]) => pref.required[key].length));
  const soft = pref.targets.length || pref.preferredStages.length || pref.preferredPlaces.length ||
    pref.industrial || pref.text.length || topics.some(([key]) => pref[key].length);
  if (!hard && !soft) return clarify("请选择一个赛道，或输入想查询的行业、融资阶段和业务关键词。");
  const candidates = offlineData.records.filter(record => acceptable(record, pref));
  const rows = candidates.map(record => scoreDemo(record, pref)).filter(result => hard || result.ratio > 0)
    .sort((a, b) => b.ratio - a.ratio || b.row.matched_sectors.length - a.row.matched_sectors.length ||
      a.row.company_name.localeCompare(b.row.company_name, "zh-CN"))
    .slice(0, request.limit || 5).map(result => result.row);
  demoSessions.set(id, {pref, rows});
  if (demoSessions.size > 20) demoSessions.delete(demoSessions.keys().next().value);
  return {...base, results: rows, candidates_considered: candidates.length,
    assistant_message: rows.length ? "已完成本地匹配，可查看分数和原表证据。"
      : "这份 Excel 快照中没有找到符合条件的公司。"};
}

async function api(path, options = {}) {
  if (path === "/taxonomy") return offlineData.taxonomy;
  if (path === "/recommendations") return recommendDemo(JSON.parse(options.body));
  if (path.startsWith("/companies/")) {
    const id = decodeURIComponent(path.slice("/companies/".length));
    const record = offlineData.records.find(record => record.detail.company_id === id);
    if (record) return record.detail;
  }
  throw new Error("没有找到这条离线数据。");
}

