const STORAGE_ACTIVE_RUN = "steps-agent.activeRunId";
const MAX_EVENT_CARDS = 200;
const MAX_GRAPH_EVENTS = 300;

const state = {
  source: null,
  activeRunId: localStorage.getItem(STORAGE_ACTIVE_RUN) || "",
  activeRunStatus: "",
  events: [],
  llmText: "",
  plan: null,
  planInput: "",
  renderedEventKeys: new Set(),
};

const $ = (selector) => document.querySelector(selector);
const elements = {
  form: $("#runForm"),
  prompt: $("#promptInput"),
  model: $("#modelSelect"),
  mode: $("#modeSelect"),
  autoRepair: $("#autoRepair"),
  repairAttempts: $("#repairAttempts"),
  runButton: $("#runButton"),
  planButton: $("#planButton"),
  executePlanButton: $("#executePlanButton"),
  reconnectButton: $("#reconnectButton"),
  duplicateButton: $("#duplicateButton"),
  newSessionInput: $("#newSessionInput"),
  newSessionButton: $("#newSessionButton"),
  formModeHint: $("#formModeHint"),
  refreshMeta: $("#refreshMeta"),
  refreshHistory: $("#refreshHistory"),
  statusDot: $("#statusDot"),
  statusText: $("#statusText"),
  statusHint: $("#statusHint"),
  skillsList: $("#skillsList"),
  historyList: $("#historyList"),
  stream: $("#streamOutput"),
  plan: $("#planOutput"),
  events: $("#eventsOutput"),
  final: $("#finalOutput"),
  planGraph: $("#planGraph"),
  eventGraph: $("#eventGraph"),
};

function payload() {
  return {
    input: elements.prompt.value.trim(),
    mode: elements.mode.value,
    model: elements.model.value || null,
    auto_repair: elements.autoRepair.checked,
    max_repair_attempts: Number(elements.repairAttempts.value || 0),
  };
}

function setStatus(kind, text, hint = "") {
  elements.statusDot.className = `dot ${kind || ""}`.trim();
  elements.statusText.textContent = text;
  elements.statusHint.textContent = hint;
}

