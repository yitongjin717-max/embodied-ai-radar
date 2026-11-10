import {createCompanyReference} from "./radar-reference.js?v=structure";

const copy = {
  zh: {
    brand:"具身项目雷达",radar:"项目雷达",news:"新闻工作台",hero:"匹配具身智能项目动态",
    subtitle:"从新品发布、原型展示和融资报道中找到与你关注条件相符的事件。",
    prompt:"你想找什么项目动态？",placeholder:"例如，今天哪家公司发布了新机器人？",
    type:"事件类型",auto:"自动识别",allKinds:"全部类型",launch:"产品发布",prototype:"原型展示",plan:"发布计划",funding:"融资",
    timeScope:"时间口径",allDates:"不限日期",eventDay:"按事件日期",reportDay:"按报道日期",date:"指定日期",find:"匹配动态",
    todayExample:"今天谁发布了新机器人？",recentExample:"最近有哪些原型展示？",latestExample:"查看最新采集批次",
    results:"匹配结果",reviewTitle:"待复核线索",reviewNote:"事件信息或日期尚不完整，按证据片段核对。",
    newsSub:"从 36氪官方文章 RSS 更新新闻，把可追溯的事件整理成表格。",
    collect:"采集与提取",csv:"下载事件表 CSV",refresh:"更新 36氪新闻",table:"结构化记录",events:"事件表",
    articles:"新闻候选",timeNote:"报道时间与事件时间分别记录。证据保留来源原文。",
    footer:"来源可查 · 原文证据 · 北京时间",
    freshness:"上次成功采集",noSnapshot:"暂无成功采集记录",loading:"正在读取数据…",loadError:"数据读取失败，请刷新页面重试。",
    jobIdle:"点击更新读取当前 RSS 窗口。",jobRunning:"正在采集、提取和校验…",jobDone:"更新成功",
    jobFailed:"本次更新失败，仍显示上次成功的数据。",cooldown:"更新间隔限制，稍后再试",
    searchBusy:"正在匹配…",searchError:"查询失败，请重试。",searchHint:"输入条件，或选择一个示例开始。",
    noResults:"当前已采集的报道中，没有能确认符合条件的事件。",
    supported:"原文有明确证据",review:"待复核",headline:"标题线索",original:"查看报道原文",
    unknown:"未确认",company:"项目方",product:"项目 / 产品",time:"事件时间",reported:"报道时间",
    evidence:"原文证据",state:"状态",source:"来源",article:"新闻标题",relevance:"相关性",
    primary:"主题初筛",mention:"顺带提及",scanned:"上批扫描",newCount:"上批新增",records:"累计事件",pending:"待复核",
    noRows:"当前快照没有这一类记录。",dateUnclear:"事件日期待确认",headlineOnly:"只有标题线索，需核对正文",
    structured:"结构化新闻",structure:"一键结构化",structureCsv:"下载结构化新闻 CSV",anyNews:"全部候选",
    articleOnly:"未提取到明确事件",structureBusy:"正在提取所选新闻…",structureError:"提取失败，请重试。",
    structureEmpty:"点击「一键结构化」生成当前筛选的新闻表。",
    candidates: count => "当前筛选 " + count + " 篇新闻",
    structuredCount: (articles, events) => "已处理 " + articles + " 篇 · 提取 " + events + " 条事件或线索",
    archivedOnly: count => count + " 篇旧记录使用已保存的证据",
    narrowNews:"请缩小报道日期或相关性范围，每批最多处理 1,000 篇。",
  },
  en: {
    brand:"Embodied AI Project Radar",radar:"Project Radar",news:"News Workbench",hero:"Find relevant project events",
    subtitle:"Explore reported launches, prototype demonstrations and funding events in embodied AI.",
    prompt:"What project events are you looking for?",placeholder:"For example, who launched a new robot today?",
    type:"Event type",auto:"Detect automatically",allKinds:"All event types",launch:"Product launch",prototype:"Prototype demo",plan:"Launch plan",funding:"Funding",
    timeScope:"Date basis",allDates:"Any date",eventDay:"By event date",reportDay:"By publication date",date:"Specific date",find:"Find Events",
    todayExample:"Who launched a new robot today?",recentExample:"Show recent prototype demos",latestExample:"Show the latest batch",
    results:"Matching events",reviewTitle:"Needs review",reviewNote:"Some event details or dates remain unconfirmed. Check the source excerpt.",
    newsSub:"Refresh 36Kr's official article RSS and review the extracted events with source links.",
    collect:"Collect and extract",csv:"Download Events CSV",refresh:"Refresh 36Kr News",table:"Structured records",events:"Events",
    articles:"Candidate articles",timeNote:"Publication time and event time are tracked separately. Evidence stays in the source language.",
    footer:"Source links · Original evidence · Beijing time",
    freshness:"Last successful refresh",noSnapshot:"No successful refresh yet",loading:"Loading data…",loadError:"Couldn't load the data. Refresh the page to retry.",
    jobIdle:"Refresh to read the current RSS window.",jobRunning:"Collecting, extracting and validating…",jobDone:"Refresh completed",
    jobFailed:"This refresh failed. The last successful data is still shown.",cooldown:"Refresh limit reached. Try again shortly.",
    searchBusy:"Searching…",searchError:"Search failed. Please try again.",searchHint:"Enter a query or choose an example.",
    noResults:"The collected reports contain no confirmed events that meet these criteria.",
    supported:"Explicit source evidence",review:"Needs review",headline:"Headline lead",original:"View Original Article",
    unknown:"Unconfirmed",company:"Reported organization",product:"Project / product",time:"Event time",reported:"Published",
    evidence:"Original evidence",state:"Status",source:"Source",article:"Headline",relevance:"Relevance",
    primary:"Primary topic",mention:"Passing mention",scanned:"Last batch scanned",newCount:"New in last batch",records:"Events on file",pending:"Needs review",
    noRows:"No records of this type in the current snapshot.",dateUnclear:"Event date unconfirmed",headlineOnly:"Headline lead only. Check the article.",
    structured:"Structured news",structure:"Structure Selected News",structureCsv:"Download Structured News CSV",anyNews:"All candidates",
    articleOnly:"No explicit event extracted",structureBusy:"Extracting the selected articles…",structureError:"Extraction failed. Please try again.",
    structureEmpty:"Select Structure Selected News to generate this table.",
    candidates: count => count + " articles match the filters",
    structuredCount: (articles, events) => articles + " articles processed · " + events + " events or leads extracted",
    archivedOnly: count => count + " older records used their saved evidence",
    narrowNews:"Narrow the filters to process up to 1,000 articles at once.",
  }
};
const $ = id => document.getElementById(id);
const model = {lang:"zh", view:"radar", table:"events", snapshot:null, answer:null, queryState:"idle", jobState:null};
const structureState = {focus:"all", day:"", result:null, busy:false, error:false};
try { if (localStorage.getItem("embodied-radar-lang") === "en") model.lang = "en"; } catch { /* Optional preference. */ }
const t = key => copy[model.lang][key] ?? key;
const queryBox = $("radar-query");
const companyReference = createCompanyReference(() => {
  model.answer = null;
  renderSearch();
});
let watching = false;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function el(name, value, cls) {
  const node = document.createElement(name);
  node.textContent = value ?? "";
  if (cls) node.className = cls;
  return node;
}
function urlLink(raw, label) {
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.hostname !== "www.36kr.com" || url.username || url.password) {
      return el("span", label);
    }
    const a = el("a", label);
    a.href = url.href; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  } catch { return el("span", label); }
}
function clock(value) {
  if (!value) return t("unknown");
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return t("unknown");
  return new Intl.DateTimeFormat(model.lang === "zh" ? "zh-CN" : "en-GB",
    {timeZone:"Asia/Shanghai",dateStyle:"medium",timeStyle:"short",hour12:false}).format(timestamp);
}
function eventTime(row) {
  if (row.event_date) return row.event_date;
  return row.time_text ? row.time_text + " · " + t("dateUnclear") : t("unknown");
}
function stateLabel(row) {
  if (row.status === "article_only") return t("articleOnly");
  return t(row.review_reason === "headline_only" ? "headline" : row.status === "supported" ? "supported" : "review");
}
function api(path, body) {
  const options = body === undefined ? {cache:"no-store"} : {
    method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)
  };
  return fetch("/api/v1/radar" + path, options).then(response => {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  });
}

