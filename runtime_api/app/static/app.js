const passwordKey = "par-password";
const loginPanel = document.querySelector("#loginPanel");
const appPanel = document.querySelector("#appPanel");
const loginForm = document.querySelector("#loginForm");
const loginError = document.querySelector("#loginError");
const passwordInput = document.querySelector("#passwordInput");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const messages = document.querySelector("#messages");
const searchForm = document.querySelector("#searchForm");
const searchInput = document.querySelector("#searchInput");
const searchContent = document.querySelector("#searchContent");
const governanceFilters = document.querySelector("#governanceFilters");
const governanceQuery = document.querySelector("#governanceQuery");
const governanceSource = document.querySelector("#governanceSource");
const governanceSensitive = document.querySelector("#governanceSensitive");
const governanceContent = document.querySelector("#governanceContent");
const suggestionsContent = document.querySelector("#suggestionsContent");
const collectorsContent = document.querySelector("#collectorsContent");
const toolsContent = document.querySelector("#toolsContent");
const refreshGovernance = document.querySelector("#refreshGovernance");
const refreshSuggestions = document.querySelector("#refreshSuggestions");
const refreshCollectors = document.querySelector("#refreshCollectors");
const refreshTools = document.querySelector("#refreshTools");
const toolRouteForm = document.querySelector("#toolRouteForm");
const toolRouteInput = document.querySelector("#toolRouteInput");
const toolRouteResult = document.querySelector("#toolRouteResult");
let realtimeSocket = null;
let realtimeReady = false;
let activeAssistantNode = null;

function password() {
  return localStorage.getItem(passwordKey) || "";
}

function showApp() {
  loginPanel.classList.add("hidden");
  appPanel.classList.remove("hidden");
  connectRealtime();
  if (location.hash === "#chat") switchView("chatView");
  consumePendingProactive();
  loadDashboard();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "content-type": "application/json",
      "x-par-password": password(),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function switchView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === viewId));
  document.querySelectorAll(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.view === viewId));
  if (viewId === "suggestionsView") loadSuggestions();
  if (viewId === "collectorsView") loadCollectors();
  if (viewId === "toolsView") loadTools();
  if (viewId === "governanceView") loadGovernance();
}

function renderJson(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  return value.summary || value.current_value || JSON.stringify(value, null, 2);
}

function card(className = "card") {
  const node = document.createElement("article");
  node.className = className;
  return node;
}

function addMessage(role, text, sources = []) {
  const item = card(`message ${role}`);
  item.textContent = text;
  if (sources.length) item.appendChild(renderSources(sources));
  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
  return item;
}

function appendMessageText(node, text) {
  node.textContent += text;
  messages.scrollTop = messages.scrollHeight;
}

function connectRealtime() {
  if (realtimeSocket && realtimeSocket.readyState <= WebSocket.OPEN) return;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  realtimeSocket = new WebSocket(`${protocol}//${location.host}/ws?password=${encodeURIComponent(password())}`);
  realtimeSocket.addEventListener("open", () => {
    realtimeReady = true;
  });
  realtimeSocket.addEventListener("close", () => {
    realtimeReady = false;
    setTimeout(() => {
      if (password()) connectRealtime();
    }, 3000);
  });
  realtimeSocket.addEventListener("message", (event) => {
    handleRealtimeMessage(JSON.parse(event.data));
  });
}

function handleRealtimeMessage(event) {
  if (event.type === "proactive_message") {
    switchView("chatView");
    const title = event.title ? `${event.title}\n` : "";
    addMessage("assistant", `${title}${event.body || ""}`);
    location.hash = "chat";
    return;
  }
  if (event.type === "chat_delta") {
    if (!activeAssistantNode) activeAssistantNode = addMessage("assistant", "");
    appendMessageText(activeAssistantNode, event.delta || "");
    return;
  }
  if (event.type === "chat_done") {
    if (activeAssistantNode && event.sources?.length) activeAssistantNode.appendChild(renderSources(event.sources));
    activeAssistantNode = null;
    return;
  }
  if (event.type === "error") {
    addMessage("assistant", event.message || "实时通道发生错误。");
  }
}

function consumePendingProactive() {
  const raw = localStorage.getItem("nomi-pending-proactive");
  if (!raw) return;
  localStorage.removeItem("nomi-pending-proactive");
  try {
    const event = JSON.parse(raw);
    switchView("chatView");
    const title = event.title ? `${event.title}\n` : "";
    addMessage("assistant", `${title}${event.body || ""}`);
  } catch {
    addMessage("assistant", raw);
  }
}