function pretty(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function setPlanDraft(plan, input = "") {
  state.plan = Array.isArray(plan) && plan.length ? plan : null;
  state.planInput = state.plan ? input : "";
  elements.plan.value = state.plan ? pretty(state.plan) : "暂无 Plan";
  elements.plan.classList.toggle("empty", !state.plan);
  renderPlanGraph(state.plan || []);
  updateEditorMode();
}

function readPlanDraft() {
  if (!elements.plan.value.trim() || elements.plan.classList.contains("empty")) return null;
  const parsed = JSON.parse(elements.plan.value);
  if (!Array.isArray(parsed) || !parsed.length) throw new Error("Plan 必须是非空 JSON 数组");
  return parsed;
}

function resetOutputs() {
  state.events = [];
  state.llmText = "";
  state.plan = null;
  state.planInput = "";
  state.renderedEventKeys = new Set();
  elements.stream.textContent = "运行后，模型输出会显示在这里。";
  elements.plan.value = "暂无 Plan";
  elements.events.textContent = "暂无事件";
  elements.final.textContent = "暂无最终结果";
  elements.planGraph.textContent = "暂无 Plan";
  elements.eventGraph.textContent = "暂无事件";
  [elements.stream, elements.plan, elements.events, elements.final, elements.planGraph, elements.eventGraph].forEach((el) =>
    el.classList.add("empty"),
  );
}

function setBusy(isBusy) {
  elements.form.dataset.busy = isBusy ? "true" : "";
  updateEditorMode();
}

function isPlanCurrent() {
  return Boolean(state.plan) && state.planInput === elements.prompt.value.trim();
}

function isRunView() {
  return Boolean(state.activeRunId);
}

function canReconnectRun() {
  return isRunView() && !state.source && !["done", "error"].includes(state.activeRunStatus);
}

function canDuplicateRun() {
  return isRunView() && !state.source;
}

function updateEditorMode() {
  const busy = elements.form.dataset.busy === "true";
  const runView = isRunView();
  const planCurrent = isPlanCurrent();
  elements.prompt.readOnly = runView;
  elements.runButton.disabled = busy || runView;
  elements.planButton.disabled = busy || runView;
  elements.executePlanButton.disabled = busy || runView || !planCurrent;
  elements.plan.readOnly = runView || !planCurrent;
  elements.reconnectButton.disabled = busy || !canReconnectRun();
  elements.duplicateButton.disabled = busy || !canDuplicateRun();
  elements.reconnectButton.classList.toggle("hidden", !runView);
  elements.duplicateButton.classList.toggle("hidden", !runView);
  elements.runButton.classList.toggle("hidden", runView);
  elements.planButton.classList.toggle("hidden", runView);
  elements.executePlanButton.classList.toggle("hidden", runView || !planCurrent);
  if (!runView && state.plan && !planCurrent) elements.formModeHint.textContent = "输入已变更，请重新规划";
  else if (!runView && state.plan) elements.formModeHint.textContent = "规划待确认，可在 Plan 阶段编辑 JSON 后执行";
  else if (!runView) elements.formModeHint.textContent = "编辑新任务";
  else if (state.source) elements.formModeHint.textContent = "正在连接原始任务，历史输入只读";
  else if (state.activeRunStatus === "done") elements.formModeHint.textContent = "历史会话已完成，输入只读";
  else if (state.activeRunStatus === "error") elements.formModeHint.textContent = "历史会话已异常，输入只读";
  else elements.formModeHint.textContent = "历史会话只读，可重新连接原始任务";
}

function newSessionPayload() {
  return {
    input: elements.newSessionInput.value.trim(),
    mode: elements.mode.value,
    model: elements.model.value || null,
    auto_repair: elements.autoRepair.checked,
    max_repair_attempts: Number(elements.repairAttempts.value || 0),
  };
}

function setActiveRun(runId) {
  state.activeRunId = runId;
  if (runId) localStorage.setItem(STORAGE_ACTIVE_RUN, runId);
  else localStorage.removeItem(STORAGE_ACTIVE_RUN);
  if (!runId) state.activeRunStatus = "";
  updateHistorySelection();
  updateEditorMode();
}

function updateHistorySelection() {
  elements.historyList.querySelectorAll(".history-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.runId === state.activeRunId);
  });
}

function appendStream(text) {
  if (elements.stream.classList.contains("empty")) {
    elements.stream.textContent = "";
    elements.stream.classList.remove("empty");
  }
  elements.stream.textContent += text;
  elements.stream.scrollTop = elements.stream.scrollHeight;
}

function eventKey(event) {
  return event.index != null ? `i:${event.index}` : `${event.type}:${event.timestamp || ""}:${state.events.length}`;
}

function ingestEvent(event) {
  const key = eventKey(event);
  if (state.renderedEventKeys.has(key)) return false;
  state.renderedEventKeys.add(key);
  state.events.push(event);
  return true;
}

function appendEventCard(event, { trim = true } = {}) {
  elements.events.classList.remove("empty");
  if (elements.events.classList.contains("empty") || state.events.length === 1) elements.events.textContent = "";
  if (trim && elements.events.children.length >= MAX_EVENT_CARDS) elements.events.firstElementChild?.remove();

  const item = document.createElement("article");
  item.className = `event ${event.type || ""}`;
  const title = document.createElement("strong");
  title.textContent = event.step_id ? `${event.type} / step ${event.step_id}` : event.type;
  const body = document.createElement("pre");
  body.textContent = pretty(event);
  item.append(title, body);
  elements.events.appendChild(item);
  elements.events.scrollTop = elements.events.scrollHeight;
}

function renderPlanGraph(plan) {
  elements.planGraph.classList.remove("empty");
  elements.planGraph.textContent = "";
  const steps = Array.isArray(plan) ? plan : [];
  if (!steps.length) {
    elements.planGraph.textContent = "暂无 Plan";
    elements.planGraph.classList.add("empty");
    return;
  }
  for (const step of steps) {
    const node = document.createElement("div");
    node.className = `graph-node ${step.type || ""}`;
    node.innerHTML = `
      <span class="node-id">#${escapeHtml(step.step_id || "?")}</span>
      <strong>${escapeHtml(step.type || "")}${step.tool_id ? ` · ${escapeHtml(step.tool_id)}` : ""}</strong>
      <small>${escapeHtml(step.prompt || step.description || JSON.stringify(step.params || {})).slice(0, 160)}</small>
    `;
    elements.planGraph.appendChild(node);
  }
}