function eventCard(row) {
  const card = el("article", "", "event");
  const top = el("div", "", "event-head");
  const title = [row.product, row.subject].filter(Boolean).join(" · ") || t("unknown");
  top.append(el("h3", title), el("span", t(row.kind), "badge"),
    el("span", stateLabel(row), "badge" + (row.status === "supported" ? "" : " pending")));
  const meta = el("div", "", "event-meta");
  meta.append(el("span", t("time") + " · " + eventTime(row)), el("span", t("reported") + " · " + clock(row.published_at)));
  card.append(top, meta, el("blockquote", row.evidence), urlLink(row.source_url, t("original") + " ↗"));
  return card;
}

function renderSearch() {
  $("radar-submit").disabled = model.queryState === "busy";
  const result = model.answer;
  const progress = model.queryState;
  const confirmed = $("radar-results"), review = $("radar-review");
  if (!result) {
    $("radar-result-note").textContent = progress === "error" ? t("searchError") :
      progress === "busy" ? t("searchBusy") : "";
    confirmed.replaceChildren(el("p", t("searchHint"), "empty"));
    review.hidden = true;
    return;
  }
  const scope = result.scope === "all" ? t("allDates") :
    t(result.scope === "event" ? "eventDay" : "reportDay") + " · " +
      (result.from === result.to ? result.from : result.from + " – " + result.to);
  $("radar-result-note").textContent = (progress === "busy" ? t("searchBusy") :
    progress === "error" ? t("searchError") : scope);
  confirmed.replaceChildren(...(result.results.length ? result.results.map(eventCard) : [el("p", t("noResults"), "empty")]));
  review.hidden = !result.review.length;
  $("radar-review-cards").replaceChildren(...result.review.map(eventCard));
}

