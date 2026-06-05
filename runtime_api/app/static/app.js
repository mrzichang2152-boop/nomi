const passwordKey = "par-password";
const conversationKey = "nomi-conversation-id";
const loginPanel = document.querySelector("#loginPanel");
const appPanel = document.querySelector("#appPanel");
const loginForm = document.querySelector("#loginForm");
const loginError = document.querySelector("#loginError");
const passwordInput = document.querySelector("#passwordInput");
const sidebar = document.querySelector(".sidebar");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const chatSubmitButton = document.querySelector("#chatForm button[type='submit']");
const messages = document.querySelector("#messages");
const searchForm = document.querySelector("#searchForm");
const searchInput = document.querySelector("#searchInput");
const searchContent = document.querySelector("#searchContent");
const governanceFilters = document.querySelector("#governanceFilters");
const governanceQuery = document.querySelector("#governanceQuery");
const governanceSource = document.querySelector("#governanceSource");
const governanceSensitive = document.querySelector("#governanceSensitive");
const governanceContent = document.querySelector("#governanceContent");
const agendaContent = document.querySelector("#agendaContent");
const agendaDayTabs = document.querySelector("#agendaDayTabs");
const suggestionsContent = document.querySelector("#suggestionsContent");
const collectorsContent = document.querySelector("#collectorsContent");
const toolsContent = document.querySelector("#toolsContent");
const refreshGovernance = document.querySelector("#refreshGovernance");
const refreshAgenda = document.querySelector("#refreshAgenda");
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
let agendaItems = [];
let selectedAgendaDate = "";
let chatConversationId = localStorage.getItem(conversationKey) || "";
let chatHistoryLoaded = false;
let viewportMetricsBound = false;
let realtimeChatWatchdog = null;
let realtimeChatHadDelta = false;
let lastTouchSubmitAt = 0;
const openClawJobCards = new Map();
const realtimePendingText = "正在结合本地记忆思考...";
const realtimeTimeoutMs = 45000;

function password() {
  return localStorage.getItem(passwordKey) || "";
}

function showApp() {
  loginPanel.classList.add("hidden");
  appPanel.classList.remove("hidden");
  bindViewportMetrics();
  connectRealtime();
  if (location.hash === "#chat") switchView("chatView");
  loadChatHistory().finally(() => {
    consumePendingProactive();
    consumePendingAgentEvent();
  });
  loadDashboard();
}

