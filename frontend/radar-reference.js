const labels = {
  zh: {
    title:"公司参考", sector:"选择赛道", browse:"查看完整目录", previous:"上一页", next:"下一页",
    separation:"资料来自 Excel 快照。关联按公司名或主题匹配，新闻日期筛选只作用于上方事件。",
    details:"公司资料", close:"关闭", all:"可多选 · 不选即不限赛道", selected: count => "已选 " + count + " 项",
    loading:"正在加载公司参考…",
    unavailable:"公司参考暂时无法读取。", empty:"原表里没有找到直接相关的公司。可以查看完整目录。",
    excel:"Excel 快照", review:"原表有待复核项", stage:"表内融资阶段", missing:"未提供",
    view:"查看资料", business_description:"主营业务", sub_tracks:"赛道", products:"产品",
    funding_stage:"表内融资阶段", website:"公司官网", sources:"原表关联来源",
    evidence:"Excel 单元格证据", topics:"关联主题",
    directory: (total, count) => total === count ? "共 " + count + " 家公司" : "当前赛道 " + total + " 家 · 全目录 " + count + " 家",
    related: (total, count) => "直接相关 " + total + " 家 · 全目录 " + count + " 家",
  },
  en: {
    title:"Company Reference", sector:"Choose sectors", browse:"Browse Full Directory", previous:"Previous", next:"Next",
    separation:"These profiles come from an Excel snapshot. Related companies are matched by name or topic. News date filters apply to the events above.",
    details:"Company Profile", close:"Close", all:"Select any sectors, or leave empty for all", selected: count => count + " selected",
    loading:"Loading company references…",
    unavailable:"Couldn't load the company references.", empty:"No directly related companies were found in the snapshot. Browse the full directory.",
    excel:"Excel snapshot", review:"Source has items to review", stage:"Funding stage in Excel", missing:"Not provided",
    view:"View Profile", business_description:"Business description", sub_tracks:"Sectors", products:"Products",
    funding_stage:"Funding stage in Excel", website:"Company Website", sources:"Sources listed in Excel",
    evidence:"Excel cell evidence", topics:"Related topics",
    directory: (total, count) => total === count ? count + " companies" : total + " in this sector · " + count + " in the directory",
    related: (total, count) => total + " directly related · " + count + " in the directory",
  }
};
const sectorLabels = {
  "灵巧手":"Dexterous hands","关节模组":"Joint modules","人形机器人本体":"Humanoid robots",
  "四足机器人":"Quadruped robots","机器人大脑（VLA、具身大模型）":"Robot intelligence (VLA & embodied models)",
  "机械臂（工业、协作）":"Robotic arms (industrial & collaborative)",
};