function reportDay(value) {
  const instant = new Date(value);
  if (!value || Number.isNaN(instant.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en", {timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"})
    .formatToParts(instant);
  const get = name => parts.find(part => part.type === name).value;
  return [get("year"),get("month"),get("day")].join("-");
}

function filteredArticles() {
  return (model.snapshot?.articles ?? []).filter(row =>
    (structureState.focus === "all" || row.topic_focus === structureState.focus) &&
    (!structureState.day || reportDay(row.published_at) === structureState.day));
}

function renderNews() {
  const snap = model.snapshot;
  const freshness = snap?.fetched_at ? t("freshness") + " · " + clock(snap.fetched_at) : t("noSnapshot");
  $("radar-freshness").textContent = freshness;
  $("news-freshness").textContent = freshness;
  const job = model.jobState ?? snap?.refresh?.status ?? "idle";
  $("news-refresh").disabled = job === "running" || job === "loading";
  const jobLabel = {idle:"jobIdle",running:"jobRunning",loading:"loading",failed:"jobFailed",
    succeeded:"jobDone",cooldown:"cooldown",unavailable:"loadError"}[job];
  $("news-job").textContent = t(jobLabel || "jobIdle");
  const batch = snap?.last_batch;
  const metrics = [["scanned",batch?.scanned],["newCount",batch?.new],
    ["records",snap?.events.length],["pending",snap?.events.filter(e => e.status !== "supported").length]];
  $("news-metrics").replaceChildren(...metrics.map(([label,value]) => {
    const metric = el("div","","metric");
    metric.append(el("span",t(label)),el("strong",String(value ?? "—")));
    return metric;
  }));

  const articles = model.table === "articles", structured = model.table === "structured";
  const candidates = filteredArticles();
  const generated = structureState.result;
  $("news-structure").disabled = structureState.busy || job === "running" || job === "loading" ||
    !candidates.length || candidates.length > 1000;
  $("news-focus").disabled = structureState.busy;
  $("news-day").disabled = structureState.busy;
  $("news-structure-export").hidden = !structured || !generated?.rows.length;
  $("news-structure-note").textContent = structureState.error ? t("structureError") :
    structureState.busy ? t("structureBusy") : candidates.length > 1000 ? t("narrowNews") :
      structured && generated ? [t("structuredCount")(generated.article_count,generated.event_count),
        generated.archived_only && t("archivedOnly")(generated.archived_only)].filter(Boolean).join(" · ") :
        t("candidates")(candidates.length);
  const headers = articles ? ["article","relevance","reported","source"] :
    [...(structured ? ["article"] : []),"product","company","type","time","reported","state","evidence","source"];
  const head = el("tr","");
  for (const h of headers) {
    const th = el("th",t(h)); th.scope = "col"; head.append(th);
  }
  $("news-head").replaceChildren(head);
  $("news-head").closest("table").classList.toggle("structured-table", structured);
  const rows = (articles ? candidates : structured ? generated?.rows : snap?.events) ?? [];
  const body = rows.map(row => {
    const tr = el("tr","");
    if (articles) {
      tr.append(el("td",row.title),el("td",t(row.topic_focus === "primary" ? "primary" : "mention")),el("td",clock(row.published_at)));
    } else {
      if (structured) tr.append(el("td",row.article_title));
      for (const value of [row.product ?? t("unknown"),row.subject ?? t("unknown"),row.kind ? t(row.kind) : "—",
        eventTime(row),clock(row.published_at),stateLabel(row),row.evidence]) tr.append(el("td",value));
    }
    const source = el("td","");
    source.append(urlLink(articles ? row.url : row.source_url, t("original")));
    tr.append(source);
    return tr;
  });
  if (!body.length) {
    const row = el("tr",""), cell = el("td",t(structured && !generated ? "structureEmpty" : "noRows"));
    cell.colSpan = headers.length; row.append(cell); body.push(row);
  }
  $("news-body").replaceChildren(...body);
  document.querySelectorAll("[data-table]").forEach(button =>
    button.setAttribute("aria-pressed",String(button.dataset.table === model.table)));
}