function renderEventGraph() {
  elements.eventGraph.classList.remove("empty");
  elements.eventGraph.textContent = "";
  if (!state.events.length) {
    elements.eventGraph.textContent = "暂无事件";
    elements.eventGraph.classList.add("empty");
    return;
  }

  const hidden = Math.max(0, state.events.length - MAX_GRAPH_EVENTS);
  if (hidden) {
    const notice = document.createElement("div");
    notice.className = "timeline-row";
    notice.innerHTML = `<span></span><span class="timeline-type">省略</span><span class="timeline-detail">已隐藏较早的 ${hidden} 个事件，保留最近 ${MAX_GRAPH_EVENTS} 个</span>`;
    elements.eventGraph.appendChild(notice);
  }

  for (const event of state.events.slice(-MAX_GRAPH_EVENTS)) {
    const row = document.createElement("div");
    row.className = `timeline-row ${event.type || ""}`;
    row.innerHTML = `
      <span class="timeline-dot"></span>
      <span class="timeline-type">${escapeHtml(event.type || "")}</span>
      <span class="timeline-detail">${escapeHtml(event.step_id ? `step ${event.step_id}` : event.content || event.message || "")}</span>
    `;
    elements.eventGraph.appendChild(row);
  }
}

function applyEventEffects(event, { appendCard = true, renderGraph = true } = {}) {
  if (appendCard) appendEventCard(event);
  if (event.type === "thinking") appendStream(`\n${event.content}\n`);
  if (event.type === "plan_generated") {
    setPlanDraft(event.plan, elements.prompt.value.trim());
  }
  if (event.type === "tool_invoke") appendStream(`\n调用工具：${event.tool_id}\n`);
  if (event.type === "tool_result") {
    const success = event.result && event.result.success !== false;
    appendStream(`${success ? "完成" : "失败"}：${event.tool_id}\n`);
  }
  if (event.type === "repair_attempt") appendStream(`尝试自动修复 step ${event.step_id} 参数...\n`);
  if (event.type === "llm") {
    state.llmText += event.content || "";
    elements.stream.textContent = state.llmText;
    elements.stream.classList.remove("empty");
  }
  if (event.type === "error") {
    state.activeRunStatus = "error";
    appendStream(`\n错误：${event.message || event.error || "未知错误"}\n`);
    setStatus("error", "出错", event.message || event.error || "请查看事件详情");
  }
  if (event.type === "done") {
    state.activeRunStatus = "done";
    elements.final.textContent = pretty(event.final_result || "");
    elements.final.classList.remove("empty");
    setStatus("ok", "完成", "任务已结束");
    setBusy(false);
    closeSubscription(false);
    loadHistory();
  }
  if (renderGraph) renderEventGraph();
}

function renderEvent(event) {
  if (!ingestEvent(event)) return;
  applyEventEffects(event);
}

function renderEventBatch(events) {
  const uniqueEvents = [];
  for (const event of events || []) {
    if (ingestEvent(event)) uniqueEvents.push(event);
  }
  elements.events.textContent = "";
  for (const event of uniqueEvents) applyEventEffects(event, { appendCard: false, renderGraph: false });
  const visibleCards = uniqueEvents.slice(-MAX_EVENT_CARDS);
  if (state.events.length > MAX_EVENT_CARDS) {
    const notice = document.createElement("article");
    notice.className = "event";
    notice.innerHTML = `<strong>事件视图已截断</strong><pre>共有 ${state.events.length} 个事件，仅渲染最近 ${MAX_EVENT_CARDS} 个，完整内容保存在后端历史记录中。</pre>`;
    elements.events.appendChild(notice);
    elements.events.classList.remove("empty");
  }
  for (const event of visibleCards) appendEventCard(event, { trim: false });
  renderEventGraph();
}

