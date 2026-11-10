import {api, element, renderCard, renderDetail} from "./components.js";

const byId = id => document.getElementById(id);
const form = byId("search");
const chips = byId("sectors");
const query = byId("query");
const submit = byId("submit");
const compare = byId("compare");
const chat = byId("chat");
const cards = byId("cards");
const status = byId("status");
const dialog = byId("detail");
const resultNote = byId("result-note");
const empty = byId("empty-results");
let sessionId = null;
let ready = false;
let busy = false;
let hasResults = false;
let companyCount = 0;

function buttons() {
  submit.disabled = !ready || busy;
  compare.disabled = busy || !sessionId || !hasResults;
  byId("reset").disabled = busy;
  byId("example").disabled = !ready || busy;
  form.setAttribute("aria-busy", String(busy));
  cards.closest(".results").setAttribute("aria-busy", String(busy));
}

function selection() {
  return Array.from(chips.querySelectorAll("input"), input => input)
    .filter(input => input.checked).map(input => input.value);
}

function selectionCount() {
  const count = selection().length;
  byId("selection-count").textContent = count ? "已选 " + count + " 项" : "可多选";
}

function addChat(speaker, text) {
  const turn = element("div", "", "turn");
  turn.append(element("small", speaker), element("p", text));
  chat.append(turn);
  byId("turn-count").textContent = chat.children.length + " 条";
  chat.scrollTop = chat.scrollHeight;
}

function note(text) {
  resultNote.textContent = text;
  resultNote.hidden = !text;
}

function showEmpty(title, copy) {
  empty.querySelector("h3").textContent = title;
  empty.querySelector("p").textContent = copy;
  empty.hidden = false;
}

async function openDetail(companyId) {
  const body = byId("detail-body");
  body.replaceChildren(element("p", "正在读取公司资料…"));
  if (!dialog.open) dialog.showModal();
  try {
    const company = await api("/companies/" + encodeURIComponent(companyId));
    body.replaceChildren(renderDetail(company));
  } catch (error) {
    body.replaceChildren(element("p", error.message));
  }
}

async function send(text, action, companyId) {
  if (busy) return;
  busy = true;
  buttons();
  const sectors = selection();
  addChat("你", text || sectors.join("、") || "搜索");
  status.textContent = "正在匹配…";
  try {
    const body = {query: text, selected_sectors: sectors, limit: 5, session_id: sessionId};
    if (action) body.action = action;
    if (companyId) body.company_id = companyId;
    const response = await api("/recommendations", {method: "POST", body: JSON.stringify(body)});
    sessionId = response.session_id;
    addChat("助手", response.assistant_message);
    byId("warnings").replaceChildren(...response.data_warnings.map(w => element("p", w)));
    if (response.clarification_question) {
      note(response.clarification_question);
    } else {
      const followup = response.action === "compare" || response.action === "explain";
      note(followup ? response.assistant_message
        : "硬筛后 " + response.candidates_considered + " 家 · 本次显示 " + response.results.length + " 家");
      cards.replaceChildren(...response.results.map((result, index) => renderCard(result, {
        detail: () => openDetail(result.company_id),
        explain: () => send("为什么推荐" + result.company_name + "？", "explain", result.company_id)
      }, index === 0)));
      if (response.results.length) empty.hidden = true;
      else showEmpty("暂无符合条件的公司", "试着减少必选条件，或更换关注赛道。");
      if (!followup) hasResults = Boolean(response.results.length);
    }
    const mode = response.matching_mode === "fallback" ? "本地规则" : "DeepSeek + 本地规则";
    status.textContent = companyCount + " 家公司 · " + mode;
  } catch (error) {
    addChat("提示", error.message);
    note(error.message);
    status.textContent = "请求失败";
  } finally {
    busy = false;
    buttons();
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  void send(query.value.trim());
});
chips.addEventListener("change", selectionCount);
compare.addEventListener("click", () => send("对比前三家公司", "compare"));
byId("example").addEventListener("click", () => {
  const exampleSectors = new Set(["灵巧手", "关节模组"]);
  for (const input of chips.querySelectorAll("input")) input.checked = exampleSectors.has(input.value);
  selectionCount();
  query.value = "只看 A 轮及以前的公司，优先考虑有产业资本参与的公司";
  query.focus();
});
byId("reset").addEventListener("click", () => {
  sessionId = null;
  hasResults = false;
  query.value = "";
  for (const input of chips.querySelectorAll("input")) input.checked = false;
  selectionCount();
  chat.replaceChildren();
  byId("turn-count").textContent = "";
  cards.replaceChildren();
  byId("warnings").replaceChildren();
  note("");
  showEmpty("开始一次搜索", "选择赛道、输入偏好，或用示例查看匹配明细。");
  status.textContent = ready ? companyCount + " 家公司 · 已就绪" : "数据尚未载入";
  buttons();
});
byId("close-detail").addEventListener("click", () => dialog.close());

async function init() {
  try {
    const taxonomy = await api("/taxonomy");
    for (const name of taxonomy.sectors) {
      const label = element("label", "");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = name;
      label.append(input, document.createTextNode(name));
      chips.append(label);
    }
    companyCount = taxonomy.company_count;
    status.textContent = companyCount + " 家公司 · 已就绪";
    ready = true;
  } catch (error) {
    status.textContent = "数据载入失败";
    note(error.message);
  }
  buttons();
}

void init();