async function structureNews() {
  const urls = filteredArticles().map(row => row.url);
  if (structureState.busy || !urls.length || urls.length > 1000) return;
  structureState.busy = true; structureState.error = false; renderNews();
  try {
    structureState.result = await api("/structure",{urls});
    model.table = "structured";
  } catch {structureState.error = true;}
  finally {structureState.busy = false;renderNews();}
}

function exportStructuredNews() {
  if (!structureState.result) return;
  const columns = ["article_title","subject","product","kind","event_date","time_text","published_at",
    "status","evidence","source_url"];
  const csv = value => {
    let text = String(value ?? "");
    if (/^[=+@-]/.test(text.trimStart())) text = "'" + text;
    return '"' + text.replaceAll('"','""') + '"';
  };
  const lines = [columns.join(","), ...structureState.result.rows.map(row =>
    columns.map(column => csv(row[column])).join(","))];
  const href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n")],{type:"text/csv;charset=utf-8"}));
  const anchor = el("a","");
  anchor.href = href; anchor.download = "structured-news.csv";
  document.body.append(anchor);anchor.click();anchor.remove();
  setTimeout(() => URL.revokeObjectURL(href),1000);
}

function renderLanguage() {
  document.documentElement.lang = model.lang === "zh" ? "zh-CN" : "en";
  document.title = t("brand");
  document.querySelectorAll("[data-i]").forEach(node => { node.textContent = t(node.dataset.i); });
  document.querySelectorAll("[data-placeholder]").forEach(node => { node.placeholder = t(node.dataset.placeholder); });
  document.querySelectorAll("[data-lang]").forEach(button =>
    button.setAttribute("aria-pressed",String(button.dataset.lang === model.lang)));
  renderSearch();
  renderNews();
  companyReference.setLanguage(model.lang);
}
function view(name) {
  model.view = name;
  $("view-radar").hidden = name !== "radar";
  $("view-news").hidden = name !== "news";
  document.querySelectorAll("[data-view]").forEach(button =>
    button.setAttribute("aria-pressed",String(button.dataset.view === name)));
}
async function loadSnapshot() {
  model.snapshot = await api("/snapshot");
  renderNews();
}
async function pollRefresh() {
  if (watching) return;
  watching = true;
  try {
    for (let i = 0; i < 60; i++) {
      await loadSnapshot();
      const state = model.snapshot.refresh.status;
      if (state !== "running") {
        model.jobState = state;
        if (state === "succeeded" && model.answer) await search();
        return;
      }
      await wait(1000);
    }
    model.jobState = "unavailable";
  } catch { model.jobState = "unavailable"; }
  finally { watching = false; renderNews(); }
}
async function refresh() {
  if (watching || model.jobState === "running" || model.jobState === "loading") return;
  model.jobState = "loading";
  renderNews();
  try {
    const job = await api("/refresh", {});
    model.jobState = job.retry_after ? "cooldown" : job.status;
    if (job.status === "running") await pollRefresh();
  } catch { model.jobState = "unavailable"; }
  finally { renderNews(); }
}
const form = $("radar-form");
const field = name => form.querySelector('[name="' + name + '"]');
async function search() {
  if (model.queryState === "busy") return;
  model.queryState = "busy";
  const query = queryBox.value;
  const sectors = companyReference.getSectors();
  renderSearch();
  try {
    const answer = await api("/search",{query,kind:field("kind").value,
      scope:field("scope").value,day:field("day").value || null,sectors});
    if (JSON.stringify(sectors) === JSON.stringify(companyReference.getSectors())) {
      model.answer = answer;
      model.queryState = "ready";
      companyReference.setQuery(query);
    } else {
      model.queryState = "idle";
    }
  } catch { model.queryState = "error"; }
  renderSearch();
}