function subscribe(runId, fromIndex = 0) {
  closeSubscription(false);
  state.activeRunStatus = "running";
  setActiveRun(runId);
  setStatus("running", "运行中", `run ${runId.slice(0, 8)}`);
  state.source = new EventSource(`/api/runs/${runId}/events?from_index=${fromIndex}`);
  state.source.onmessage = (message) => {
    if (state.activeRunId !== runId) return;
    renderEvent(JSON.parse(message.data));
  };
  state.source.onerror = () => {
    if (state.activeRunId !== runId) return;
    if (["done", "error"].includes(state.activeRunStatus)) return;
    setStatus("error", "连接断开", "可重新连接原任务，或用此问题新建任务");
    closeSubscription(false);
    setBusy(false);
  };
}

function closeSubscription(clearActive = true) {
  if (state.source) state.source.close();
  state.source = null;
  if (clearActive) setActiveRun("");
  else updateEditorMode();
}

async function run() {
  if (isRunView()) return;
  const body = payload();
  if (!body.input) return;
  setBusy(true);
  resetOutputs();
  try {
    await createRun(body, { open: true });
  } finally {
    setBusy(false);
  }
}

async function createRun(body, { open = false } = {}) {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.message || "创建任务失败");
  if (open) {
    state.activeRunStatus = "running";
    subscribe(data.run_id, 0);
  }
  await loadHistory();
  return data;
}

async function createParallelRun() {
  const body = newSessionPayload();
  if (!body.input) return;
  elements.newSessionButton.disabled = true;
  try {
    await createRun(body, { open: true });
    elements.newSessionInput.value = "";
  } finally {
    elements.newSessionButton.disabled = false;
  }
}

async function executePlannedRun() {
  if (isRunView()) return;
  const body = payload();
  if (!body.input) return;
  if (!isPlanCurrent()) {
    setStatus("error", "Plan 已过期", "输入已变更，请重新规划后再执行");
    return;
  }
  let plan;
  try {
    plan = readPlanDraft();
  } catch (error) {
    setStatus("error", "Plan 无效", error.message);
    return;
  }
  if (!plan) return;
  setBusy(true);
  resetOutputs();
  try {
    const response = await fetch("/api/runs/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input: body.input,
        plan,
        context: {},
        model: body.model,
        auto_repair: body.auto_repair,
        max_repair_attempts: body.max_repair_attempts,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.message || "创建执行任务失败");
    state.activeRunStatus = "running";
    subscribe(data.run_id, 0);
    loadHistory();
  } finally {
    setBusy(false);
  }
}

async function duplicateRun() {
  const body = payload();
  if (!body.input || state.source) return;
  closeSubscription(true);
  elements.prompt.value = body.input;
  await run();
}

function reconnectRun() {
  if (!canReconnectRun()) return;
  subscribe(state.activeRunId, state.events.length);
}

async function restoreRun(runId) {
  closeSubscription(false);
  setActiveRun(runId);
  setStatus("running", "加载历史", `run ${runId.slice(0, 8)}`);
  const response = await fetch(`/api/runs/${runId}`);
  if (!response.ok) {
    closeSubscription(true);
    return;
  }
  const data = await response.json();
  if (state.activeRunId !== runId) return;
  const run = data.run;
  state.activeRunStatus = run.status || "";
  resetOutputs();
  setActiveRun(runId);
  elements.prompt.value = run.request?.input || "";
  renderEventBatch(run.events || []);
  updateHistorySelection();
  if (!["done", "error"].includes(run.status)) subscribe(run.id, (run.events || []).length);
  else {
    setBusy(false);
    setStatus(run.status === "done" ? "ok" : "error", run.status, run.error || "历史会话");
  }
}

async function planOnly() {
  if (isRunView()) return;
  const body = payload();
  if (!body.input) return;
  resetOutputs();
  setBusy(true);
  setStatus("running", "规划中", "请求 /api/plan");
  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || data.error || "规划失败");
    setPlanDraft(data.plan || [], body.input);
    renderEvent({ type: "plan_response", ...data });
    activateTab("plan");
    setStatus("ok", "规划完成", "可执行当前规划，或编辑输入后重新规划");
  } finally {
    setBusy(false);
  }
}