export function createCompanyReference(onSectorChange) {
  const $ = id => document.getElementById(id);
  const selector = $("reference-sector");
  const dialog = $("reference-dialog");
  const detailBody = $("reference-detail");
  const prev = $("reference-prev"), next = $("reference-next");
  const limit = 6;
  const state = {lang:"zh", sectors:[], selected:new Set(), q:"", offset:0, page:null, pending:true, failed:false, detail:null};
  let pageRequest = 0;
  let detailRequest = 0;
  const t = name => labels[state.lang][name] ?? name;

  function node(tag, value, cls) {
    const el = document.createElement(tag);
    el.textContent = value ?? "";
    if (cls) el.className = cls;
    return el;
  }
  function sectorLabel(value) {
    return state.lang === "en" ? sectorLabels[value] || value : value;
  }
  function link(url, caption, cls) {
    try {
      const target = new URL(url);
      if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) return null;
      const anchor = node("a", caption, cls);
      anchor.href = target.href; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
      return anchor;
    } catch { return null; }
  }
  async function get(path) {
    const response = await fetch("/api/v1" + path, {cache:"no-store"});
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }
  function renderOptions() {
    selector.replaceChildren(...state.sectors.map(value => {
      const label = node("label", "");
      const input = node("input", "");
      input.type = "checkbox"; input.value = value; input.checked = state.selected.has(value);
      label.append(input, node("span", sectorLabel(value)));
      return label;
    }));
    renderCount();
  }
  function renderCount() {
    $("reference-sector-count").textContent = state.selected.size ? t("selected")(state.selected.size) : t("all");
  }
  function card(company) {
    const article = node("article", "", "reference-card");
    const badge = node("span", t("excel"), "badge");
    const title = node("h3", company.company_name);
    const fields = node("p", [company.headquarters, company.funding_stage && t("stage") + " · " + company.funding_stage]
      .filter(Boolean).join("  /  "), "muted");
    const sectors = company.matched_topics.length ? company.matched_topics : company.sectors.slice(0, 3);
    const tags = node("div", "", "reference-tags");
    for (const sector of sectors) tags.append(node("span", sectorLabel(sector), "reference-tag"));
    const open = node("button", t("view") + " ↗", "pill");
    open.type = "button";
    open.addEventListener("click", () => void openDetail(company.company_id));
    article.append(badge, title, fields, tags, open);
    return article;
  }
  function render() {
    const page = state.page;
    const message = state.failed ? t("unavailable") : state.pending ? t("loading") : state.q
      ? t("related")(page.total, page.company_count) : t("directory")(page.total, page.company_count);
    $("reference-status").textContent = message;
    const cards = $("reference-list");
    if (state.pending || state.failed) cards.replaceChildren();
    else if (!page.items.length) cards.replaceChildren(node("p", t("empty"), "muted"));
    else cards.replaceChildren(...page.items.map(card));
    $("reference-browse").hidden = !state.q && !state.selected.size;
    const paginated = Boolean(page?.total > limit && !state.failed && !state.pending);
    $("reference-pager").hidden = !paginated;
    prev.disabled = !paginated || state.offset === 0;
    next.disabled = !paginated || state.offset + limit >= page.total;
    $("reference-range").textContent = paginated
      ? (state.offset + 1) + "–" + Math.min(state.offset + limit, page.total) + " / " + page.total : "";
  }
  async function loadPage() {
    const request = ++pageRequest;
    state.pending = true; state.failed = false; render();
    const params = new URLSearchParams({q:state.q, offset:state.offset, limit});
    for (const sector of state.selected) params.append("sectors", sector);
    try {
      const page = await get("/radar/references?" + params);
      if (request === pageRequest) state.page = page;
    } catch {
      if (request === pageRequest) state.failed = true;
    } finally {
      if (request === pageRequest) {state.pending = false;render();}
    }
  }
  function renderDetail() {
    if (!state.detail || state.detail === "error") {
      detailBody.replaceChildren(node("p", t(state.detail === "error" ? "unavailable" : "loading")));
      return;
    }
    const row = state.detail;
    const header = node("div","","reference-profile");
    header.append(node("span",t("excel"),"badge"),node("h3",row.company_name),
      node("p",[row.headquarters,t("stage") + " · " + (row.funding_stage || t("missing"))].filter(Boolean).join(" / "),"muted"));
    if (row.data_status === "needs_review") header.append(node("span",t("review"),"badge pending"));
    const site = row.website && link(row.website,t("website") + " ↗","button");
    if (site) header.append(site);
    const body = [header];
    if (row.business_description) body.push(node("h4",t("business_description")),node("p",row.business_description));
    for (const [field, items] of [["sub_tracks",row.sectors.map(sectorLabel)],["products",row.products]]) {
      if (items.length) body.push(node("h4",t(field)),node("p",items.join(" · ")));
    }
    if (row.excel_evidence.length) {
      const evidence = node("details","");
      evidence.append(node("summary",t("evidence")));
      for (const entry of row.excel_evidence) {
        const line = node("div","","reference-evidence");
        line.append(node("strong",t(entry.field)),node("p",entry.value),
          node("small",entry.workbook + " · " + entry.sheet + "!" + entry.cell,"muted"));
        evidence.append(line);
      }
      body.push(evidence);
    }
    const sources = node("ul","");
    for (const url of row.source_urls) {
      const anchor = link(url,url);
      if (anchor) {const item = node("li","");item.append(anchor);sources.append(item);}
    }
    if (sources.children.length) body.push(node("h4",t("sources")),sources);
    detailBody.replaceChildren(...body);
  }
  async function openDetail(id) {
    const request = ++detailRequest;
    state.detail = null; renderDetail();
    if (!dialog.open) dialog.showModal();
    try {
      const detail = await get("/radar/references/" + encodeURIComponent(id));
      if (request === detailRequest) state.detail = detail;
    } catch {
      if (request === detailRequest) state.detail = "error";
    }
    if (request === detailRequest) renderDetail();
  }
  selector.addEventListener("change", event => {
    const input = event.target;
    if (input.type !== "checkbox") return;
    if (input.checked) state.selected.add(input.value);
    else state.selected.delete(input.value);
    state.offset = 0;
    renderCount();
    onSectorChange();
    void loadPage();
  });
  $("reference-browse").addEventListener("click", () => {
    const hadSectors = state.selected.size > 0;
    state.q = "";state.selected.clear();state.offset = 0;renderOptions();
    if (hadSectors) onSectorChange();
    void loadPage();
  });
  prev.addEventListener("click", () => {if (!prev.disabled) {state.offset -= limit;void loadPage();}});
  next.addEventListener("click", () => {if (!next.disabled) {state.offset += limit;void loadPage();}});
  $("reference-close").addEventListener("click", () => dialog.close());
  void get("/taxonomy").then(data => {state.sectors = data.sectors;renderOptions();}).catch(() => {});
  void loadPage();
  return {
    setLanguage(lang) {
      state.lang = lang;
      document.querySelectorAll("[data-ref-i]").forEach(el => {el.textContent = t(el.dataset.refI);});
      renderOptions();render();
      if (dialog.open) renderDetail();
    },
    setQuery(q) {
      state.q = q.trim();state.offset = 0;void loadPage();
    },
    getSectors() {return [...state.selected];}
  };
}