document.querySelectorAll("[data-lang]").forEach(button => button.addEventListener("click",() => {
  model.lang = button.dataset.lang;
  try { localStorage.setItem("embodied-radar-lang",model.lang); } catch { /* Optional preference. */ }
  renderLanguage();
}));
document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click",() => view(button.dataset.view)));
document.querySelectorAll("[data-table]").forEach(button => button.addEventListener("click",() => {model.table = button.dataset.table; renderNews();}));
document.querySelectorAll("[data-example]").forEach(button => button.addEventListener("click",() => {
  const choice = button.dataset.example;
  if (choice === "latest") {view("news");return;}
  field("kind").value = choice === "today" ? "launch" : "prototype";
  field("scope").value = "event";
  field("day").value = "";
  queryBox.value = t(choice === "today" ? "todayExample" : "recentExample");
  void search();
}));
form.addEventListener("submit",event => {event.preventDefault();void search();});
$("news-refresh").addEventListener("click",() => void refresh());
$("news-structure").addEventListener("click",() => void structureNews());
$("news-structure-export").addEventListener("click",exportStructuredNews);
for (const [id, key] of [["news-focus","focus"],["news-day","day"]]) {
  $(id).addEventListener("change", () => {
    structureState[key] = $(id).value;
    structureState.result = null; structureState.error = false;
    model.table = "articles"; renderNews();
  });
}
renderLanguage();
loadSnapshot().then(() => {
  if (model.snapshot.refresh.status === "running") {
    model.jobState = "running";
    void pollRefresh();
  }
}).catch(() => {model.jobState = "unavailable";renderNews();});