function renderSources(sources) {
  const sourceBox = document.createElement("div");
  sourceBox.className = "sources";
  sourceBox.textContent = `引用 ${sources.length} 条本地记忆`;
  const list = document.createElement("ul");
  list.className = "source-list";
  for (const source of sources.slice(0, 6)) {
    const row = document.createElement("li");
    const layer = source.layer || "memory";
    const explanation = source.explanation || source.layer || "相关个人上下文";
    const summary = source.summary || source.content?.summary || source.object || source.value?.summary || "";
    row.textContent = `${layer} · ${explanation}${summary ? ` · ${summary}` : ""}`;
    list.appendChild(row);
  }
  sourceBox.appendChild(list);
  return sourceBox;
}

async function loadDashboard() {
  await Promise.allSettled([loadSuggestions(), loadCollectors(), loadGovernance(), loadTools()]);
}

async function loadSearch(query) {
  searchContent.textContent = "搜索中...";
  try {
    const result = await api("/search", {
      method: "POST",
      body: JSON.stringify({ query, limit: 20 }),
    });
    searchContent.textContent = "";
    const plan = card("card compact");
    plan.innerHTML = `<strong>检索计划</strong><p>${(result.retrieval_plan?.reasons || []).join("；") || "默认分层检索"}</p>`;
    searchContent.appendChild(plan);
    for (const source of result.sources || []) {
      const node = card();
      node.innerHTML = `<time>${source.layer || "memory"} · ${(source.confidence || 0).toFixed ? Number(source.confidence || 0).toFixed(2) : ""}</time><strong>${source.explanation || "相关结果"}</strong><p>${renderJson(source.content || source.summary || source.object || source.value)}</p>`;
      searchContent.appendChild(node);
    }
    if (searchContent.children.length === 1) searchContent.appendChild(emptyCard("没有找到相关记忆"));
  } catch {
    searchContent.textContent = "搜索失败。";
  }
}

function governanceQueryString() {
  const params = new URLSearchParams();
  if (governanceQuery.value.trim()) params.set("q", governanceQuery.value.trim());
  if (governanceSource.value) params.set("source", governanceSource.value);
  if (governanceSensitive.value) params.set("sensitive", governanceSensitive.value);
  return params.toString();
}

async function loadGovernance() {
  governanceContent.textContent = "加载中...";
  try {
    const query = governanceQueryString();
    const data = await api(`/api/memory/governance${query ? `?${query}` : ""}`);
    governanceContent.textContent = "";
    renderGovernanceSection("事件审计", data.events || [], renderEventGovernanceItem);
    renderGovernanceSection("长期记忆", data.semantic_memory || [], renderSemanticGovernanceItem);
    renderGovernanceSection("状态记忆", data.states || [], renderStateGovernanceItem);
    if (!governanceContent.children.length) governanceContent.appendChild(emptyCard("暂无治理项"));
  } catch {
    governanceContent.textContent = "无法读取治理数据。";
  }
}

function renderGovernanceSection(title, items, renderer) {
  if (!items.length) return;
  const heading = document.createElement("h3");
  heading.textContent = title;
  governanceContent.appendChild(heading);
  for (const item of items) governanceContent.appendChild(renderer(item));
}

function renderEventGovernanceItem(item) {
  const node = card();
  const sensitive = item.sensitive ? ` · 敏感：${(item.sensitive_reasons || []).join(", ") || "是"}` : "";
  node.innerHTML = `<time>${item.source} · ${item.event_type}${sensitive}</time><strong>${item.summary || item.intent || "事件"}</strong><p>${renderJson(item.raw_data)}</p>`;
  const actions = document.createElement("div");
  actions.className = "actions";
  const raw = button("读取本地原文");
  raw.addEventListener("click", async () => {
    raw.disabled = true;
    try {
      const data = await api(`/api/events/${item.event_id}/private-raw`);
      node.querySelector("p").textContent = renderJson(data.raw_data);
      raw.textContent = "已读取";
    } catch {
      raw.textContent = "读取失败";
    }
  });
  actions.appendChild(raw);
  node.appendChild(actions);
  return node;
}