function updateViewportMetrics() {
  const viewport = window.visualViewport;
  const focusedComposer = document.activeElement === messageInput;
  const rawViewportHeight = viewport ? viewport.height : window.innerHeight;
  let keyboardBottom = viewport
    ? Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop))
    : 0;
  if (focusedComposer && keyboardBottom < 80 && rawViewportHeight >= window.innerHeight - 8) {
    keyboardBottom = Math.round(window.innerHeight * 0.38);
  }
  const appHeight = Math.max(
    320,
    Math.round(keyboardBottom > 80 ? window.innerHeight - keyboardBottom : rawViewportHeight || window.innerHeight || 0)
  );
  const sidebarHeight = sidebar ? Math.ceil(sidebar.getBoundingClientRect().height) : 154;
  document.documentElement.style.setProperty("--app-height", `${appHeight}px`);
  document.documentElement.style.setProperty("--keyboard-bottom", `${keyboardBottom}px`);
  document.documentElement.style.setProperty("--mobile-sidebar-height", `${sidebarHeight}px`);
  document.body.classList.toggle("keyboard-open", focusedComposer && keyboardBottom > 80);
  if (focusedComposer) {
    requestAnimationFrame(() => {
      messageInput.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  }
}

function bindViewportMetrics() {
  updateViewportMetrics();
  if (viewportMetricsBound) return;
  viewportMetricsBound = true;
  window.addEventListener("resize", updateViewportMetrics);
  window.addEventListener("orientationchange", () => setTimeout(updateViewportMetrics, 250));
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", updateViewportMetrics);
    window.visualViewport.addEventListener("scroll", updateViewportMetrics);
  }
  messageInput.addEventListener("focus", () => setTimeout(updateViewportMetrics, 120));
  messageInput.addEventListener("click", () => setTimeout(updateViewportMetrics, 120));
  window.addEventListener("nomi-pending-agent-event", consumePendingAgentEvent);
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
  if (viewId === "agendaView") loadAgenda();
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

function setChatConversationId(value) {
  chatConversationId = value || "";
  if (chatConversationId) {
    localStorage.setItem(conversationKey, chatConversationId);
  } else {
    localStorage.removeItem(conversationKey);
  }
}

async function loadChatHistory(force = false) {
  if (chatHistoryLoaded && !force) return;
  if (messages.children.length && !force) {
    chatHistoryLoaded = true;
    return;
  }
  chatHistoryLoaded = true;
  const params = new URLSearchParams();
  params.set("limit", "80");
  if (chatConversationId) params.set("conversation_id", chatConversationId);
  const query = `?${params.toString()}`;
  try {
    const result = await api(`/api/chat/history${query}`);
    if (result.conversation_id) setChatConversationId(result.conversation_id);
    messages.innerHTML = "";
    (result.messages || []).forEach((message) => {
      if (message.role === "user" || message.role === "assistant") {
        addMessage(message.role, message.content || "");
      }
    });
  } catch (error) {
    if (chatConversationId && !force) {
      setChatConversationId("");
      chatHistoryLoaded = false;
      await loadChatHistory(true);
    }
  }
}

function appendMessageText(node, text) {
  node.textContent += text;
  messages.scrollTop = messages.scrollHeight;
}

function focusMessageInputNow() {
  if (!messageInput) return;
  messageInput.focus({ preventScroll: true });
  const caret = messageInput.value.length;
  messageInput.setSelectionRange(caret, caret);
  updateViewportMetrics();
}

function refocusMessageInput() {
  if (!messageInput) return;
  requestAnimationFrame(() => {
    focusMessageInputNow();
  });
  for (const delay of [80, 240, 520]) {
    setTimeout(focusMessageInputNow, delay);
  }
}

function clearRealtimeChatWatchdog() {
  if (!realtimeChatWatchdog) return;
  clearTimeout(realtimeChatWatchdog);
  realtimeChatWatchdog = null;
}

function failActiveRealtimeChat(message) {
  clearRealtimeChatWatchdog();
  if (activeAssistantNode) {
    if (realtimeChatHadDelta) {
      appendMessageText(activeAssistantNode, `\n\n${message}`);
    } else {
      activeAssistantNode.textContent = message;
    }
  } else {
    addMessage("assistant", message);
  }
  activeAssistantNode = null;
  realtimeChatHadDelta = false;
}

function startRealtimeChatWatchdog() {
  clearRealtimeChatWatchdog();
  realtimeChatWatchdog = setTimeout(() => {
    failActiveRealtimeChat("实时回复超时，请稍后重试或检查模型服务。");
  }, realtimeTimeoutMs);
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
    if (activeAssistantNode) {
      failActiveRealtimeChat("实时通道已断开，请重新发送或检查模型服务。");
    }
    setTimeout(() => {
      if (password()) connectRealtime();
    }, 3000);
  });
  realtimeSocket.addEventListener("error", () => {
    if (activeAssistantNode) {
      failActiveRealtimeChat("实时通道发生错误，请重新发送或检查网络。");
    }
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
  if (event.type === "agent_task_delivery") {
    switchView("chatView");
    messages.appendChild(renderLongTailDelivery(event.delivery || {}, {
      taskId: event.task_id,
      effectId: event.effect_id,
    }));
    messages.scrollTop = messages.scrollHeight;
    location.hash = "chat";
    return;
  }
  if (event.type === "agent_task_fallback") {
    const fallbackDecision = event.fallback_decision || {};
    const actionCard = event.action_card || fallbackDecision.action_card;
    if (actionCard) {
      switchView("chatView");
      messages.appendChild(renderLongTailActionCard(actionCard, {
        taskId: event.task_id,
        effectId: event.effect_id,
      }));
      messages.scrollTop = messages.scrollHeight;
      location.hash = "chat";
    }
    return;
  }
  if (event.type === "chat_delta") {
    if (!activeAssistantNode) activeAssistantNode = addMessage("assistant", "");
    if (!realtimeChatHadDelta && activeAssistantNode.textContent === realtimePendingText) {
      activeAssistantNode.textContent = "";
    }
    realtimeChatHadDelta = true;
    startRealtimeChatWatchdog();
    appendMessageText(activeAssistantNode, event.delta || "");
    return;
  }
  if (event.type === "chat_done") {
    clearRealtimeChatWatchdog();
    if (event.conversation_id) setChatConversationId(event.conversation_id);
    if (activeAssistantNode && event.sources?.length) activeAssistantNode.appendChild(renderSources(event.sources));
    activeAssistantNode = null;
    realtimeChatHadDelta = false;
    return;
  }
  if (event.type === "openclaw_job_event") {
    handleOpenClawRealtimeEvent(event);
    return;
  }
  if (event.type === "error") {
    failActiveRealtimeChat(event.message || "实时通道发生错误。");
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

function consumePendingAgentEvent() {
  const raw = localStorage.getItem("nomi-pending-agent-event");
  if (!raw) return;
  localStorage.removeItem("nomi-pending-agent-event");
  try {
    const event = JSON.parse(raw);
    handleRealtimeMessage(event);
  } catch {
    switchView("chatView");
    addMessage("assistant", "收到一个长尾任务提醒，但事件内容无法解析。");
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

function renderLongTailDelivery(delivery, context = {}) {
  const node = card("message assistant long-tail-delivery");
  const message = delivery.message || "长尾任务有新的交付结果。";
  node.textContent = message;
  if ((delivery.actions || []).length) {
    const actionCard = {
      title: "需要你确认的后续操作",
      message: "这些操作只会打开 Nomi 的回滚/补偿流程，不会直接撤回或执行第三方动作。",
      actions: delivery.actions,
    };
    node.appendChild(renderLongTailActionCard(actionCard, context));
  }
  return node;
}

function renderLongTailActionCard(actionCard, context = {}) {
  const node = card("card long-tail-action-card");
  const title = document.createElement("strong");
  title.textContent = actionCard.title || "任务操作";
  const message = document.createElement("p");
  message.textContent = actionCard.message || "请选择下一步。";
  node.append(title, message);
  const actions = document.createElement("div");
  actions.className = "actions";
  for (const rawAction of actionCard.actions || []) {
    const action = { ...rawAction };
    const actionButton = button(action.label || action.id || "执行");
    actionButton.addEventListener("click", () => handleLongTailActionCardAction(action, context, node));
    actions.appendChild(actionButton);
  }
  if (actions.children.length) node.appendChild(actions);
  return node;
}

async function handleLongTailActionCardAction(action, context = {}, node) {
  const taskId = action.task_id || context.taskId;
  const effectId = action.effect_id || context.effectId;
  const status = document.createElement("p");
  status.className = "muted";
  node.appendChild(status);
  if (!taskId || !effectId) {
    status.textContent = "缺少任务或外部效果编号，无法打开补偿流程。";
    return;
  }
  if (action.id === "review_external_effect_rollback") {
    status.textContent = "读取回滚与补偿说明...";
    try {
      const result = await api(`/api/agent-tasks/${taskId}/external-effects/${effectId}/rollback`, {
        method: "POST",
      });
      status.textContent = "已读取回滚说明。";
      if (result.action_card) {
        node.appendChild(renderLongTailActionCard(result.action_card, { taskId, effectId }));
      }
    } catch {
      status.textContent = "无法读取回滚说明。";
    }
    return;
  }
  if (action.id === "prepare_compensation") {
    const reason = window.prompt("补偿操作说明", "准备一条更正或取消说明，发送前需要我再次确认。");
    if (!reason) {
      status.textContent = "已取消补偿准备。";
      return;
    }
    status.textContent = "准备补偿方案...";
    try {
      const result = await api(`/api/agent-tasks/${taskId}/external-effects/${effectId}/compensation`, {
        method: "POST",
        body: JSON.stringify({ proposal: { type: "manual_compensation_request", reason } }),
      });
      status.textContent = `补偿方案已准备：${result.status || "waiting_for_compensation_confirmation"}`;
    } catch {
      status.textContent = "补偿方案准备失败。";
    }
    return;
  }
  status.textContent = "这个任务操作暂时只能在完整任务详情中处理。";
}

async function loadDashboard() {
  await Promise.allSettled([loadAgenda(), loadSuggestions(), loadCollectors(), loadGovernance(), loadTools()]);
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
  const sourceIds = item.source_event_ids || [];
  const sourceText = sourceIds.length ? ` · 来源 ${sourceIds.length} 条证据` : " · 无来源证据";
  node.innerHTML = `<time>${item.memory_type} · ${Number(item.confidence || 0).toFixed(2)}${sourceText}</time><strong>长期记忆</strong><p>${renderJson(item.content)}${sourceIds.length ? `\nsource_event_ids: ${sourceIds.join(", ")}` : ""}</p>`;
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
  const sourceFactIds = item.source_fact_ids || [];
  const sourceText = sourceFactIds.length ? ` · 来源 ${sourceFactIds.length} 条事实` : " · 无来源事实";
  node.innerHTML = `<time>${item.key} · ${Number(item.confidence || 0).toFixed(2)}${sourceText}</time><strong>状态</strong><p>${renderJson(item.value)}${sourceFactIds.length ? `\nsource_fact_ids: ${sourceFactIds.join(", ")}` : ""}</p>`;
  const actions = document.createElement("div");
  actions.className = "actions";
  const remove = button("删除");
  remove.className = "danger";
  remove.addEventListener("click", async () => {
    await api("/memory/delete", { method: "POST", body: JSON.stringify({ state_key: item.key }) });
    node.remove();
  });
  actions.appendChild(remove);
  node.appendChild(actions);
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

function agendaStatusText(status) {
  if (status === "scheduled") return "已安排";
  if (status === "open") return "待处理";
  if (status === "done") return "已完成";
  if (status === "dismissed") return "已忽略";
  if (status === "cancelled" || status === "canceled") return "已取消";
  return status || "未知状态";
}

function agendaCertaintyText(certainty) {
  if (certainty === "exact") return "时间明确";
  if (certainty === "fuzzy") return "信息模糊";
  if (certainty === "inferred") return "推断";
  return certainty || "未标注";
}

function agendaTypeText(type) {
  if (type === "appointment") return "约定";
  if (type === "todo") return "待办";
  if (type === "deadline") return "截止";
  if (type === "payment") return "付款";
  if (type === "travel") return "出行";
  if (type === "shopping") return "购物";
  return type || "日程";
}

function missingFieldText(field) {
  const labels = {
    exact_time: "具体时间",
    exact_place: "具体地点",
    place: "地点",
    participants: "参与人",
    amount: "金额",
    due_time: "截止时间",
  };
  return labels[field] || field;
}

const agendaWeekdayLabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const agendaChineseWeekdays = { 一: 0, 二: 1, 三: 2, 四: 3, 五: 4, 六: 5, 日: 6, 天: 6 };
const agendaChineseDigits = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };

function agendaDateKeyFromDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function agendaDateFromKey(dateKey) {
  const [year, month, day] = String(dateKey || "").split("-").map((value) => Number(value));
  if (!year || !month || !day) return new Date();
  return new Date(year, month - 1, day);
}

function agendaAddDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function agendaStartOfWeek(date) {
  const day = date.getDay() || 7;
  return agendaAddDays(date, 1 - day);
}

function agendaWeekdayLabel(date) {
  return agendaWeekdayLabels[(date.getDay() + 6) % 7];
}

function agendaHourFromChinese(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (/^\d+$/.test(raw)) return Number(raw);
  if (raw === "十") return 10;
  if (raw.includes("十")) {
    const [before, after] = raw.split("十");
    const tens = before ? agendaChineseDigits[before] || 0 : 1;
    const ones = after ? agendaChineseDigits[after] || 0 : 0;
    return tens * 10 + ones;
  }
  return agendaChineseDigits[raw] ?? null;
}

function agendaTimeOfDayFromText(text) {
  const match = String(text || "").match(/(上午|下午|晚上|中午|早上)?\s*([0-2]?\d|[一二三四五六七八九十两]{1,3})\s*(?:点|[:：])\s*([0-5]?\d)?/);
  if (!match) return null;
  const period = match[1] || "";
  let hour = agendaHourFromChinese(match[2]);
  const minute = Number(match[3] || 0);
  if (hour === null || hour > 23 || minute > 59) return null;
  if ((period === "下午" || period === "晚上") && hour >= 1 && hour < 12) hour += 12;
  if (period === "中午" && hour < 11) hour += 12;
  return { hour, minute };
}

function agendaEventDate(item) {
  const timeWindow = item.time_window || {};
  const timestamp = timeWindow.source_event_timestamp || item.metadata?.event_timestamp || item.created_at;
  const parsed = timestamp ? new Date(timestamp) : new Date();
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function agendaRelativeDateFromText(text, eventDate) {
  const raw = String(text || "");
  if (raw.includes("后天")) return agendaAddDays(eventDate, 2);
  if (raw.includes("明天")) return agendaAddDays(eventDate, 1);
  if (raw.includes("今天") || raw.includes("今晚")) return eventDate;
  const weekdayMatch = raw.match(/(下周)?(?:周|星期|礼拜)([一二三四五六日天])/);
  if (!weekdayMatch) return null;
  const target = agendaChineseWeekdays[weekdayMatch[2]];
  if (target === undefined) return null;
  const current = (eventDate.getDay() + 6) % 7;
  let days = (target - current + 7) % 7;
  if (weekdayMatch[1]) days += 7;
  return agendaAddDays(eventDate, days);
}

function resolvedAgendaWindowFromRaw(item) {
  const timeWindow = item.time_window || {};
  const raw = timeWindow.raw_text || item.title || "";
  const eventDate = agendaEventDate(item);
  const targetDate = agendaRelativeDateFromText(raw, eventDate);
  if (!targetDate) return null;
  const dateKey = agendaDateKeyFromDate(targetDate);
  const weekday = agendaWeekdayLabel(targetDate);
  const time = agendaTimeOfDayFromText(raw);
  if (!time) return { date: dateKey, display: `${dateKey} ${weekday}` };
  return {
    date: dateKey,
    display: `${dateKey} ${weekday} ${String(time.hour).padStart(2, "0")}:${String(time.minute).padStart(2, "0")}`,
  };
}

function agendaDateKeyForItem(item) {
  const timeWindow = item.time_window || {};
  if (timeWindow.date) return String(timeWindow.date).slice(0, 10);
  const start = timeWindow.start || timeWindow.start_at;
  if (start) {
    const parsed = new Date(start);
    if (!Number.isNaN(parsed.getTime())) return agendaDateKeyFromDate(parsed);
    return String(start).slice(0, 10);
  }
  return resolvedAgendaWindowFromRaw(item)?.date || "";
}

function formatAgendaTimeWindow(timeWindow = {}, item = {}) {
  if (timeWindow.display) return timeWindow.display;
  const resolved = resolvedAgendaWindowFromRaw(item);
  if (resolved?.display) return resolved.display;
  if (timeWindow.date) {
    const date = agendaDateFromKey(String(timeWindow.date).slice(0, 10));
    return `${String(timeWindow.date).slice(0, 10)} ${agendaWeekdayLabel(date)}`;
  }
  const start = timeWindow.start || timeWindow.start_at;
  if (start) {
    const parsed = new Date(start);
    if (!Number.isNaN(parsed.getTime())) {
      return `${agendaDateKeyFromDate(parsed)} ${agendaWeekdayLabel(parsed)} ${String(parsed.getHours()).padStart(2, "0")}:${String(parsed.getMinutes()).padStart(2, "0")}`;
    }
    return String(start);
  }
  if (!timeWindow || typeof timeWindow !== "object") return "未记录";
  if (timeWindow.text) return timeWindow.text;
  if (timeWindow.raw_text) return timeWindow.raw_text;
  return "未记录";
}

function agendaRelativeTitleTimeText(text) {
  const raw = String(text || "");
  const patterns = [
    /(今天|今晚|明天|后天)\s*(早上|上午|中午|下午|晚上)?\s*([0-2]?\d|[一二三四五六七八九十两]{1,3})\s*(?:点|[:：])\s*([0-5]?\d)?/,
    /(下周)?\s*(?:周|星期|礼拜)([一二三四五六日天])\s*(早上|上午|中午|下午|晚上)?\s*([0-2]?\d|[一二三四五六七八九十两]{1,3})\s*(?:点|[:：])\s*([0-5]?\d)?/,
    /(今天|今晚|明天|后天)/,
    /(下周)?\s*(?:周|星期|礼拜)([一二三四五六日天])/,
  ];
  for (const pattern of patterns) {
    const match = raw.match(pattern);
    if (match?.[0]) return match[0];
  }
  return "";
}

function formatAgendaTitle(item = {}) {
  const originalTitle = item.title || "未命名日程";
  const timeWindow = item.time_window || {};
  const relativeText = timeWindow.raw_text || timeWindow.text || "";
  const resolved = resolvedAgendaWindowFromRaw(item);
  if (!resolved?.display) {
    return originalTitle;
  }
  const replacementTarget = relativeText && originalTitle.includes(relativeText)
    ? relativeText
    : agendaRelativeTitleTimeText(originalTitle);
  if (!replacementTarget) return originalTitle;
  return originalTitle
    .replace(replacementTarget, `${resolved.display} `)
    .replace(/\s+/g, " ")
    .trim();
}

async function loadAgenda() {
  agendaContent.textContent = "加载中...";
  try {
    const data = await api("/api/agenda?limit=50");
    agendaItems = data.items || [];
    if (!selectedAgendaDate) {
      selectedAgendaDate = agendaItems.map(agendaDateKeyForItem).find(Boolean) || agendaDateKeyFromDate(new Date());
    }
    renderAgenda();
  } catch {
    agendaContent.textContent = "无法读取日程。";
  }
}

function renderAgenda() {
  agendaContent.textContent = "";
  renderAgendaDayTabs();
  const activeItems = agendaItems.filter((item) => !["done", "dismissed", "cancelled", "canceled"].includes(item.status));
  const closedItems = agendaItems.filter((item) => ["done", "dismissed", "cancelled", "canceled"].includes(item.status));
  const selectedActive = activeItems.filter((item) => agendaDateKeyForItem(item) === selectedAgendaDate);
  const selectedClosed = closedItems.filter((item) => agendaDateKeyForItem(item) === selectedAgendaDate).slice(0, 8);
  const undatedItems = activeItems.filter((item) => !agendaDateKeyForItem(item)).slice(0, 8);
  renderAgendaSection("当天日程", selectedActive);
  renderAgendaSection("当天已处理", selectedClosed);
  if (!selectedActive.length && !selectedClosed.length) agendaContent.appendChild(emptyCard("当天暂无日程"));
  renderAgendaSection("时间未定", undatedItems);
}

function renderAgendaDayTabs() {
  agendaDayTabs.textContent = "";
  const selectedDate = agendaDateFromKey(selectedAgendaDate || agendaDateKeyFromDate(new Date()));
  const weekStart = agendaStartOfWeek(selectedDate);
  const counts = new Map();
  for (const item of agendaItems) {
    const dateKey = agendaDateKeyForItem(item);
    if (dateKey) counts.set(dateKey, (counts.get(dateKey) || 0) + 1);
  }
  for (let index = 0; index < 7; index += 1) {
    const date = agendaAddDays(weekStart, index);
    const dateKey = agendaDateKeyFromDate(date);
    const tab = button("");
    tab.className = `agenda-day-tab${dateKey === selectedAgendaDate ? " active" : ""}`;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", dateKey === selectedAgendaDate ? "true" : "false");
    tab.innerHTML = `<span>${agendaWeekdayLabel(date)}</span><strong>${date.getMonth() + 1}/${date.getDate()}</strong>${counts.get(dateKey) ? `<em>${counts.get(dateKey)}</em>` : ""}`;
    tab.addEventListener("click", () => {
      selectedAgendaDate = dateKey;
      renderAgenda();
    });
    agendaDayTabs.appendChild(tab);
  }
}

function renderAgendaSection(title, items) {
  if (!items.length) return;
  const heading = document.createElement("h3");
  heading.textContent = title;
  agendaContent.appendChild(heading);
  for (const item of items) agendaContent.appendChild(renderAgendaItem(item));
}

function renderAgendaItem(item) {
  const node = card("card agenda-card");
  const meta = document.createElement("time");
  meta.textContent = `${agendaTypeText(item.type)} · ${agendaStatusText(item.status)} · ${agendaCertaintyText(item.certainty)} · ${Number(item.confidence || 0).toFixed(2)}`;
  const title = document.createElement("strong");
  title.textContent = formatAgendaTitle(item);
  const detail = document.createElement("p");
  const missingFields = (item.missing_fields || []).map(missingFieldText);
  const detailLines = [
    `时间：${formatAgendaTimeWindow(item.time_window, item)}`,
    `地点：${item.place || "未记录"}`,
    `参与：${(item.participants || []).join("、") || "未记录"}`,
  ];
  if (missingFields.length) detailLines.push(`待补充：${missingFields.join("、")}`);
  if (item.metadata?.source || item.source_event_ids?.length) {
    detailLines.push(`来源：${item.metadata?.source || "本地事件"}${item.source_event_ids?.length ? ` · ${item.source_event_ids.length} 条证据` : ""}`);
  }
  detail.textContent = detailLines.join("\n");
  node.append(meta, title, detail);

  const actions = document.createElement("div");
  actions.className = "actions";
  if (!["done", "dismissed", "cancelled", "canceled"].includes(item.status)) {
    const snooze = button("稍后提醒");
    snooze.addEventListener("click", () => snoozeAgendaItem(item.id));
    const done = button("完成");
    done.addEventListener("click", () => updateAgendaItemStatus(item.id, "done"));
    const dismiss = button("忽略");
    dismiss.addEventListener("click", () => updateAgendaItemStatus(item.id, "dismissed"));
    actions.append(snooze, done, dismiss);
  }
  if (actions.children.length) node.appendChild(actions);
  return node;
}

if (typeof window !== "undefined") {
  window.nomiAgendaDebug = {
    agendaDateKeyForItem,
    formatAgendaTitle,
    formatAgendaTimeWindow,
    resolvedAgendaWindowFromRaw,
  };
}

async function updateAgendaItemStatus(id, status) {
  await api(`/api/agenda/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status, reason: `user marked agenda ${status} from workbench` }),
  });
  await loadAgenda();
}

async function snoozeAgendaItem(id) {
  const snoozedUntil = new Date(Date.now() + 60 * 60 * 1000).toISOString();
  await api(`/api/agenda/${id}/snooze`, {
    method: "POST",
    body: JSON.stringify({ snoozed_until: snoozedUntil, reason: "user snoozed from workbench" }),
  });
  await loadAgenda();
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

async function submitChatMessage() {
  const text = messageInput.value.trim();
  if (!text) return;
  messageInput.value = "";
  addMessage("user", text);
  refocusMessageInput();
  if (realtimeReady && realtimeSocket?.readyState === WebSocket.OPEN) {
    activeAssistantNode = addMessage("assistant", realtimePendingText);
    realtimeChatHadDelta = false;
    startRealtimeChatWatchdog();
    try {
      realtimeSocket.send(
        JSON.stringify({
          type: "chat_message",
          message: text,
          conversation_id: chatConversationId || undefined,
        })
      );
    } catch {
      failActiveRealtimeChat("实时通道发送失败，请重新发送或检查网络。");
    }
    refocusMessageInput();
    return;
  }
  const pendingNode = addMessage("assistant", realtimePendingText);
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message: text, conversation_id: chatConversationId || undefined }),
    });
    if (result.conversation_id) setChatConversationId(result.conversation_id);
    pendingNode.textContent = result.answer;
    if (result.sources?.length) pendingNode.appendChild(renderSources(result.sources));
  } catch {
    pendingNode.textContent = "请求失败，请检查模型服务或访问密码。";
  } finally {
    refocusMessageInput();
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitChatMessage();
});

function preserveComposerFocus(event) {
  event.preventDefault();
  refocusMessageInput();
}

chatSubmitButton.addEventListener("pointerdown", preserveComposerFocus);
chatSubmitButton.addEventListener("touchstart", preserveComposerFocus, { passive: false });
chatSubmitButton.addEventListener("mousedown", preserveComposerFocus);
chatSubmitButton.addEventListener("touchend", (event) => {
  event.preventDefault();
  lastTouchSubmitAt = Date.now();
  refocusMessageInput();
  submitChatMessage();
}, { passive: false });
chatSubmitButton.addEventListener("click", (event) => {
  event.preventDefault();
  if (Date.now() - lastTouchSubmitAt < 700) {
    refocusMessageInput();
    return;
  }
  refocusMessageInput();
  submitChatMessage();
});

messages.addEventListener("pointerdown", () => {
  messageInput.blur();
  setTimeout(updateViewportMetrics, 120);
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
refreshAgenda.addEventListener("click", loadAgenda);
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