async function loadHistory() {
  const response = await fetch("/api/runs");
  const data = await response.json();
  elements.historyList.textContent = "";
  for (const run of data.runs || []) {
    const item = document.createElement("button");
    item.className = `history-item ${run.id === state.activeRunId ? "active" : ""}`;
    item.dataset.runId = run.id;
    item.type = "button";
    const rawCount = run.raw_event_count && run.raw_event_count !== run.event_count ? ` · 原始 ${run.raw_event_count}` : "";
    const steps = run.total_steps ? ` · ${run.completed_steps || 0}/${run.total_steps} steps` : "";
    const repairs = run.repair_count ? ` · 修复 ${run.repair_count}` : "";
    const excerpt = run.excerpt ? `<small class="history-excerpt">${escapeHtml(run.excerpt)}</small>` : "";
    item.innerHTML = `
      <strong>${escapeHtml(run.input || "(empty)")}</strong>
      <small>${escapeHtml(run.status)} · ${run.event_count} 个事件${steps}${repairs}${rawCount}</small>
      ${excerpt}
    `;
    item.addEventListener("click", () => restoreRun(run.id));
    elements.historyList.appendChild(item);
  }
  if (!elements.historyList.children.length) elements.historyList.innerHTML = '<p class="muted">暂无历史</p>';
  updateHistorySelection();
}

async function loadModels() {
  const response = await fetch("/api/models");
  const data = await response.json();
  elements.model.innerHTML = '<option value="">默认模型</option>';
  for (const item of data.models || []) {
    const option = document.createElement("option");
    option.value = item.model;
    option.textContent = `${item.model || item.provider}${item.is_default ? "（默认）" : ""}`;
    elements.model.appendChild(option);
  }
}

async function loadSkills() {
  const response = await fetch("/api/skills");
  const data = await response.json();
  elements.skillsList.textContent = "";
  for (const skill of data.skills || []) {
    const card = document.createElement("article");
    card.className = "skill";
    card.innerHTML = `<strong><span>${escapeHtml(skill.name || skill.id)}</span><span class="badge">${escapeHtml(skill.type)}</span></strong><p class="muted">${escapeHtml(skill.description || "暂无描述")}</p>`;
    elements.skillsList.appendChild(card);
  }
  if (!elements.skillsList.children.length) elements.skillsList.innerHTML = '<p class="muted">暂无能力</p>';
}

async function loadMeta() {
  setStatus("running", "连接中", "读取模型、能力和历史");
  try {
    await Promise.all([loadModels(), loadSkills(), loadHistory()]);
    setStatus("ok", "待命", "后端连接正常");
  } catch (error) {
    setStatus("error", "连接失败", error.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function activateTab(tabName) {
  document.querySelectorAll(".tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === tabName));
  document.querySelectorAll(".tab-panel").forEach((item) => item.classList.toggle("active", item.id === `${tabName}Tab`));
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  run().catch((error) => {
    setStatus("error", "请求失败", error.message);
    appendStream(`\n错误：${error.message}\n`);
    setBusy(false);
  });
});
elements.planButton.addEventListener("click", () => planOnly().catch((error) => setStatus("error", "规划失败", error.message)));
elements.executePlanButton.addEventListener("click", () => executePlannedRun().catch((error) => setStatus("error", "执行失败", error.message)));
elements.reconnectButton.addEventListener("click", reconnectRun);
elements.duplicateButton.addEventListener("click", () => duplicateRun().catch((error) => setStatus("error", "创建失败", error.message)));
elements.newSessionButton.addEventListener("click", () => createParallelRun().catch((error) => setStatus("error", "创建失败", error.message)));
elements.refreshMeta.addEventListener("click", loadMeta);
elements.refreshHistory.addEventListener("click", loadHistory);
elements.prompt.addEventListener("input", () => updateEditorMode());

resetOutputs();
loadMeta().then(() => {
  if (state.activeRunId) restoreRun(state.activeRunId);
});