function renderSemanticGovernanceItem(item) {
  const node = card();
  node.innerHTML = `<time>${item.memory_type} · ${Number(item.confidence || 0).toFixed(2)}</time><strong>长期记忆</strong><p>${renderJson(item.content)}</p>`;
  const actions = document.createElement("div");
  actions.className = "actions";
  const correct = button("纠正");
  correct.addEventListener("click", async () => {
    const summary = window.prompt("输入更正后的记忆", renderJson(item.content));
    if (!summary) return;
    await api(`/api/memory/semantic/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ summary, reason: "corrected from governance UI" }),
    });
    await loadGovernance();
  });
  const remove = button("删除");
  remove.className = "danger";
  remove.addEventListener("click", async () => {
    await api("/memory/delete", { method: "POST", body: JSON.stringify({ memory_id: item.id }) });
    node.remove();
  });
  actions.append(correct, remove);
  node.appendChild(actions);
  return node;
}

function renderStateGovernanceItem(item) {
  const node = card();
  node.innerHTML = `<time>${item.key} · ${Number(item.confidence || 0).toFixed(2)}</time><strong>状态</strong><p>${renderJson(item.value)}</p>`;
  return node;
}

async function loadSuggestions() {
  suggestionsContent.textContent = "加载中...";
  try {
    const data = await api("/api/suggestions");
    suggestionsContent.textContent = "";
    for (const item of data || []) {
      const node = card();
      node.innerHTML = `<time>${item.metadata?.suggestion_type || "suggestion"} · 优先级 ${Number(item.priority || 0).toFixed(2)}</time><strong>${item.title}</strong><p>${item.body}</p>`;
      const actions = document.createElement("div");
      actions.className = "actions";
      const done = button("完成");
      done.addEventListener("click", () => updateSuggestion(item.id, "done", node));
      const dismiss = button("忽略");
      dismiss.addEventListener("click", () => updateSuggestion(item.id, "dismissed", node));
      actions.append(done, dismiss);
      node.appendChild(actions);
      suggestionsContent.appendChild(node);
    }
    if (!suggestionsContent.children.length) suggestionsContent.appendChild(emptyCard("暂无建议"));
  } catch {
    suggestionsContent.textContent = "无法读取建议。";
  }
}

async function updateSuggestion(id, status, node) {
  await api(`/api/suggestions/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
  node.remove();
}

function collectorStatusText(item) {
  if (!item.enabled) return "已关闭";
  if (item.paused) return "已暂停";
  return "采集中";
}

async function loadCollectors() {
  collectorsContent.textContent = "加载中...";
  try {
    const data = await api("/api/collectors/status");
    collectorsContent.textContent = "";
    for (const item of data.collectors || []) {
      const node = card();
      node.innerHTML = `<time>${collectorStatusText(item)} · ${item.health_status || "unknown"}</time><strong>${item.source}</strong><p>${JSON.stringify(item.details || {}, null, 2)}</p>`;
      const actions = document.createElement("div");
      actions.className = "actions";
      const toggle = button(item.enabled && !item.paused ? "暂停" : "开启");
      toggle.addEventListener("click", async () => {
        const nextEnabled = !(item.enabled && !item.paused);
        await api(`/api/collectors/settings/${item.source}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled: nextEnabled, paused_until: null, reason: nextEnabled ? "" : "user paused from workbench" }),
        });
        await loadCollectors();
      });
      const pauseHour = button("暂停1小时");
      pauseHour.addEventListener("click", async () => {
        const until = new Date(Date.now() + 60 * 60 * 1000).toISOString();
        await api(`/api/collectors/settings/${item.source}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled: true, paused_until: until, reason: "temporary pause from workbench" }),
        });
        await loadCollectors();
      });
      actions.append(toggle, pauseHour);
      node.appendChild(actions);
      collectorsContent.appendChild(node);
    }
  } catch {
    collectorsContent.textContent = "无法读取采集设置。";
  }
}

function phaseText(phase) {
  if (phase === "core") return "第一批";
  if (phase === "recommended") return "第二批";
  if (phase === "experimental") return "实验";
  return phase || "候选";
}

function riskText(risk) {
  if (risk === "low") return "低风险";
  if (risk === "medium") return "中风险";
  if (risk === "high") return "高风险";
  return risk || "未知风险";
}

