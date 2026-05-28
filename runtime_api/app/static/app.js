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
const fieldReleaseForm = document.querySelector("#fieldReleaseForm");
const fieldReleaseName = document.querySelector("#fieldReleaseName");
const fieldReleaseValue = document.querySelector("#fieldReleaseValue");
const fieldReleasePurpose = document.querySelector("#fieldReleasePurpose");
const fieldReleaseResult = document.querySelector("#fieldReleaseResult");
let realtimeSocket = null;
let realtimeReady = false;
let activeAssistantNode = null;
let approvedSensitiveFields = {};
const openClawJobCards = new Map();

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
  if (event.type === "openclaw_job_event") {
    handleOpenClawRealtimeEvent(event);
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
    const traceQuery = new URLSearchParams();
    if (governanceQuery.value.trim()) traceQuery.set("q", governanceQuery.value.trim());
    traceQuery.set("limit", "20");
    const [data, routeTraceData] = await Promise.all([
      api(`/api/memory/governance${query ? `?${query}` : ""}`),
      api(`/api/tools/route/traces?${traceQuery.toString()}`),
    ]);
    governanceContent.textContent = "";
    renderGovernanceSection("事件审计", data.events || [], renderEventGovernanceItem);
    renderGovernanceSection("长期记忆", data.semantic_memory || [], renderSemanticGovernanceItem);
    renderGovernanceSection("状态记忆", data.states || [], renderStateGovernanceItem);
    renderGovernanceSection("任务路由", routeTraceData.traces || [], renderRouteTraceGovernanceItem);
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

function routeTypeLabel(routeType) {
  if (routeType === "core_pipeline") return "核心 Pipeline";
  if (routeType === "openclaw_tool") return "OpenClaw 长尾";
  if (routeType === "ask_user") return "需要澄清";
  return routeType || "未知路由";
}

function renderRouteTraceGovernanceItem(item) {
  const node = card();
  const packetGoal = item.openclaw_task_packet?.goal ? `\nOpenClaw 目标：${item.openclaw_task_packet.goal}` : "";
  const clarification = item.clarification?.question ? `\n澄清问题：${item.clarification.question}` : "";
  const pipeline = item.pipeline_id ? `\nPipeline：${item.pipeline_id}` : "";
  node.innerHTML = `<time>${routeTypeLabel(item.route_type)} · ${item.capability_id || "unknown"} · ${item.risk_permission || "read_only"}</time><strong>${item.request}</strong><p>${renderJson(item.task_route_decision)}${pipeline}${packetGoal}${clarification}</p>`;
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
    const composioStatus = await api("/api/integrations/composio/status").catch((error) => ({
      configured: false,
      error: error.message || "无法读取 Composio 状态",
      readonly_toolkits: [],
    }));
    const composioConnections = composioStatus.configured
      ? await api("/api/integrations/composio/toolkits?session_kind=readonly").catch((error) => ({
          toolkits: [],
          error: error.message || "无法同步 Composio 连接状态",
        }))
      : { toolkits: [] };
    toolsContent.textContent = "";
    toolsContent.appendChild(renderComposioPanel(composioStatus, composioConnections));
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

function renderComposioPanel(status, connections) {
  const node = card("card integration-card");
  const configuredText = status.configured ? "已配置 API Key" : "未配置 API Key";
  const connectedBySlug = new Map((connections.toolkits || []).map((toolkit) => [toolkit.slug, toolkit]));
  const primaryToolkits = (status.readonly_toolkits || [
    "gmail",
    "googlecalendar",
    "googledrive",
    "googledocs",
    "googlesheets",
    "googletasks",
    "google_maps",
  ]).slice(0, 10);
  node.innerHTML = `
    <time>Composio Connect · ${configuredText}</time>
    <strong>连接外部账号</strong>
    <p>点击后会打开 Composio Connect Link。授权完成后，Nomi 会用本地 Pipeline 和确认机制决定何时读取或写入。</p>
  `;
  const grid = document.createElement("div");
  grid.className = "connection-grid";
  for (const slug of primaryToolkits) {
    const connection = connectedBySlug.get(slug);
    const row = document.createElement("div");
    row.className = "connection-row";
    const label = document.createElement("div");
    label.innerHTML = `<strong>${connection?.name || slug}</strong><span>${connection?.connected ? "已连接" : "未连接"}</span>`;
    const connect = button(connection?.connected ? "重新连接" : "连接");
    connect.disabled = !status.configured;
    connect.addEventListener("click", async () => {
      connect.disabled = true;
      connect.textContent = "生成链接...";
      try {
        const result = await api(`/api/integrations/composio/connect/${encodeURIComponent(slug)}`, { method: "POST" });
        connect.textContent = "打开授权";
        if (result.redirect_url) window.open(result.redirect_url, "_blank", "noopener,noreferrer");
      } catch {
        connect.textContent = "生成失败";
      } finally {
        setTimeout(() => {
          connect.disabled = !status.configured;
          if (connect.textContent !== "生成失败") connect.textContent = connection?.connected ? "重新连接" : "连接";
        }, 1800);
      }
    });
    row.append(label, connect);
    grid.appendChild(row);
  }
  node.appendChild(grid);
  if (status.error || connections.error) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = status.error || connections.error;
    node.appendChild(note);
  }
  return node;
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
  const context = Object.keys(approvedSensitiveFields).length
    ? { approved_sensitive_fields: approvedSensitiveFields }
    : {};
  try {
    const result = await api("/api/tools/route", {
      method: "POST",
      body: JSON.stringify({ request, context }),
    });
    toolRouteResult.textContent = "";
    toolRouteResult.appendChild(renderRouteResult(result));
  } catch {
    toolRouteResult.textContent = "路由失败。";
  }
}

async function releaseSensitiveField() {
  const field = fieldReleaseName.value.trim();
  const value = fieldReleaseValue.value.trim();
  const purpose = fieldReleasePurpose.value.trim();
  if (!field || !value || !purpose) {
    fieldReleaseResult.textContent = "需要填写字段、原值和用途。";
    return;
  }
  fieldReleaseResult.textContent = "生成放行记录...";
  try {
    const result = await api("/api/tools/openclaw/field-release", {
      method: "POST",
      body: JSON.stringify({ field, value, purpose }),
    });
    approvedSensitiveFields = {
      ...approvedSensitiveFields,
      ...(result.approved_sensitive_fields || {}),
    };
    fieldReleaseResult.textContent = "";
    const node = card("card compact");
    node.innerHTML = `<strong>已放行字段：${Object.keys(result.approved_sensitive_fields || {}).join("、")}</strong><p>下一次工具路由会把这些字段放入 OpenClaw 的正式批准上下文。</p>`;
    fieldReleaseResult.appendChild(node);
  } catch {
    fieldReleaseResult.textContent = "字段放行失败。";
  }
}

function renderRouteResult(result) {
  const node = card("card route-card");
  const routeLabel =
    result.route_type === "core_pipeline" ? "核心 Pipeline" :
    result.route_type === "openclaw_tool" ? "OpenClaw 长尾执行" :
    result.route_type === "ask_user" ? "需要澄清" :
    "工具路由";
  const pipeline = result.pipeline ? `<p>Pipeline：${result.pipeline.name}</p>` : `<p>Pipeline：${routeLabel}</p>`;
  const tools = (result.candidate_tools || []).map((tool) => `${tool.name} (${tool.recommended_adapter})`).join("；") || "暂无候选工具";
  const guard = result.execution_guard || {};
  const packet = result.openclaw_task_packet;
  const packetSummary = packet
    ? `<p>OpenClaw：允许 ${packet.allowed_actions.join(" / ")}；禁止 ${packet.forbidden_actions.slice(0, 5).join(" / ")}。</p>`
    : "";
  const clarification = result.clarification?.required
    ? `<p>需要补充：${result.clarification.missing_fields.join("、")}</p>`
    : "";
  node.innerHTML = `
    <time>${routeLabel} · ${result.capability?.id || ""}</time>
    <strong>${result.routing_reason || "工具路由结果"}</strong>
    ${pipeline}
    <p>候选工具：${tools}</p>
    <p>权限：${guard.permission || "read_only"} · ${guard.policy || ""}${guard.final_user_confirmation ? " · 最终确认" : ""}</p>
    ${packetSummary}
    ${clarification}
  `;
  if (result.route_type === "openclaw_tool" && packet) {
    const actions = document.createElement("div");
    actions.className = "actions";
    const enqueue = button("加入执行队列");
    enqueue.addEventListener("click", async () => {
      enqueue.disabled = true;
      const job = await api("/api/tools/openclaw/jobs", {
        method: "POST",
        body: JSON.stringify({ packet, execution_guard: guard, max_attempts: 3 }),
      });
      node.appendChild(renderOpenClawJobCard(job));
    });
    actions.appendChild(enqueue);
    node.appendChild(actions);
  }
  return node;
}

function renderOpenClawJobCard(job) {
  const node = card("card compact");
  node.innerHTML = `<time>OpenClaw Job · ${job.status}</time><strong>${job.job_id}</strong><p>尝试次数：${job.attempt_count || 0}/${job.max_attempts || 1}</p>`;
  const actions = document.createElement("div");
  actions.className = "actions";
  const run = button("运行一次");
  const refresh = button("刷新事件");
  const events = document.createElement("p");
  events.className = "muted";
  run.addEventListener("click", async () => {
    run.disabled = true;
    const result = await api(`/api/tools/openclaw/jobs/${job.job_id}/run-once`, { method: "POST" });
    node.querySelector("time").textContent = `OpenClaw Job · ${result.status}`;
    node.querySelector("p").textContent = `尝试次数：${result.attempt_count || 0}/${result.max_attempts || job.max_attempts || 1}`;
    run.disabled = false;
  });
  refresh.addEventListener("click", async () => {
    const status = await api(`/api/tools/openclaw/jobs/${job.job_id}`);
    events.textContent = (status.events || []).map((event) => `${event.event_type}: ${event.message}`).join("\n") || "暂无事件";
    node.querySelector("time").textContent = `OpenClaw Job · ${status.job.status}`;
  });
  actions.append(run, refresh);
  node.append(actions, events);
  openClawJobCards.set(job.job_id, { node, events, maxAttempts: job.max_attempts || 1 });
  return node;
}

function openClawStatusFromEvent(eventType) {
  if (["completed", "failed", "blocked", "needs_user_input", "retry_scheduled", "running"].includes(eventType)) return eventType;
  if (eventType === "attempt_started") return "running";
  return null;
}

function handleOpenClawRealtimeEvent(event) {
  const item = openClawJobCards.get(event.job_id);
  if (!item) return;
  const status = openClawStatusFromEvent(event.event_type);
  if (status) item.node.querySelector("time").textContent = `OpenClaw Job · ${status}`;
  const current = item.events.textContent ? `${item.events.textContent}\n` : "";
  item.events.textContent = `${current}${event.event_type}: ${event.message || ""}`;
  const attemptCount = event.payload?.attempt_count;
  const maxAttempts = event.payload?.max_attempts || item.maxAttempts;
  if (attemptCount) item.node.querySelector("p").textContent = `尝试次数：${attemptCount}/${maxAttempts}`;
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
fieldReleaseForm.addEventListener("submit", (event) => {
  event.preventDefault();
  releaseSensitiveField();
});

if (password()) showApp();