async function loadTools() {
  toolsContent.textContent = "加载中...";
  try {
    const data = await api("/api/tools/catalog");
    toolsContent.textContent = "";
    const policy = card("card compact");
    policy.innerHTML = `<strong>执行权限规则</strong><p>读取可直接执行；写入、发消息、叫车、购买等动作都需要用户确认。付款/下单必须最终确认。</p>`;
    toolsContent.appendChild(policy);
    const groups = [
      ["core", "第一批：先接入"],
      ["recommended", "第二批：目标人群高频"],
      ["experimental", "实验：生活服务与非官方工具"],
    ];
    for (const [phase, title] of groups) {
      const items = (data.tools || []).filter((tool) => tool.phase === phase);
      if (!items.length) continue;
      const heading = document.createElement("h3");
      heading.textContent = title;
      toolsContent.appendChild(heading);
      for (const tool of items) toolsContent.appendChild(renderToolCard(tool));
    }
  } catch {
    toolsContent.textContent = "无法读取工具目录。";
  }
}

function renderToolCard(tool) {
  const node = card("card tool-card");
  const jobs = (tool.user_jobs || []).map((job) => `<span>${job}</span>`).join("");
  const permissions = (tool.permission_levels || []).map((level) => `<span>${level}</span>`).join("");
  node.innerHTML = `
    <time>${phaseText(tool.phase)} · ${riskText(tool.risk_level)} · ${tool.recommended_adapter || "adapter 待定"}</time>
    <strong>${tool.name}</strong>
    <p>${jobs}</p>
    <div class="pill-row">${permissions}</div>
  `;
  if (tool.confirmation_required) {
    const note = document.createElement("div");
    note.className = "tool-note";
    note.textContent = "执行前需要确认";
    node.appendChild(note);
  }
  return node;
}

async function routeToolRequest(request) {
  toolRouteResult.textContent = "路由中...";
  try {
    const result = await api("/api/tools/route", {
      method: "POST",
      body: JSON.stringify({ request }),
    });
    toolRouteResult.textContent = "";
    toolRouteResult.appendChild(renderRouteResult(result));
  } catch {
    toolRouteResult.textContent = "路由失败。";
  }
}

function renderRouteResult(result) {
  const node = card("card route-card");
  const pipeline = result.pipeline ? `<p>Pipeline：${result.pipeline.name}</p>` : "<p>Pipeline：长尾工具路由</p>";
  const tools = (result.candidate_tools || []).map((tool) => `${tool.name} (${tool.recommended_adapter})`).join("；") || "暂无候选工具";
  const guard = result.execution_guard || {};
  node.innerHTML = `
    <time>${result.route_type === "core_pipeline" ? "核心 Pipeline" : "长尾工具"} · ${result.capability?.id || ""}</time>
    <strong>${result.routing_reason || "工具路由结果"}</strong>
    ${pipeline}
    <p>候选工具：${tools}</p>
    <p>权限：${guard.permission || "read_only"} · ${guard.policy || ""}${guard.final_user_confirmation ? " · 最终确认" : ""}</p>
  `;
  return node;
}

function button(text) {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = text;
  return node;
}

function emptyCard(text) {
  const node = card("card compact muted");
  node.textContent = text;
  return node;
}

document.querySelectorAll(".nav-button").forEach((buttonNode) => {
  buttonNode.addEventListener("click", () => switchView(buttonNode.dataset.view));
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  localStorage.setItem(passwordKey, passwordInput.value);
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ password: passwordInput.value }) });
    showApp();
  } catch {
    localStorage.removeItem(passwordKey);
    loginError.textContent = "密码不正确";
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text) return;
  messageInput.value = "";
  addMessage("user", text);
  if (realtimeReady && realtimeSocket?.readyState === WebSocket.OPEN) {
    activeAssistantNode = addMessage("assistant", "");
    realtimeSocket.send(JSON.stringify({ type: "chat_message", message: text }));
    return;
  }
  const pendingNode = addMessage("assistant", "正在结合本地记忆思考...");
  try {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text }) });
    pendingNode.textContent = result.answer;
    if (result.sources?.length) pendingNode.appendChild(renderSources(result.sources));
  } catch {
    pendingNode.textContent = "请求失败，请检查模型服务或访问密码。";
  }
});

window.addEventListener("hashchange", () => {
  if (location.hash === "#chat") switchView("chatView");
});
window.addEventListener("nomi-pending-proactive", consumePendingProactive);

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (query) loadSearch(query);
});
governanceFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  loadGovernance();
});
refreshGovernance.addEventListener("click", loadGovernance);
refreshSuggestions.addEventListener("click", loadSuggestions);
refreshCollectors.addEventListener("click", loadCollectors);
refreshTools.addEventListener("click", loadTools);
toolRouteForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const request = toolRouteInput.value.trim();
  if (request) routeToolRequest(request);
});

if (password()) showApp();
