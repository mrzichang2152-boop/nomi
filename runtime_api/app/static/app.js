const WORKBENCH_VIEW_HASH_MAP = Object.freeze({
  chatView: "chat",
  agendaView: "agenda",
  careerView: "career",
  settingsView: "settings",
  searchView: "search",
  governanceView: "governance",
  suggestionsView: "suggestions",
  collectorsView: "collectors",
  assistantIdentitiesView: "assistant-identities",
  toolsView: "tools",
  privacyView: "privacy",
  webSearchSettingsView: "web-search",
});

const WORKBENCH_SETTINGS_SECTION_IDS = Object.freeze([
  "suggestionsView",
  "searchView",
  "governanceView",
  "collectorsView",
  "toolsView",
  "assistantIdentitiesView",
  "webSearchSettingsView",
  "privacyView",
]);

function applyWorkbenchRouteToDocument(
  root,
  { primaryViewId, settingsSectionId },
  { revealActiveSetting = false } = {}
) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  root
    .querySelectorAll(".view")
    .forEach((view) => view.classList?.toggle("active", view.id === primaryViewId));
  root
    .querySelectorAll(".nav-button")
    .forEach((button) => button.classList?.toggle("active", button.dataset?.view === primaryViewId));
  root.querySelectorAll(".settings-section").forEach((section) => {
    section.classList?.toggle(
      "active",
      primaryViewId === "settingsView" && section.id === settingsSectionId
    );
  });

  let activeSettingsButton = null;
  root.querySelectorAll(".settings-nav-button").forEach((button) => {
    const active =
      primaryViewId === "settingsView" && button.dataset?.settingsSection === settingsSectionId;
    button.classList?.toggle("active", active);
    if (active) {
      button.setAttribute?.("aria-current", "page");
      activeSettingsButton = button;
    } else {
      button.removeAttribute?.("aria-current");
    }
  });

  if (revealActiveSetting && activeSettingsButton?.scrollIntoView) {
    activeSettingsButton.scrollIntoView({
      block: "nearest",
      inline: "nearest",
      behavior: "smooth",
    });
  }
}

function createLatestRequestGate() {
  const versions = new Map();
  return {
    begin(key, parentContext = null) {
      const normalizedKey = String(key || "default");
      const version = (versions.get(normalizedKey) || 0) + 1;
      versions.set(normalizedKey, version);
      return {
        isCurrent() {
          const parentIsCurrent =
            typeof parentContext?.isCurrent !== "function" || parentContext.isCurrent();
          return parentIsCurrent && versions.get(normalizedKey) === version;
        },
      };
    },
  };
}

function isRequestParentCurrent(parentContext = null) {
  return typeof parentContext?.isCurrent !== "function" || parentContext.isCurrent();
}

async function runLatestRequest({
  gate,
  key,
  parentContext = null,
  load,
  commit,
  onError = () => {},
}) {
  if (!isRequestParentCurrent(parentContext)) return false;
  const context = gate.begin(key, parentContext);
  if (!context.isCurrent()) return false;
  try {
    const value = await load(context);
    if (!context.isCurrent()) return false;
    await commit(value, context);
    return context.isCurrent();
  } catch (error) {
    if (context.isCurrent()) {
      try {
        onError(error, context);
      } catch {
        // Error presentation must not turn a handled loader failure into an unhandled rejection.
      }
    }
    return false;
  }
}

async function runUiTask(task, onError = () => {}) {
  try {
    await task();
    return true;
  } catch (error) {
    try {
      await onError(error);
    } catch {
      // Error recovery must not create another unhandled rejection.
    }
    return false;
  }
}

function runCollectorSettingsUpdate({
  routeContext,
  actionButton,
  mutate,
  refresh,
  recover = () => {},
}) {
  const previousText = actionButton.textContent;
  actionButton.disabled = true;
  return runUiTask(
    async () => {
      await mutate();
      if (!isRequestParentCurrent(routeContext)) return false;
      await refresh(routeContext);
      return true;
    },
    async (error) => {
      actionButton.disabled = false;
      actionButton.textContent = previousText;
      await recover(error);
    }
  );
}

function createWorkbenchNavigationController({
  location,
  history,
  viewHashMap,
  settingsSectionIds,
  defaultSettingsSectionId,
  applyRoute = () => {},
  primaryLoaders = {},
  settingsLoaders = {},
  clearWebSearchKeyInput = () => {},
  onLoaderError = () => {},
}) {
  const primaryViewIds = new Set(["chatView", "agendaView", "careerView", "settingsView"]);
  const primaryReturnViewIds = ["chatView", "agendaView", "careerView"];
  const settingsIds = new Set(settingsSectionIds || []);
  const suggestionFallbacks = new Map();
  let activeRoute = null;
  let activeRouteContext = null;
  let hashChangeBinding = null;
  let activationSequence = 0;
  const pendingLoads = new Set();

  function hashForView(viewId) {
    return viewHashMap[viewId] || "";
  }

  function routeStateFromHash(hash = location.hash) {
    const routeHash = String(hash || "");
    if (routeHash.startsWith("#suggestion:")) {
      return { primaryViewId: "settingsView", settingsSectionId: "suggestionsView" };
    }
    for (const [viewId, hashValue] of Object.entries(viewHashMap)) {
      if (routeHash !== `#${hashValue}`) continue;
      if (settingsIds.has(viewId)) {
        return { primaryViewId: "settingsView", settingsSectionId: viewId };
      }
      if (primaryViewIds.has(viewId)) {
        return { primaryViewId: viewId, settingsSectionId: "" };
      }
    }
    return { primaryViewId: "", settingsSectionId: "" };
  }

  function normalizeRoute(route = {}) {
    let primaryViewId = route.primaryViewId || "";
    let settingsSectionId = route.settingsSectionId || "";
    if (settingsIds.has(primaryViewId)) {
      settingsSectionId = primaryViewId;
      primaryViewId = "settingsView";
    }
    if (!primaryViewIds.has(primaryViewId)) primaryViewId = "chatView";
    if (primaryViewId === "settingsView") {
      if (!settingsIds.has(settingsSectionId)) settingsSectionId = defaultSettingsSectionId;
    } else {
      settingsSectionId = "";
    }
    return { primaryViewId, settingsSectionId };
  }

  function isSettingsRoute(route) {
    return normalizeRoute(route).primaryViewId === "settingsView";
  }

  function safePrimaryHash(hash) {
    const candidate = String(hash || "");
    return primaryReturnViewIds.some((viewId) => `#${hashForView(viewId)}` === candidate)
      ? candidate
      : "";
  }

  function settingsEntryState(returnHash, currentState = null) {
    const base =
      currentState && typeof currentState === "object" && !Array.isArray(currentState)
        ? currentState
        : {};
    return {
      ...base,
      nomiWorkbenchSettingsEntry: true,
      nomiSettingsReturnHash: safePrimaryHash(returnHash),
    };
  }

  function settingsReturnHashFromState() {
    const state = history.state;
    if (!state || state.nomiWorkbenchSettingsEntry !== true) return "";
    return safePrimaryHash(state.nomiSettingsReturnHash);
  }

  function currentSuggestionFocusId(hash = location.hash) {
    const routeHash = String(hash || "");
    if (!routeHash.startsWith("#suggestion:")) return "";
    const encodedId = routeHash.slice("#suggestion:".length);
    try {
      return decodeURIComponent(encodedId);
    } catch {
      return encodedId;
    }
  }

  function activateRoute(route, hash = location.hash) {
    const nextRoute = normalizeRoute(route);
    const activationId = ++activationSequence;
    const loadContext = {
      activationId,
      hash: String(hash || ""),
      route: nextRoute,
      isCurrent: () => activationSequence === activationId,
    };
    activeRouteContext = loadContext;
    if (
      activeRoute?.settingsSectionId === "webSearchSettingsView" &&
      nextRoute.settingsSectionId !== "webSearchSettingsView"
    ) {
      clearWebSearchKeyInput();
    }

    applyRoute(nextRoute);
    activeRoute = nextRoute;

    let loadResult;
    let onLoadSuccess = null;
    if (nextRoute.primaryViewId === "settingsView") {
      const loader = settingsLoaders[nextRoute.settingsSectionId];
      if (loader) {
        if (nextRoute.settingsSectionId === "suggestionsView") {
          const focusSuggestionId = currentSuggestionFocusId(hash);
          const fallbackEvent = focusSuggestionId ? suggestionFallbacks.get(focusSuggestionId) || null : null;
          if (focusSuggestionId) {
            onLoadSuccess = () => suggestionFallbacks.delete(focusSuggestionId);
          }
          loadResult = invokeLoader(
            loader,
            [focusSuggestionId, fallbackEvent, loadContext],
            loadContext
          );
        } else {
          loadResult = invokeLoader(loader, [loadContext], loadContext);
        }
      }
    } else {
      const loader = primaryLoaders[nextRoute.primaryViewId];
      if (loader) loadResult = invokeLoader(loader, [loadContext], loadContext);
    }
    if (loadResult) {
      const trackedLoad = Promise.resolve(loadResult)
        .then((result) => {
          if (result !== false && loadContext.isCurrent()) onLoadSuccess?.();
          return result;
        })
        .finally(() => pendingLoads.delete(trackedLoad));
      pendingLoads.add(trackedLoad);
    }
    return nextRoute;
  }

  function invokeLoader(loader, args, context) {
    try {
      return Promise.resolve(loader(...args)).catch((error) => {
        try {
          onLoaderError(error, context);
        } catch {
          // Keep navigation stable even if a diagnostic callback fails.
        }
        return false;
      });
    } catch (error) {
      try {
        onLoaderError(error, context);
      } catch {
        // Keep navigation stable even if a diagnostic callback fails.
      }
      return Promise.resolve(false);
    }
  }

  async function whenIdle() {
    while (pendingLoads.size) {
      await Promise.all(Array.from(pendingLoads));
    }
  }

  function activateCurrentRoute() {
    return activateRoute(routeStateFromHash(location.hash), location.hash);
  }

  function currentRouteContext() {
    return activeRouteContext;
  }

  function navigateToHash(nextHash) {
    if (!nextHash) return activateCurrentRoute();
    if (String(location.hash || "") !== nextHash) {
      const currentRoute = normalizeRoute(routeStateFromHash(location.hash));
      const nextRoute = normalizeRoute(routeStateFromHash(nextHash));
      if (isSettingsRoute(currentRoute) && isSettingsRoute(nextRoute)) {
        const returnHash = settingsReturnHashFromState();
        const nextState = returnHash
          ? settingsEntryState(returnHash, history.state)
          : history.state ?? null;
        history.replaceState(nextState, "", nextHash);
      } else if (!isSettingsRoute(currentRoute) && isSettingsRoute(nextRoute)) {
        const currentHash =
          safePrimaryHash(location.hash) ||
          (currentRoute.primaryViewId === "chatView" ? `#${hashForView("chatView")}` : "");
        history.pushState(settingsEntryState(currentHash), "", nextHash);
      } else {
        history.pushState(null, "", nextHash);
      }
    }
    return activateCurrentRoute();
  }

  function exitSettings() {
    const returnHash = settingsReturnHashFromState();
    if (returnHash && typeof history.back === "function") {
      history.back();
      return;
    }
    const chatHash = `#${hashForView("chatView")}`;
    history.replaceState(null, "", chatHash);
    return activateCurrentRoute();
  }

  function navigateToView(viewId) {
    const hashValue = hashForView(viewId);
    if (!hashValue) return activateCurrentRoute();
    return navigateToHash(`#${hashValue}`);
  }

  function navigateToSuggestion(suggestionId, fallbackEvent = null) {
    const normalizedId = String(suggestionId || "").trim();
    if (!normalizedId) return navigateToView("suggestionsView");
    if (fallbackEvent) suggestionFallbacks.set(normalizedId, fallbackEvent);
    return navigateToHash(`#suggestion:${encodeURIComponent(normalizedId)}`);
  }

  function unbindHashChanges() {
    if (!hashChangeBinding) return;
    const { eventTarget, listener } = hashChangeBinding;
    hashChangeBinding = null;
    eventTarget.removeEventListener?.("hashchange", listener);
  }

  function bindHashChanges(eventTarget) {
    if (!eventTarget || typeof eventTarget.addEventListener !== "function") {
      throw new TypeError("hash change event target must support addEventListener");
    }
    if (hashChangeBinding?.eventTarget === eventTarget) return unbindHashChanges;
    unbindHashChanges();
    const listener = () => activateCurrentRoute();
    eventTarget.addEventListener("hashchange", listener);
    hashChangeBinding = { eventTarget, listener };
    return unbindHashChanges;
  }

  function shouldPreserveCurrentViewForAssistantEvent() {
    return normalizeRoute(routeStateFromHash(location.hash)).primaryViewId !== "chatView";
  }

  function renderAssistantEventWithoutStealingView(render) {
    const preserveCurrentView = shouldPreserveCurrentViewForAssistantEvent();
    const node = render();
    if (!preserveCurrentView && routeStateFromHash(location.hash).primaryViewId !== "chatView") {
      navigateToView("chatView");
    }
    return node;
  }

  function consumePendingAgentEvent(raw, { handleEvent, renderParseError }) {
    let event;
    try {
      event = JSON.parse(raw);
    } catch {
      renderAssistantEventWithoutStealingView(() =>
        renderParseError("收到一个长尾任务提醒，但事件内容无法解析。")
      );
      return;
    }
    handleEvent(event);
  }

  return {
    activateCurrentRoute,
    activateRoute,
    bindHashChanges,
    consumePendingAgentEvent,
    currentSuggestionFocusId,
    currentRouteContext,
    exitSettings,
    hashForView,
    navigateToSuggestion,
    navigateToView,
    renderAssistantEventWithoutStealingView,
    routeStateFromHash,
    shouldPreserveCurrentViewForAssistantEvent,
    whenIdle,
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    WORKBENCH_SETTINGS_SECTION_IDS,
    WORKBENCH_VIEW_HASH_MAP,
    applyWorkbenchRouteToDocument,
    createLatestRequestGate,
    createWorkbenchNavigationController,
    runCollectorSettingsUpdate,
    runLatestRequest,
    runUiTask,
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
const passwordKey = "par-password";
const conversationKey = "nomi-conversation-id";
const loginPanel = document.querySelector("#loginPanel");
const appPanel = document.querySelector("#appPanel");
const loginForm = document.querySelector("#loginForm");
const loginError = document.querySelector("#loginError");
const passwordInput = document.querySelector("#passwordInput");
const assistantSettingsToggle = document.querySelector("#assistantSettingsToggle");
const assistantSettingsClose = document.querySelector("#assistantSettingsClose");
const assistantSettingsPanel = document.querySelector("#assistantSettingsPanel");
const settingsBackButton = document.querySelector("#settingsBackButton");
const assistantCloseButton = document.querySelector("#assistantCloseButton");
const sidebar = document.querySelector(".sidebar");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const chatSubmitButton = document.querySelector("#chatForm button[type='submit']");
const attachmentButton = document.querySelector("#attachmentButton");
const attachmentInput = document.querySelector("#attachmentInput");
const attachmentTray = document.querySelector("#attachmentTray");
const AttachmentDraft = window.NomiChatAttachments || null;
const FileViewerLinks = window.NomiFileViewerLinks || null;
const messages = document.querySelector("#messages");
const chatAssistantDrafts = document.querySelector("#chatAssistantDrafts");
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
const careerContent = document.querySelector("#careerContent");
const careerResumeLibrary = document.querySelector("#careerResumeLibrary");
const careerAtsPreviewForm = document.querySelector("#careerAtsPreviewForm");
const careerAtsPreviewUrl = document.querySelector("#careerAtsPreviewUrl");
const careerAtsListPreview = document.querySelector("#careerAtsListPreview");
const careerProfileIngestForm = document.querySelector("#careerProfileIngestForm");
const careerResumeText = document.querySelector("#careerResumeText");
const careerTargetRoles = document.querySelector("#careerTargetRoles");
const careerTargetLocations = document.querySelector("#careerTargetLocations");
const careerResumeFileImportForm = document.querySelector("#careerResumeFileImportForm");
const careerResumeFile = document.querySelector("#careerResumeFile");
const suggestionsContent = document.querySelector("#suggestionsContent");
const collectorsContent = document.querySelector("#collectorsContent");
const toolsContent = document.querySelector("#toolsContent");
const assistantIdentityGmail = document.querySelector("#assistantIdentityGmail");
const assistantIdentityInbox = document.querySelector("#assistantIdentityInbox");
const assistantIdentityDrafts = document.querySelector("#assistantIdentityDrafts");
const assistantIdentityHistory = document.querySelector("#assistantIdentityHistory");
const assistantIdentityAudit = document.querySelector("#assistantIdentityAudit");
const assistantIdentityStatus = document.querySelector("#assistantIdentityStatus");
const refreshAssistantIdentities = document.querySelector("#refreshAssistantIdentities");
const webSearchProviderList = document.querySelector("#webSearchProviderList");
const webSearchConfiguredSummary = document.querySelector("#webSearchConfiguredSummary");
const webSearchProviderListPanel = document.querySelector("#webSearchProviderListPanel");
const webSearchProviderDetail = document.querySelector("#webSearchProviderDetail");
const webSearchProviderDetailTitle = document.querySelector("#webSearchProviderDetailTitle");
const webSearchProviderDescription = document.querySelector("#webSearchProviderDescription");
const webSearchProviderHealth = document.querySelector("#webSearchProviderHealth");
const webSearchProviderSource = document.querySelector("#webSearchProviderSource");
const webSearchProviderKeyHint = document.querySelector("#webSearchProviderKeyHint");
const webSearchKeyInput = document.querySelector("#webSearchKeyInput");
const webSearchToggleKeyVisibility = document.querySelector("#webSearchToggleKeyVisibility");
const webSearchSaveAndTest = document.querySelector("#webSearchSaveAndTest");
const webSearchTestStored = document.querySelector("#webSearchTestStored");
const webSearchDeleteKey = document.querySelector("#webSearchDeleteKey");
const webSearchEnabledToggle = document.querySelector("#webSearchEnabledToggle");
const webSearchProviderStatus = document.querySelector("#webSearchProviderStatus");
const webSearchLastTestedAt = document.querySelector("#webSearchLastTestedAt");
const webSearchProviderBack = document.querySelector("#webSearchProviderBack");
const webSearchRoutingStrategy = document.querySelector("#webSearchRoutingStrategy");
const webSearchRoutingOrder = document.querySelector("#webSearchRoutingOrder");
const webSearchSaveRouting = document.querySelector("#webSearchSaveRouting");
const webSearchRoutingStatus = document.querySelector("#webSearchRoutingStatus");
const webSearchConfigVersion = document.querySelector("#webSearchConfigVersion");
const refreshGovernance = document.querySelector("#refreshGovernance");
const refreshAgenda = document.querySelector("#refreshAgenda");
const refreshCareer = document.querySelector("#refreshCareer");
const careerOffers = document.querySelector("#careerOffers");
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
let webSearchSettingsState = null;
let selectedWebSearchProvider = "";
function conversationIdFromUrl() {
  const search = window.location?.search || "";
  if (typeof URLSearchParams === "function") {
    const params = new URLSearchParams(search);
    return (params.get("conversation_id") || "").trim();
  }
  const rawQuery = search.startsWith("?") ? search.slice(1) : search;
  for (const part of rawQuery.split("&")) {
    const [key, value = ""] = part.split("=");
    if (key === "conversation_id") {
      return decodeURIComponent(value.replace(/\+/g, " ")).trim();
    }
  }
  return "";
}

let chatConversationId = conversationIdFromUrl() || localStorage.getItem(conversationKey) || "";
let chatHistoryLoaded = false;
let viewportMetricsBound = false;
let realtimeChatWatchdog = null;
let realtimeChatHadDelta = false;
let lastTouchSubmitAt = 0;
const attachmentDraft = AttachmentDraft ? AttachmentDraft.createDraftState() : { items: [], in_flight_request_id: null };
const attachmentPollTimers = new Map();
let attachmentTrayError = "";
let activeChatAttempt = null;
const openClawJobCards = new Map();
const assistantDraftActionsInFlight = new Set();
const realtimePendingText = "正在结合本地记忆思考...";
const realtimeTimeoutMs = 45000;
const browserLoginChannels = [
  {
    source: "whatsapp",
    name: "WhatsApp",
    url: "https://web.whatsapp.com/",
    description: "在服务器托管浏览器中扫码登录 WhatsApp Web，用于可见聊天采集和关系推进。",
  },
  {
    source: "telegram",
    name: "Telegram",
    url: "https://web.telegram.org/",
    description: "在服务器托管浏览器中登录 Telegram Web，用于可见会话采集和提醒。",
  },
  {
    source: "linkedin",
    name: "LinkedIn",
    url: "https://www.linkedin.com/login",
    description: "在服务器托管浏览器中登录 LinkedIn，用于岗位、招聘方和求职 Pipeline。",
  },
  {
    source: "search",
    name: "Google Search",
    url: "https://www.google.com/",
    description: "打开云端浏览器搜索入口，用于人工辅助验证网页采集状态。",
  },
  {
    source: "shopping",
    name: "Amazon / Shopping",
    url: "https://www.amazon.com/",
    description: "打开云端浏览器购物入口，后续工具执行仍需要确认。",
  },
];
const viewHashMap = WORKBENCH_VIEW_HASH_MAP;
const defaultSettingsSectionId = "suggestionsView";
const settingsSectionIds = new Set(WORKBENCH_SETTINGS_SECTION_IDS);
const workbenchRequestGate = createLatestRequestGate();
const workbenchNavigation = createWorkbenchNavigationController({
  location,
  history: window.history,
  viewHashMap,
  settingsSectionIds: Array.from(settingsSectionIds),
  defaultSettingsSectionId,
  applyRoute: (route) => applyWorkbenchRoute(route),
  primaryLoaders: {
    chatView: (context) => loadChatAssistantDrafts(context),
    agendaView: (context) => loadAgenda(context),
    careerView: (context) => loadCareerBoard(context),
  },
  settingsLoaders: {
    suggestionsView: (focusSuggestionId, fallbackEvent, context) =>
      loadSuggestions(focusSuggestionId, fallbackEvent, context),
    governanceView: (context) => loadGovernance(context),
    collectorsView: (context) => loadCollectors(context),
    toolsView: (context) => loadTools(context),
    assistantIdentitiesView: (context) => loadAssistantIdentities(context),
    webSearchSettingsView: (context) => loadWebSearchSettings(context),
  },
  clearWebSearchKeyInput: () => clearWebSearchKeyInput(),
  onLoaderError: (error, context) => {
    console.error("Unable to load workbench route", context?.route, error);
  },
});

function hashForView(viewId) {
  return workbenchNavigation.hashForView(viewId);
}

function routeStateFromHash(hash = location.hash) {
  return workbenchNavigation.routeStateFromHash(hash);
}

function viewIdFromHash(hash = location.hash) {
  return routeStateFromHash(hash).primaryViewId;
}

function setHashForView(viewId) {
  return workbenchNavigation.navigateToView(viewId);
}

function shouldPreserveCurrentViewForAssistantEvent() {
  return workbenchNavigation.shouldPreserveCurrentViewForAssistantEvent();
}

function renderAssistantEventWithoutStealingView(render) {
  const node = workbenchNavigation.renderAssistantEventWithoutStealingView(render);
  messages.scrollTop = messages.scrollHeight;
  return node;
}

function currentSuggestionFocusId() {
  return workbenchNavigation.currentSuggestionFocusId();
}

function cssEscapeValue(value) {
  if (typeof CSS !== "undefined" && CSS.escape) return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

function password() {
  return localStorage.getItem(passwordKey) || "";
}

function showApp() {
  loginPanel.classList.add("hidden");
  appPanel.classList.remove("hidden");
  if (conversationIdFromUrl()) setChatConversationId(conversationIdFromUrl());
  bindViewportMetrics();
  connectRealtime();
  workbenchNavigation.activateCurrentRoute();
  loadChatHistory().finally(() => {
    consumePendingProactive();
    consumePendingAgentEvent();
  });
}

function toggleAssistantSettings(forceOpen = null) {
  if (!assistantSettingsPanel || !assistantSettingsToggle) return;
  const shouldOpen = forceOpen === null ? assistantSettingsPanel.classList.contains("hidden") : Boolean(forceOpen);
  assistantSettingsPanel.classList.toggle("hidden", !shouldOpen);
  assistantSettingsToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function closeAssistantWorkspace() {
  if (window.NomiAndroid?.closeWorkspace) {
    window.NomiAndroid.closeWorkspace();
    return;
  }
  window.history.back();
}

function computeViewportMetrics({
  focusedComposer,
  rawViewportHeight,
  viewportOffsetTop = 0,
  innerHeight,
  screenHeight = 0,
}) {
  const keyboardThreshold = 80;
  const height = innerHeight || rawViewportHeight || 0;
  const rawHeight = rawViewportHeight || height;
  let keyboardBottom = Math.max(0, Math.round(height - rawHeight - viewportOffsetTop));
  const screenGap = screenHeight ? Math.max(0, Math.round(screenHeight - height)) : 0;
  const alreadyResizedForKeyboard =
    focusedComposer && keyboardBottom < keyboardThreshold && screenGap > Math.max(120, Math.round(height * 0.18));

  if (
    focusedComposer &&
    keyboardBottom < keyboardThreshold &&
    rawHeight >= height - 8 &&
    !alreadyResizedForKeyboard
  ) {
    keyboardBottom = Math.round(height * 0.38);
  }
  const appHeight = Math.max(
    320,
    Math.round(keyboardBottom > keyboardThreshold ? height - keyboardBottom : rawHeight || height || 0)
  );

  return {
    appHeight,
    keyboardBottom,
    keyboardLikelyOpen: focusedComposer && (keyboardBottom > keyboardThreshold || alreadyResizedForKeyboard),
    alreadyResizedForKeyboard,
  };
}

window.nomiViewportDebug = { computeViewportMetrics };

function updateViewportMetrics() {
  const viewport = window.visualViewport;
  const focusedComposer = document.activeElement === messageInput;
  const rawViewportHeight = viewport ? viewport.height : window.innerHeight;
  const metrics = computeViewportMetrics({
    focusedComposer,
    rawViewportHeight,
    viewportOffsetTop: viewport ? viewport.offsetTop : 0,
    innerHeight: window.innerHeight,
    screenHeight: window.screen ? window.screen.height : 0,
  });
  const sidebarHeight = sidebar ? Math.ceil(sidebar.getBoundingClientRect().height) : 154;
  document.documentElement.style.setProperty("--app-height", `${metrics.appHeight}px`);
  document.documentElement.style.setProperty("--keyboard-bottom", `${metrics.keyboardBottom}px`);
  document.documentElement.style.setProperty("--mobile-sidebar-height", `${sidebarHeight}px`);
  document.body.classList.toggle("keyboard-open", metrics.keyboardLikelyOpen);
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
  if (!response.ok) {
    const rawError = await response.text();
    if (
      path.startsWith("/api/integrations/composio/") &&
      typeof window.NomiComposioGuidance?.createApiError === "function"
    ) {
      throw window.NomiComposioGuidance.createApiError(response.status, rawError);
    }
    throw new Error(rawError);
  }
  return response.json();
}

function applyWorkbenchRoute({ primaryViewId, settingsSectionId }) {
  applyWorkbenchRouteToDocument(
    document,
    { primaryViewId, settingsSectionId },
    { revealActiveSetting: window.matchMedia?.("(max-width: 860px)")?.matches === true }
  );
}

function switchView(primaryViewId, settingsSectionId = "") {
  return workbenchNavigation.activateRoute({ primaryViewId, settingsSectionId });
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

function isArtifactDownloadUrl(url) {
  try {
    const parsed = new URL(String(url || "").trim(), location.href);
    return /^\/api\/artifacts\/[A-Za-z0-9_-]+\/download\/?$/.test(parsed.pathname);
  } catch {
    return false;
  }
}

function artifactFilenameFromMessage(text) {
  const body = String(text || "");
  const patterns = [
    /(?:已生成|生成的?)\s*(?:PPTX?|Word|Excel)?\s*文件\s*[:：]\s*([^\r\n]+)/i,
    /(?:PPTX?|Word|Excel|文件)\s*[:：]\s*([^\r\n]+\.(?:pptx|docx|xlsx|pdf))/i,
  ];
  for (const pattern of patterns) {
    const match = body.match(pattern);
    const candidate = String(match?.[1] || "").trim();
    if (candidate && !/^https?:\/\//i.test(candidate)) return candidate;
  }
  return "";
}

function openInternalFileViewer({ source, filename = "", mimeType = "" } = {}) {
  if (!FileViewerLinks) return false;
  const viewerUrl = FileViewerLinks.buildViewerUrl({ source, filename, mimeType }, location.origin);
  if (!viewerUrl) return false;
  if (window.NomiAndroid && typeof window.NomiAndroid.openFileViewer === "function") {
    window.NomiAndroid.openFileViewer(viewerUrl);
    return true;
  }
  const opened = window.open(viewerUrl, "_blank", "noopener");
  if (!opened) location.href = viewerUrl;
  return true;
}

function trimUrlPunctuation(value) {
  return String(value || "").replace(/[),.，。；;！!？?]+$/g, "");
}

function renderMessageContent(node, text) {
  const body = String(text || "");
  const filename = artifactFilenameFromMessage(body);
  const urlPattern = /https?:\/\/[^\s<>"']+/gi;
  let cursor = 0;
  let match;
  node.textContent = "";
  while ((match = urlPattern.exec(body)) !== null) {
    const url = trimUrlPunctuation(match[0]);
    if (!url) continue;
    node.appendChild(document.createTextNode(body.slice(cursor, match.index)));
    const anchor = document.createElement("a");
    anchor.href = url;
    if (isArtifactDownloadUrl(url)) {
      anchor.className = "artifact-view-link";
      anchor.textContent = `点击查看${filename ? `：${filename}` : "文件"}`;
      anchor.addEventListener("click", (event) => {
        if (openInternalFileViewer({ source: url, filename })) {
          event.preventDefault();
        }
      });
    } else {
      anchor.target = "_blank";
      anchor.rel = "noopener";
      anchor.textContent = url;
    }
    node.appendChild(anchor);
    const trailingPunctuation = match[0].slice(url.length);
    if (trailingPunctuation) node.appendChild(document.createTextNode(trailingPunctuation));
    cursor = match.index + match[0].length;
  }
  node.appendChild(document.createTextNode(body.slice(cursor)));
}

function formatAttachmentSize(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function attachmentStatusText(item) {
  return {
    selected: "等待上传",
    uploading: "正在上传",
    uploaded: "等待处理",
    queued: "等待处理",
    processing: "正在处理",
    ready: "可发送",
    failed: "处理失败",
    rejected: "已拒绝",
    expired: "已过期",
  }[item.status] || item.status || "未知状态";
}

function attachmentIndex(item) {
  return attachmentDraft.items.indexOf(item);
}

function updateAttachmentControls() {
  if (!AttachmentDraft) return;
  const sending = Boolean(attachmentDraft.in_flight_request_id);
  attachmentButton.disabled = sending;
  attachmentInput.disabled = sending;
  chatSubmitButton.disabled = !AttachmentDraft.canSend(messageInput.value, attachmentDraft);
}

function setAttachmentTrayError(message = "") {
  attachmentTrayError = message;
  renderAttachmentTray();
}

function renderAttachmentTray() {
  if (!AttachmentDraft) return;
  attachmentTray.replaceChildren();
  if (attachmentTrayError) {
    const error = document.createElement("p");
    error.className = "attachment-tray-error";
    error.textContent = attachmentTrayError;
    attachmentTray.appendChild(error);
  }
  for (const item of attachmentDraft.items) {
    const draft = document.createElement("article");
    draft.className = "attachment-draft";
    draft.dataset.clientUploadId = item.client_upload_id;

    const copy = document.createElement("div");
    copy.className = "attachment-draft-copy";
    const filename = document.createElement("span");
    filename.className = "attachment-filename";
    filename.textContent = item.filename;
    const meta = document.createElement("p");
    meta.className = "attachment-meta";
    meta.textContent = `${formatAttachmentSize(item.byte_size)} · ${attachmentStatusText(item)}`;
    copy.append(filename, meta);
    if (item.error_message) {
      const error = document.createElement("p");
      error.className = "attachment-error";
      error.textContent = item.error_message;
      copy.appendChild(error);
    }

    const actions = document.createElement("div");
    actions.className = "attachment-draft-actions";
    if (["failed", "rejected", "expired"].includes(item.status)) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "attachment-retry";
      retry.title = "重试附件";
      retry.setAttribute("aria-label", `重试 ${item.filename}`);
      retry.textContent = "↻";
      retry.addEventListener("click", () => retryAttachment(item));
      actions.appendChild(retry);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-remove";
    remove.title = "移除附件";
    remove.setAttribute("aria-label", `移除 ${item.filename}`);
    remove.textContent = "×";
    remove.disabled = Boolean(attachmentDraft.in_flight_request_id);
    remove.addEventListener("click", () => removeAttachment(item));
    actions.appendChild(remove);
    draft.append(copy, actions);

    if (["uploading", "uploaded", "queued", "processing"].includes(item.status)) {
      const progress = document.createElement("div");
      progress.className = "attachment-progress";
      progress.role = "progressbar";
      progress.setAttribute("aria-label", `${item.filename} ${attachmentStatusText(item)}`);
      draft.appendChild(progress);
    }
    attachmentTray.appendChild(draft);
  }
  attachmentTray.hidden = !attachmentTray.childElementCount;
  updateAttachmentControls();
}

async function attachmentApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "x-par-password": password(),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let message = "附件请求失败。";
    const rawError = await response.text();
    try {
      const payload = JSON.parse(rawError);
      message = payload.detail?.message || payload.detail?.code || payload.message || message;
    } catch {
      if (rawError && !/^<!doctype|^<html/i.test(rawError.trim())) message = rawError;
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function clearAttachmentPoll(item) {
  const timer = attachmentPollTimers.get(item.client_upload_id);
  if (timer) clearTimeout(timer);
  attachmentPollTimers.delete(item.client_upload_id);
}

function scheduleAttachmentPoll(item) {
  clearAttachmentPoll(item);
  if (!AttachmentDraft.shouldPoll(item, document.visibilityState !== "hidden")) return;
  attachmentPollTimers.set(item.client_upload_id, setTimeout(() => pollAttachment(item), 1000));
}

async function pollAttachment(item) {
  const index = attachmentIndex(item);
  if (index < 0 || !AttachmentDraft.shouldPoll(item, document.visibilityState !== "hidden")) return;
  try {
    const status = await attachmentApi(`/api/chat/attachments/${item.attachment_id}`);
    if (status.status === "ready") {
      AttachmentDraft.markReady(attachmentDraft, index, status);
    } else if (["failed", "rejected", "expired", "deleted"].includes(status.status)) {
      AttachmentDraft.markFailed(attachmentDraft, index, status);
    } else {
      AttachmentDraft.markUploaded(attachmentDraft, index, status);
    }
  } catch (error) {
    AttachmentDraft.markFailed(attachmentDraft, index, { error_message: error.message });
  }
  renderAttachmentTray();
  scheduleAttachmentPoll(item);
}

async function uploadAttachment(item) {
  const index = attachmentIndex(item);
  if (index < 0) return;
  AttachmentDraft.markUploading(attachmentDraft, index);
  renderAttachmentTray();
  const form = new FormData();
  form.append("file", item.file, item.filename);
  form.append("client_upload_id", item.client_upload_id);
  try {
    const uploaded = await attachmentApi("/api/chat/attachments", { method: "POST", body: form });
    const currentIndex = attachmentIndex(item);
    if (currentIndex < 0) return;
    AttachmentDraft.markUploaded(attachmentDraft, currentIndex, uploaded);
    renderAttachmentTray();
    scheduleAttachmentPoll(item);
  } catch (error) {
    const currentIndex = attachmentIndex(item);
    if (currentIndex >= 0) {
      AttachmentDraft.markFailed(attachmentDraft, currentIndex, { error_message: error.message });
      renderAttachmentTray();
    }
  }
}

async function retryAttachment(item) {
  const index = attachmentIndex(item);
  if (index < 0) return;
  const priorAttachmentId = item.attachment_id;
  AttachmentDraft.retryItem(attachmentDraft, index);
  renderAttachmentTray();
  if (!priorAttachmentId) {
    await uploadAttachment(item);
    return;
  }
  try {
    const retried = await attachmentApi(`/api/chat/attachments/${priorAttachmentId}/retry`, { method: "POST" });
    const currentIndex = attachmentIndex(item);
    if (currentIndex < 0) return;
    AttachmentDraft.markUploaded(attachmentDraft, currentIndex, retried);
    renderAttachmentTray();
    scheduleAttachmentPoll(item);
  } catch (error) {
    const currentIndex = attachmentIndex(item);
    if (currentIndex >= 0) {
      AttachmentDraft.markFailed(attachmentDraft, currentIndex, { error_message: error.message });
      renderAttachmentTray();
    }
  }
}

async function removeAttachment(item) {
  const index = attachmentIndex(item);
  if (index < 0) return;
  clearAttachmentPoll(item);
  AttachmentDraft.removeItem(attachmentDraft, index);
  renderAttachmentTray();
  if (item.attachment_id) {
    try {
      await attachmentApi(`/api/chat/attachments/${item.attachment_id}`, { method: "DELETE" });
    } catch (error) {
      setAttachmentTrayError(`未能从服务器清理 ${item.filename}：${error.message}`);
    }
  }
}

async function loadAuthenticatedAttachmentBlob(url) {
  const response = await fetch(url, { headers: { "x-par-password": password() } });
  if (!response.ok) throw new Error("附件内容加载失败。");
  return response.blob();
}

function revokeObjectUrlsWithin(node) {
  if (!(node instanceof Element)) return;
  const targets = node.matches("[data-object-url]") ? [node] : Array.from(node.querySelectorAll("[data-object-url]"));
  for (const target of targets) {
    if (target.dataset.objectUrl) URL.revokeObjectURL(target.dataset.objectUrl);
  }
}

if (typeof MutationObserver === "function") {
  new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.removedNodes) revokeObjectUrlsWithin(node);
    }
  }).observe(messages, { childList: true, subtree: true });
}

async function loadAttachmentThumbnail(image, fallback, url) {
  try {
    const blob = await loadAuthenticatedAttachmentBlob(url);
    if (!fallback.isConnected) return;
    const objectUrl = URL.createObjectURL(blob);
    image.dataset.objectUrl = objectUrl;
    image.src = objectUrl;
    fallback.replaceWith(image);
  } catch {
    image.remove();
  }
}

function renderMessageAttachments(attachments = []) {
  const list = document.createElement("div");
  list.className = "message-attachments";
  for (const attachment of attachments) {
    const cardNode = document.createElement("button");
    cardNode.type = "button";
    cardNode.className = "message-attachment-card";
    cardNode.addEventListener("click", () => {
      if (!openInternalFileViewer({
        source: attachment.content_url,
        filename: attachment.filename,
        mimeType: attachment.mime_type,
      })) {
        addMessage("assistant", `无法打开附件 ${attachment.filename || ""}，请稍后重试。`);
      }
    });
    if (attachment.kind === "image" && attachment.preview_url) {
      const fallback = document.createElement("span");
      fallback.className = "attachment-file-icon attachment-preview-fallback";
      fallback.textContent = "image";
      const image = document.createElement("img");
      image.className = "attachment-thumbnail";
      image.alt = "";
      cardNode.appendChild(fallback);
      loadAttachmentThumbnail(image, fallback, attachment.preview_url);
    } else {
      const icon = document.createElement("span");
      icon.className = "attachment-file-icon";
      icon.textContent = (attachment.kind || "file").slice(0, 4);
      cardNode.appendChild(icon);
    }
    const copy = document.createElement("span");
    copy.className = "message-attachment-copy";
    const filename = document.createElement("span");
    filename.className = "attachment-filename";
    filename.textContent = attachment.filename || "attachment";
    const meta = document.createElement("span");
    meta.className = "attachment-meta";
    meta.textContent = `${attachment.mime_type || attachment.kind || "file"} · ${formatAttachmentSize(attachment.byte_size)} · ${attachmentStatusText(attachment)}`;
    copy.append(filename, meta);
    cardNode.appendChild(copy);
    list.appendChild(cardNode);
  }
  return list;
}


function ensureChatAssistantDraftRegion() {
  if (!messages || !chatAssistantDrafts) return;
  if (chatAssistantDrafts.parentElement !== messages) {
    messages.appendChild(chatAssistantDrafts);
  }
}

function addMessage(role, text, sources = [], attachments = [], messageId = "") {
  const item = card(`message ${role}`);
  renderMessageContent(item, text);
  if (messageId) item.dataset.messageId = messageId;
  if (attachments.length) item.appendChild(renderMessageAttachments(attachments));
  if (sources.length) item.appendChild(renderSources(sources));
  ensureChatAssistantDraftRegion();
  if (chatAssistantDrafts?.parentElement === messages) {
    messages.insertBefore(item, chatAssistantDrafts);
  } else {
    messages.appendChild(item);
  }
  messages.scrollTop = messages.scrollHeight;
  return item;
}

function jobRecommendationItemsFromEvent(event = {}) {
  const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const candidates = metadata.recommended_jobs || event.recommended_jobs || [];
  return Array.isArray(candidates) ? candidates.filter((job) => job && typeof job === "object") : [];
}

function compactUrlText(url = "") {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`.replace(/\/$/, "");
  } catch {
    return url;
  }
}

function openExternalUrl(url) {
  const value = String(url || "").trim();
  if (!/^https?:\/\//i.test(value)) return false;
  if (window.NomiAndroid && typeof window.NomiAndroid.openExternalUrl === "function") {
    window.NomiAndroid.openExternalUrl(value);
    return true;
  }
  window.open(value, "_blank", "noopener");
  return true;
}

function enterRemoteBrowserMode() {
  if (window.NomiAndroid && typeof window.NomiAndroid.enterRemoteBrowserMode === "function") {
    window.NomiAndroid.enterRemoteBrowserMode();
    return true;
  }
  return false;
}

function vncPassword() {
  const value = password().trim();
  if (!value) return "";
  return value.endsWith("-vnc") ? value : `${value}-vnc`;
}

function remoteBrowserUrl() {
  const protocol = window.location?.protocol || "http:";
  const hostname = window.location?.hostname || "";
  if (!hostname) return "";
  const params = new URLSearchParams({
    autoconnect: "1",
    resize: "scale",
    quality: "6",
    compression: "2",
    show_dot: "1",
    password: vncPassword(),
  });
  return `${protocol}//${hostname}:6080/vnc.html?${params.toString()}`;
}

function renderChipList(values = [], className = "job-recommendation-chips") {
  const list = document.createElement("div");
  list.className = className;
  for (const value of values.filter(Boolean).slice(0, 6)) {
    const chip = document.createElement("span");
    chip.textContent = value;
    list.appendChild(chip);
  }
  return list;
}

function renderProactiveJobRecommendationCard(event = {}) {
  const jobs = jobRecommendationItemsFromEvent(event);
  if (!jobs.length) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "job-recommendation-card";

  const intro = document.createElement("p");
  intro.className = "job-recommendation-intro";
  intro.textContent = (event.body || event.message || "").split("\n\n")[0]
    || `发现 ${jobs.length} 个较匹配岗位。`;
  wrapper.appendChild(intro);

  for (const job of jobs.slice(0, 3)) {
    const jobNode = document.createElement("section");
    jobNode.className = "job-recommendation-item";

    const title = document.createElement("strong");
    title.textContent = [job.title, job.company].filter(Boolean).join(" @ ") || "推荐岗位";
    jobNode.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "job-recommendation-meta";
    const metaParts = [];
    if (job.location) metaParts.push(`地点：${job.location}`);
    if (job.fit_score !== undefined && job.fit_score !== null) {
      metaParts.push(`匹配度：${Number(job.fit_score).toFixed(2)}${job.recommendation_tier ? `（${job.recommendation_tier}）` : ""}`);
    }
    meta.textContent = metaParts.join(" · ");
    if (meta.textContent) jobNode.appendChild(meta);

    if (job.summary) {
      const summary = document.createElement("p");
      summary.className = "job-recommendation-summary";
      summary.textContent = job.summary;
      jobNode.appendChild(summary);
    }

    if (Array.isArray(job.recommendation_reasons) && job.recommendation_reasons.length) {
      const reasonsLabel = document.createElement("p");
      reasonsLabel.className = "job-recommendation-label";
      reasonsLabel.textContent = "推荐理由";
      jobNode.append(reasonsLabel, renderChipList(job.recommendation_reasons));
    }

    if (Array.isArray(job.gap_requirements) && job.gap_requirements.length) {
      const gaps = document.createElement("p");
      gaps.className = "job-recommendation-gap";
      gaps.textContent = `主要缺口：${job.gap_requirements.join("、")}`;
      jobNode.appendChild(gaps);
    }

    if (job.url) {
      const linkRow = document.createElement("p");
      linkRow.className = "job-recommendation-url-row";
      const anchor = document.createElement("a");
      anchor.className = "job-recommendation-link";
      anchor.href = job.url;
      anchor.target = "_blank";
      anchor.rel = "noopener";
      anchor.textContent = `打开岗位链接：${compactUrlText(job.url)}`;
      anchor.addEventListener("click", (event) => {
        if (openExternalUrl(job.url)) event.preventDefault();
      });
      linkRow.appendChild(anchor);
      jobNode.appendChild(linkRow);
    }

    wrapper.appendChild(jobNode);
  }

  return wrapper;
}

function addProactiveSuggestionCard(event = {}) {
  const item = card("message assistant suggestion-inline-card");
  const label = document.createElement("time");
  label.textContent = event.title || "可能需要关注";
  const body = document.createElement("p");
  body.textContent = event.body || event.message || "Nomi 发现一条可能值得处理的事项。";
  const jobCard = renderProactiveJobRecommendationCard(event);
  const actions = document.createElement("div");
  actions.className = "actions";

  const suggestionId = event.suggestion_id || event.id || "";
  const review = button("查看详情");
  review.addEventListener("click", () => {
    workbenchNavigation.navigateToSuggestion(suggestionId, event);
    toggleAssistantSettings(false);
  });
  actions.appendChild(review);

  if (event.action_hint) {
    const hint = button(event.action_hint);
    hint.addEventListener("click", () => {
      messageInput.value = event.action_hint;
      refocusMessageInput();
    });
    actions.appendChild(hint);
  }
  const eventActions = event.actions || event.metadata?.actions;
  if (Array.isArray(eventActions)) {
    for (const rawAction of eventActions) {
      const action = normalizeSuggestionAction(rawAction);
      if (!action || !action.url) continue;
      const actionButton = button(action.label);
      actionButton.addEventListener("click", () => openExternalUrl(action.url));
      actions.appendChild(actionButton);
    }
  }

  item.append(label, jobCard || body, actions);
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
  notifyAndroidConversationId();
}

function notifyAndroidConversationId() {
  if (window.NomiAndroid?.updateConversationId) {
    try {
      window.NomiAndroid.updateConversationId(chatConversationId);
    } catch {
      // Android bridge failures should not block the web chat UI.
    }
  }
}

async function loadChatHistory(force = false) {
  if (chatHistoryLoaded && !force) return;
  if (messages.querySelector(".message") && !force) {
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
    ensureChatAssistantDraftRegion();
    (result.messages || []).forEach((message) => {
      if (message.role === "user" || message.role === "assistant") {
        addMessage(message.role, message.content || "", [], message.attachments || [], message.id || "");
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
  if (activeChatAttempt && AttachmentDraft) {
    AttachmentDraft.markTransportFailed(attachmentDraft);
    renderAttachmentTray();
  }
  if (activeAssistantNode) {
    if (realtimeChatHadDelta) {
      appendMessageText(activeAssistantNode, `\n\n${message}`);
    } else {
      activeAssistantNode.textContent = message;
    }
  } else {
    activeAssistantNode = addMessage("assistant", message);
  }
  if (activeChatAttempt && activeAssistantNode) renderAssistantRetry(activeAssistantNode);
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
    renderAssistantEventWithoutStealingView(() => addProactiveSuggestionCard(event));
    return;
  }
  if (event.type === "agent_task_delivery") {
    renderAssistantEventWithoutStealingView(() => messages.appendChild(renderLongTailDelivery(event.delivery || {}, {
      taskId: event.task_id,
      effectId: event.effect_id,
    })));
    return;
  }
  if (event.type === "agent_task_fallback") {
    const fallbackDecision = event.fallback_decision || {};
    const actionCard = event.action_card || fallbackDecision.action_card;
    if (actionCard) {
      renderAssistantEventWithoutStealingView(() => messages.appendChild(renderLongTailActionCard(actionCard, {
        taskId: event.task_id,
        effectId: event.effect_id,
      })));
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
    if (activeAssistantNode) renderMessageContent(activeAssistantNode, activeAssistantNode.textContent);
    if (activeAssistantNode && event.sources?.length) activeAssistantNode.appendChild(renderSources(event.sources));
    if (activeChatAttempt && event.client_request_id === activeChatAttempt.payload.client_request_id) {
      AttachmentDraft.commitSend(attachmentDraft, event.client_request_id);
      activeChatAttempt = null;
      renderAttachmentTray();
    }
    activeAssistantNode = null;
    realtimeChatHadDelta = false;
    void loadChatAssistantDrafts();
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
    renderAssistantEventWithoutStealingView(() => addProactiveSuggestionCard(event));
  } catch {
    addMessage("assistant", raw);
  }
}

function consumePendingAgentEvent() {
  const raw = localStorage.getItem("nomi-pending-agent-event");
  if (!raw) return;
  localStorage.removeItem("nomi-pending-agent-event");
  workbenchNavigation.consumePendingAgentEvent(raw, {
    handleEvent: (event) => handleRealtimeMessage(event),
    renderParseError: (message) => addMessage("assistant", message),
  });
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
  renderMessageContent(node, message);
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

async function loadGovernance(parentContext = null) {
  if (!governanceContent) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  governanceContent.textContent = "加载中...";
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "governance",
    parentContext,
    load: async () => {
      const query = governanceQueryString();
      const traceQuery = new URLSearchParams();
      if (governanceQuery?.value.trim()) traceQuery.set("q", governanceQuery.value.trim());
      traceQuery.set("limit", "20");
      const [data, routeTraceData] = await Promise.all([
        api(`/api/memory/governance${query ? `?${query}` : ""}`),
        api(`/api/tools/route/traces?${traceQuery.toString()}`),
      ]);
      return { data, routeTraceData };
    },
    commit: ({ data, routeTraceData }) => {
      governanceContent.textContent = "";
      renderGovernanceSection("事件审计", data.events || [], renderEventGovernanceItem);
      renderGovernanceSection("长期记忆", data.semantic_memory || [], renderSemanticGovernanceItem);
      renderGovernanceSection("状态记忆", data.states || [], renderStateGovernanceItem);
      renderGovernanceSection("任务路由", routeTraceData.traces || [], renderRouteTraceGovernanceItem);
      if (!governanceContent.children.length) governanceContent.appendChild(emptyCard("暂无治理项"));
    },
    onError: () => {
      governanceContent.textContent = "无法读取治理数据。";
    },
  });
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

async function loadAgenda(parentContext = null) {
  if (!agendaContent) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  agendaContent.textContent = "加载中...";
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "agenda",
    parentContext,
    load: () => api("/api/agenda?limit=50"),
    commit: (data) => {
      agendaItems = data.items || [];
      if (!selectedAgendaDate) {
        selectedAgendaDate =
          agendaItems.map(agendaDateKeyForItem).find(Boolean) || agendaDateKeyFromDate(new Date());
      }
      renderAgenda();
    },
    onError: () => {
      agendaContent.textContent = "无法读取日程。";
    },
  });
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

function careerApplicationStatusText(status, stage = "") {
  const raw = status || stage || "";
  const labels = {
    tracked: "已跟踪",
    interested: "已收藏",
    ready_for_confirmation: "等待确认",
    blocked_until_delegated_grant: "等待授权",
    apply_submit_blocked: "等待授权",
    submitted: "已投递",
    interviewing: "面试中",
    offer: "Offer",
    rejected: "已拒绝",
    ignored: "已忽略",
    withdrawn: "已撤回",
  };
  return labels[raw] || raw || "未开始";
}

function careerNextStepText(nextStep) {
  const labels = {
    request_delegated_grant_and_target_manifest: "申请分级授权并确认投递范围",
    confirm_application_materials: "确认投递材料",
    prepare_interview_if_replied: "等待回复后准备面试",
    connect_recruiter_or_referral: "联系招聘方或内推人",
    tailor_resume: "针对岗位修改简历",
    draft_cover_letter: "生成 Cover Letter",
    follow_up_after_three_days: "三天后跟进",
    none: "暂无下一步",
  };
  return labels[nextStep] || nextStep || "暂无下一步";
}

function careerListText(items, empty = "未记录") {
  if (!Array.isArray(items) || !items.length) return empty;
  return items.filter(Boolean).join("、") || empty;
}

function splitCareerInputList(value) {
  return String(value || "")
    .split(/[,，;；\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function careerResumeChangeText(resumeVersion = {}) {
  const changes = resumeVersion.payload?.changes || [];
  if (!Array.isArray(changes) || !changes.length) return "暂无专属简历草稿";
  return changes
    .slice(0, 4)
    .map((change) => `${change.section || "section"}：${change.change || change.reason || "已调整"}`)
    .join("；");
}

function careerResumeStatusText(status) {
  if (status === "active") return "可用";
  if (status === "deleted") return "已删除";
  if (status === "archived") return "已归档";
  return status || "未知状态";
}

function careerParsedTextSummary(resume = {}) {
  const raw = resume.parsed_text_summary || resume.payload?.parsed_text_summary || resume.payload?.summary || resume.parsed_text || "";
  const compact = String(raw).replace(/\s+/g, " ").trim();
  if (!compact) return "暂无解析摘要";
  return compact.length > 220 ? `${compact.slice(0, 220)}...` : compact;
}

function careerResumeSummaryText(resume = {}) {
  const payload = resume.payload || {};
  const isDefault = payload.is_default === true || payload.is_default === "true";
  const status = isDefault ? "默认基础简历" : careerResumeStatusText(resume.status);
  const evidence = careerListText(resume.source_event_ids || [], "暂无证据");
  return [
    `${resume.filename || resume.id || "未命名基础简历"} · ${resume.file_type || "resume"}`,
    `状态：${status}`,
    `解析摘要：${careerParsedTextSummary(resume)}`,
    `来源证据：${evidence}`,
    resume.updated_at ? `更新时间：${resume.updated_at}` : "",
  ].filter(Boolean).join("\n");
}

function careerOpportunityCardText(opportunity = {}, application = null, resumeVersion = null) {
  const payload = opportunity.payload || {};
  const fitScore = Number(opportunity.fit_score ?? payload.fit_score ?? 0);
  const matchedRequirements = payload.matched_requirements || opportunity.matched_requirements || [];
  const gapRequirements = payload.gap_requirements || opportunity.gap_requirements || [];
  const status = careerApplicationStatusText(application?.status, application?.stage || opportunity.status);
  const nextStep = careerNextStepText(application?.next_step);
  const lines = [
    `${opportunity.company || "未知公司"} · ${opportunity.location || "地点未记录"}`,
    `匹配度：${Number.isFinite(fitScore) ? fitScore.toFixed(2) : "未评分"}`,
    `匹配项：${careerListText(matchedRequirements)}`,
    `差距：${careerListText(gapRequirements, "暂未发现明显差距")}`,
    `应用阶段：${status}`,
    `下一步：${nextStep}`,
    `简历草稿：${careerResumeChangeText(resumeVersion || {})}`,
  ];
  if (opportunity.url) lines.push(`岗位链接：${opportunity.url}`);
  if (opportunity.source_event_ids?.length || application?.source_event_ids?.length) {
    lines.push(`来源证据：${(opportunity.source_event_ids || []).length + (application?.source_event_ids || []).length} 条`);
  }
  return lines.join("\n");
}

function careerDraftSummary(draft = {}) {
  const subject = draft.subject ? `${draft.subject}\n` : "";
  return `${subject}${draft.body || draft.message || "暂无草稿内容"}`.trim();
}

function careerDetailText(detail = {}) {
  const opportunity = detail.opportunity || {};
  const fit = detail.fit_summary || {};
  const resumeDraft = detail.resume_draft || {};
  const cover = detail.cover_letter_draft || {};
  const outreach = detail.outreach_draft || {};
  const prep = detail.interview_prep?.prep_brief || {};
  const coverDraft = cover.draft || {};
  const outreachDraft = outreach.draft || {};
  const lines = [
    `${opportunity.title || "未命名岗位"} · ${opportunity.company || "未知公司"}${opportunity.location ? ` · ${opportunity.location}` : ""}`,
    `岗位要求：${careerListText(opportunity.requirements || [])}`,
    `匹配度：${Number(fit.fit_score || 0).toFixed(2)}`,
    `匹配项：${careerListText(fit.matched_requirements || [])}`,
    `差距：${careerListText(fit.gap_requirements || [], "暂未发现明显差距")}`,
    `证据：${careerListText(fit.evidence_ids || [], "暂无证据")}`,
    `简历草案：${careerResumeChangeText(resumeDraft)}`,
    `Cover Letter（未发送）：${careerDraftSummary(coverDraft)}`,
    `外联草稿（需确认）：${outreachDraft.recipient || "收件人未定"}\n${outreachDraft.body || "暂无外联草稿"}`,
    `面试准备：${careerListText(prep.talking_points || [], "暂无面试要点")}`,
    `风险问题：${careerListText(prep.risk_questions || [], "暂无风险问题")}`,
  ];
  if (detail.generated_from?.drafts_are_not_sent) {
    lines.push("所有草稿均未发送，外联和申请动作仍需要用户最终确认。");
  }
  return lines.join("\n\n");
}

function careerAtsPreviewText(preview = {}) {
  const jobs = Array.isArray(preview.job_opportunities) ? preview.job_opportunities : [];
  const lines = [
    `来源：${preview.source || "unknown"}`,
    `状态：${preview.status || "unknown"}`,
    `下一步：${careerListText(preview.next_actions || [], "暂无下一步")}`,
    preview.writeback_performed
      ? "已写入求职看板。"
      : "只读预览，尚未写入求职看板。",
  ];
  for (const job of jobs) {
    const evidenceCount = (job.source_event_ids || []).length;
    lines.push([
      `${job.title || "未命名岗位"} · ${job.company || "未知公司"}${job.location ? ` · ${job.location}` : ""}`,
      `要求：${careerListText(job.requirements || [], "暂无可解析要求")}`,
      `证据：${evidenceCount} 条`,
      job.url ? `链接：${job.url}` : "",
    ].filter(Boolean).join("\n"));
  }
  if (!jobs.length) lines.push("没有解析到可用岗位，请确认链接是公开 ATS 岗位详情页。");
  return lines.join("\n\n");
}

function currentCareerRouteContext(parentContext = null) {
  const context =
    typeof parentContext?.isCurrent === "function"
      ? parentContext
      : workbenchNavigation.currentRouteContext();
  if (!context) {
    return {
      route: { primaryViewId: "careerView", settingsSectionId: "" },
      isCurrent: () => workbenchNavigation.currentRouteContext() === null,
    };
  }
  if (
    typeof context?.isCurrent !== "function" ||
    !context.isCurrent() ||
    context.route?.primaryViewId !== "careerView"
  ) {
    return null;
  }
  return context;
}

function runCareerContentRequest({
  parentContext = null,
  start = () => {},
  load,
  commit,
  onError = () => {},
}) {
  const routeContext = currentCareerRouteContext(parentContext);
  if (!routeContext || !careerContent) return Promise.resolve(false);
  start();
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "career-content",
    parentContext: routeContext,
    load,
    commit,
    onError,
  });
}

async function loadCareerBoard(parentContext = null) {
  return runCareerContentRequest({
    parentContext,
    start: () => {
      careerContent.textContent = "加载中...";
    },
    load: () => api("/api/career/board?limit=50"),
    commit: (data) => renderCareerBoard(data),
    onError: () => {
      if (careerResumeLibrary) careerResumeLibrary.textContent = "";
      careerContent.textContent = "无法读取求职看板。";
    },
  });
}

function clearCareerResumeLibrary() {
  if (careerResumeLibrary) careerResumeLibrary.textContent = "";
}

async function previewCareerAtsPage() {
  const url = careerAtsPreviewUrl.value.trim();
  if (!url) return false;
  return runCareerContentRequest({
    start: () => {
      clearCareerResumeLibrary();
      careerContent.textContent = "正在读取公开 ATS 岗位页面...";
    },
    load: () => api("/api/career/ats/preview", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
    commit: (preview) => renderCareerAtsPreview(preview),
    onError: () => {
      careerContent.textContent = "无法预览这个岗位链接。请确认它是 Greenhouse、Lever、Ashby、Workable 或 SmartRecruiters 的公开岗位页。";
    },
  });
}

async function previewCareerAtsList() {
  const url = careerAtsPreviewUrl.value.trim();
  if (!url) return false;
  return runCareerContentRequest({
    start: () => {
      clearCareerResumeLibrary();
      careerContent.textContent = "正在读取公开 ATS 职位列表...";
    },
    load: () => api("/api/career/ats/list-preview", {
      method: "POST",
      body: JSON.stringify({ url, limit: 25 }),
    }),
    commit: (preview) => renderCareerAtsPreview(preview),
    onError: () => {
      careerContent.textContent = "无法预览这个公司职位列表。当前列表预览支持 Greenhouse、Lever、Ashby、Workable 和 SmartRecruiters 的公开职位列表。";
    },
  });
}

async function loadCareerDetail(jobId) {
  if (!jobId) return false;
  return runCareerContentRequest({
    start: () => {
      clearCareerResumeLibrary();
      careerContent.textContent = "正在读取岗位详情...";
    },
    load: () => api(`/api/career/opportunities/${jobId}`),
    commit: (detail) => renderCareerDetail(detail),
    onError: () => {
      careerContent.textContent = "无法读取岗位详情。";
    },
  });
}

async function loadCareerOffers() {
  return runCareerContentRequest({
    start: () => {
      clearCareerResumeLibrary();
      careerContent.textContent = "正在读取面试和 Offer 跟踪...";
    },
    load: () => api("/api/career/offers"),
    commit: (data) => renderCareerOffers(data),
    onError: () => {
      careerContent.textContent = "无法读取面试和 Offer 跟踪。";
    },
  });
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",").pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error("file read failed"));
    reader.readAsDataURL(file);
  });
}

async function importCareerResumeFile() {
  const file = careerResumeFile.files?.[0];
  if (!file) {
    clearCareerResumeLibrary();
    careerContent.textContent = "请先选择 docx、pdf、txt 或 md 简历文件。";
    return false;
  }
  return runCareerContentRequest({
    start: () => {
      clearCareerResumeLibrary();
      careerContent.textContent = "正在解析并导入简历文件...";
    },
    load: async () => {
      const contentBase64 = await readFileAsBase64(file);
      return api("/api/career/resumes/import", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_base64: contentBase64,
          target_roles: splitCareerInputList(careerTargetRoles.value),
          target_locations: splitCareerInputList(careerTargetLocations.value),
        }),
      });
    },
    commit: (result) => renderCareerProfileIngestResult(result),
    onError: () => {
      careerContent.textContent = "无法导入简历文件。请确认文件格式和内容可读取。";
    },
  });
}

async function ingestCareerProfile() {
  const resumeText = careerResumeText.value.trim();
  if (resumeText.length < 20) {
    clearCareerResumeLibrary();
    careerContent.textContent = "请先粘贴至少 20 个字符的简历文本。";
    return false;
  }
  return runCareerContentRequest({
    start: () => {
      clearCareerResumeLibrary();
      careerContent.textContent = "正在生成本地职业画像...";
    },
    load: () => api("/api/career/profile/ingest", {
      method: "POST",
      body: JSON.stringify({
        resume_text: resumeText,
        target_roles: splitCareerInputList(careerTargetRoles.value),
        target_locations: splitCareerInputList(careerTargetLocations.value),
      }),
    }),
    commit: (result) => renderCareerProfileIngestResult(result),
    onError: () => {
      careerContent.textContent = "无法生成职业画像，请检查简历内容或服务状态。";
    },
  });
}

function renderCareerAtsPreview(preview = {}) {
  careerContent.textContent = "";
  const header = document.createElement("div");
  header.className = "career-detail-header";
  const title = document.createElement("h3");
  title.textContent = "ATS 岗位预览";
  const back = button("返回看板");
  back.addEventListener("click", loadCareerBoard);
  header.append(title, back);
  careerContent.appendChild(header);

  const node = card("card career-card career-ats-preview-card");
  const detail = document.createElement("p");
  detail.textContent = careerAtsPreviewText(preview);
  node.appendChild(detail);
  careerContent.appendChild(node);
}

function renderCareerProfileIngestResult(result = {}) {
  careerContent.textContent = "";
  const profile = result.career_profile || {};
  const node = card("card career-card career-profile-ingest-card");
  const text = [
    `画像：${profile.headline || "未命名职业画像"}`,
    `目标岗位：${careerListText(profile.target_roles || [])}`,
    `目标地点：${careerListText(profile.target_locations || [])}`,
    `技能：${careerListText(profile.skills || [])}`,
    `证据：${careerListText(profile.evidence_ids || profile.source_event_ids || [], "暂无证据")}`,
    result.writeback_performed ? "已写入本地求职看板。" : "尚未写入本地求职看板。",
  ].join("\n");
  const detail = document.createElement("p");
  detail.textContent = text;
  const actions = document.createElement("div");
  actions.className = "actions";
  const refresh = button("刷新看板");
  refresh.addEventListener("click", loadCareerBoard);
  actions.appendChild(refresh);
  node.append(detail, actions);
  careerContent.appendChild(node);
}

function renderCareerResumeLibrary(resumes = []) {
  if (!careerResumeLibrary) return;
  careerResumeLibrary.textContent = "";
  const heading = document.createElement("h3");
  heading.textContent = "基础简历";
  careerResumeLibrary.appendChild(heading);
  const visibleResumes = resumes.filter((resume) => resume.status !== "deleted");
  if (!visibleResumes.length) {
    careerResumeLibrary.appendChild(emptyCard("暂无基础简历。"));
    return;
  }
  for (const resume of visibleResumes) {
    careerResumeLibrary.appendChild(renderCareerBaseResumeCard(resume));
  }
}

function renderCareerBaseResumeCard(resume = {}) {
  const node = card("card compact career-base-resume-card");
  const payload = resume.payload || {};
  const isDefault = payload.is_default === true || payload.is_default === "true";
  const meta = document.createElement("time");
  meta.textContent = `${resume.file_type || "resume"} · ${isDefault ? "默认基础简历" : careerResumeStatusText(resume.status)}`;
  const title = document.createElement("strong");
  title.textContent = resume.filename || resume.id || "未命名基础简历";
  const summary = document.createElement("p");
  summary.className = "muted hidden";
  summary.textContent = careerResumeSummaryText(resume);
  const actions = document.createElement("div");
  actions.className = "actions";
  const viewSummary = button("查看解析摘要");
  viewSummary.addEventListener("click", () => {
    summary.classList.toggle("hidden");
    viewSummary.textContent = summary.classList.contains("hidden") ? "查看解析摘要" : "收起解析摘要";
  });
  actions.appendChild(viewSummary);
  if (!isDefault) {
    const makeDefault = button("设为默认");
    makeDefault.addEventListener("click", () =>
      runCareerActionTask(() => setDefaultCareerResume(resume.id), node)
    );
    actions.appendChild(makeDefault);
  }
  const remove = button("删除");
  remove.className = "danger";
  remove.addEventListener("click", () =>
    runCareerActionTask(() => deleteCareerResume(resume.id), node)
  );
  actions.appendChild(remove);
  node.append(meta, title, summary, actions);
  return node;
}

function runCareerActionTask(task, node) {
  return runUiTask(task, () => {
    showWorkbenchActionError(node, "求职看板操作失败，请稍后重试。");
  });
}

async function setDefaultCareerResume(resumeId, parentContext = null) {
  if (!resumeId) return false;
  const routeContext = currentCareerRouteContext(parentContext);
  if (!routeContext) return false;
  await api(`/api/career/resumes/${resumeId}`, {
    method: "PATCH",
    body: JSON.stringify({ make_default: true }),
  });
  if (!routeContext.isCurrent()) return false;
  return loadCareerBoard(routeContext);
}

async function deleteCareerResume(resumeId, parentContext = null) {
  if (!resumeId) return false;
  const confirmed = typeof window.confirm === "function" ? window.confirm("删除这份基础简历？") : true;
  if (!confirmed) return false;
  const routeContext = currentCareerRouteContext(parentContext);
  if (!routeContext) return false;
  await api(`/api/career/resumes/${resumeId}`, {
    method: "DELETE",
  });
  if (!routeContext.isCurrent()) return false;
  return loadCareerBoard(routeContext);
}

function careerResumeDraftSections(detail = {}) {
  const opportunity = detail.opportunity || {};
  const fit = detail.fit_summary || {};
  const resumePayload = detail.resume_draft?.payload || {};
  const explicitSections = Array.isArray(resumePayload.sections) ? resumePayload.sections : [];
  if (explicitSections.length) {
    return explicitSections
      .map((section) => ({
        title: String(section.title || section.section || "Section").trim(),
        body: String(section.body || section.content || section.change || "").trim(),
      }))
      .filter((section) => section.title && section.body);
  }
  const changes = Array.isArray(resumePayload.changes) ? resumePayload.changes : [];
  const coverDraft = detail.cover_letter_draft?.draft || {};
  const outreachDraft = detail.outreach_draft?.draft || {};
  const sections = [
    {
      title: "Job Target",
      body: [
        `${opportunity.title || "Target role"} · ${opportunity.company || "Unknown company"}`,
        opportunity.location ? `Location: ${opportunity.location}` : "",
        `Fit score: ${fit.fit_score ?? opportunity.fit_score ?? "unknown"}`,
        `Evidence: ${careerListText(fit.evidence_ids || opportunity.source_event_ids || [], "none")}`,
      ].filter(Boolean).join("\n"),
    },
    {
      title: "Resume Changes",
      body: changes.length
        ? changes.map((item) => `${item.section || "section"}: ${item.change || item.suggestion || ""}`).join("\n")
        : "No targeted resume changes were generated yet.",
    },
  ];
  if (coverDraft.body || coverDraft.subject) {
    sections.push({ title: `Cover Letter${coverDraft.subject ? ` - ${coverDraft.subject}` : ""}`, body: coverDraft.body || "" });
  }
  if (outreachDraft.body) {
    sections.push({ title: "Outreach Draft", body: outreachDraft.body });
  }
  return sections;
}

function renderCareerResumeSectionEditor(detail = {}) {
  const node = card("card career-resume-section-editor");
  const title = document.createElement("strong");
  title.textContent = "简历逐段编辑";
  node.appendChild(title);
  const sections = careerResumeDraftSections(detail);
  for (const [index, section] of sections.entries()) {
    const row = document.createElement("div");
    row.className = "career-resume-section-row";
    row.setAttribute("data-career-resume-section", String(index));
    const sectionTitle = document.createElement("input");
    sectionTitle.className = "career-section-title";
    sectionTitle.type = "text";
    sectionTitle.value = section.title;
    const sectionBody = document.createElement("textarea");
    sectionBody.className = "career-section-body";
    sectionBody.rows = Math.max(4, Math.min(10, String(section.body || "").split("\n").length + 2));
    sectionBody.value = section.body;
    row.append(sectionTitle, sectionBody);
    node.appendChild(row);
  }
  if (!sections.length) {
    node.appendChild(emptyCard("暂无可编辑简历草稿。"));
  }
  return node;
}

function readCareerEditedResumeSections(root = document) {
  const rows = Array.from(root.querySelectorAll("[data-career-resume-section]"));
  return rows
    .map((row) => {
      const title = row.querySelector(".career-section-title")?.value?.trim() || "";
      const body = row.querySelector(".career-section-body")?.value?.trim() || "";
      return { title, body };
    })
    .filter((section) => section.title && section.body);
}

function downloadCareerArtifact(artifact = {}) {
  if (!artifact.content_base64) return;
  const binary = atob(artifact.content_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const blob = new Blob([bytes], { type: artifact.mime_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = artifact.filename || "nomi-career-export";
  if (typeof anchor.click === "function") anchor.click();
  URL.revokeObjectURL(url);
}

async function exportCareerResumeDraft(detail = {}, format = "docx", sectionsOverride = null) {
  const opportunity = detail.opportunity || {};
  const headline = `${opportunity.title || "Target Resume"}${opportunity.company ? ` - ${opportunity.company}` : ""}`;
  const editedSections = Array.isArray(sectionsOverride) ? sectionsOverride : readCareerEditedResumeSections();
  const sections = editedSections.length ? editedSections : careerResumeDraftSections(detail);
  return runCareerContentRequest({
    load: () => api("/api/career/resumes/export", {
      method: "POST",
      body: JSON.stringify({
        filename: `${headline || "nomi-resume"}.${format}`,
        headline,
        sections,
        format,
        source_event_ids: detail.generated_from?.source_event_ids || detail.fit_summary?.evidence_ids || [],
      }),
    }),
    commit: (artifact) => downloadCareerArtifact(artifact),
    onError: () => {
      careerContent.appendChild(emptyCard("导出失败。请确认该岗位已有简历草稿或 Cover Letter 草稿。"));
    },
  });
}

function renderCareerOffers(data = {}) {
  careerContent.textContent = "";
  const header = document.createElement("div");
  header.className = "career-detail-header";
  const title = document.createElement("h3");
  title.textContent = "面试 / Offer 跟踪";
  const back = button("返回看板");
  back.addEventListener("click", loadCareerBoard);
  header.append(title, back);
  careerContent.appendChild(header);

  const offers = data.offers || [];
  if (!offers.length) {
    careerContent.appendChild(emptyCard("还没有面试或 Offer。进入面试、收到 Offer 后，这里会集中显示下一步和证据来源。"));
    return;
  }
  for (const offer of offers) {
    careerContent.appendChild(renderCareerApplicationCard(offer));
  }
}

function renderCareerDetail(detail = {}) {
  careerContent.textContent = "";
  const header = document.createElement("div");
  header.className = "career-detail-header";
  const title = document.createElement("h3");
  title.textContent = detail.opportunity?.title || "岗位详情";
  const back = button("返回看板");
  back.addEventListener("click", loadCareerBoard);
  header.append(title, back);
  careerContent.appendChild(header);

  const detailCard = card("card career-detail-card");
  const detailText = document.createElement("p");
  detailText.textContent = careerDetailText(detail);
  const exportActions = document.createElement("div");
  exportActions.className = "actions";
  const exportDocx = button("导出 DOCX");
  exportDocx.addEventListener("click", () => exportCareerResumeDraft(detail, "docx"));
  const exportPdf = button("导出 PDF");
  exportPdf.addEventListener("click", () => exportCareerResumeDraft(detail, "pdf"));
  exportActions.append(exportDocx, exportPdf);
  detailCard.append(detailText, exportActions);
  careerContent.appendChild(detailCard);
  careerContent.appendChild(renderCareerResumeSectionEditor(detail));

  const applications = detail.application_history || [];
  if (applications.length) {
    const heading = document.createElement("h3");
    heading.textContent = "申请状态历史";
    careerContent.appendChild(heading);
    for (const application of applications) careerContent.appendChild(renderCareerApplicationCard(application));
  }
}

function renderCareerBoard(data = {}) {
  careerContent.textContent = "";
  const baseResumes = data.career_resumes || [];
  renderCareerResumeLibrary(baseResumes);
  const profiles = data.profiles || [];
  if (profiles.length) {
    careerContent.appendChild(renderCareerProfileCard(profiles[0]));
  }

  const applicationsByJobId = new Map((data.applications || []).map((item) => [item.job_id || item.target_job_id, item]));
  const resumesByJobId = new Map((data.resume_versions || []).map((item) => [item.target_job_id, item]));
  const opportunities = data.opportunities || [];
  if (!opportunities.length && !profiles.length && !(data.applications || []).length && !baseResumes.length) {
    careerContent.appendChild(emptyCard("还没有求职数据。让 Nomi 读取简历和目标岗位后，这里会显示机会、匹配度和下一步。"));
    return;
  }

  if (opportunities.length) {
    const heading = document.createElement("h3");
    heading.textContent = "岗位机会";
    careerContent.appendChild(heading);
  }
  for (const opportunity of opportunities) {
    careerContent.appendChild(renderCareerOpportunityCard(
      opportunity,
      applicationsByJobId.get(opportunity.id),
      resumesByJobId.get(opportunity.id)
    ));
  }

  const orphanApplications = (data.applications || []).filter((application) => !opportunities.some((job) => job.id === (application.job_id || application.target_job_id)));
  if (orphanApplications.length) {
    const heading = document.createElement("h3");
    heading.textContent = "申请跟踪";
    careerContent.appendChild(heading);
    for (const application of orphanApplications) careerContent.appendChild(renderCareerApplicationCard(application));
  }
}

function renderCareerProfileCard(profile) {
  const node = card("card compact career-profile-card");
  const roles = careerListText(profile.target_roles || [], "未记录目标岗位");
  const locations = careerListText(profile.target_locations || [], "未记录目标地点");
  const skills = careerListText(profile.skills || [], "未记录技能");
  node.innerHTML = `<time>职业画像 · ${profile.updated_at || "本地"}</time><strong>${profile.headline || "求职目标"}</strong><p>目标岗位：${roles}\n目标地点：${locations}\n核心技能：${skills}</p>`;
  return node;
}

function renderCareerOpportunityCard(opportunity, application, resumeVersion) {
  const node = card("card career-card");
  const title = document.createElement("strong");
  title.textContent = opportunity.title || "未命名岗位";
  const meta = document.createElement("time");
  meta.textContent = `${opportunity.source || "job"} · ${careerApplicationStatusText(application?.status, application?.stage || opportunity.status)}`;
  const detail = document.createElement("p");
  detail.textContent = careerOpportunityCardText(opportunity, application, resumeVersion);
  node.append(meta, title, detail);
  const actions = document.createElement("div");
  actions.className = "actions";
  const openDetail = button("查看详情");
  openDetail.addEventListener("click", () => loadCareerDetail(opportunity.id));
  actions.appendChild(openDetail);
  if (application?.id) {
    if (!["submitted", "ignored", "rejected", "withdrawn"].includes(application.status)) {
      const submitted = button("标记已投递");
      submitted.addEventListener("click", () =>
        runCareerActionTask(
          () =>
            updateCareerApplicationStatus(
              application.id,
              "submitted",
              "submitted",
              "prepare_interview_if_replied"
            ),
          node
        )
      );
      const ignored = button("忽略");
      ignored.addEventListener("click", () =>
        runCareerActionTask(
          () => updateCareerApplicationStatus(application.id, "ignored", "ignored", "none"),
          node
        )
      );
      actions.append(submitted, ignored);
    }
  }
  if (actions.children.length) node.appendChild(actions);
  return node;
}

function renderCareerApplicationCard(application) {
  const node = card("card career-card");
  const payload = application.payload || {};
  const title = [payload.company, payload.title].filter(Boolean).join(" · ")
    || application.job_id
    || application.target_job_id
    || application.id;
  const evidence = careerListText(application.source_event_ids || [], "暂无证据");
  node.innerHTML = `<time>${application.application_action || "application"} · ${careerApplicationStatusText(application.status, application.stage)}</time><strong>${title}</strong><p>下一步：${careerNextStepText(application.next_step)}\n渠道：${application.platform || application.channel || "未记录"}\n证据：${evidence}</p>`;
  return node;
}

async function updateCareerApplicationStatus(
  applicationId,
  status,
  stage,
  nextStep,
  parentContext = null
) {
  const routeContext = currentCareerRouteContext(parentContext);
  if (!routeContext) return false;
  await api(`/api/career/applications/${applicationId}`, {
    method: "PATCH",
    body: JSON.stringify({
      status,
      stage,
      next_step: nextStep,
      user_note: `updated from workbench: ${status}`,
    }),
  });
  if (!routeContext.isCurrent()) return false;
  return loadCareerBoard(routeContext);
}

if (typeof window !== "undefined") {
  window.nomiCareerDebug = {
    careerApplicationStatusText,
    careerNextStepText,
    careerAtsPreviewText,
    careerDetailText,
    careerOpportunityCardText,
    careerResumeSummaryText,
    careerResumeDraftSections,
    readCareerEditedResumeSections,
    exportCareerResumeDraft,
  };
}

function normalizeSuggestionAction(action) {
  if (!action || typeof action !== "object") return null;
  const id = action.id || action.action_id || action.next_step || action.label;
  const label = action.label || action.title || action.id || action.next_step;
  if (!id || !label) return null;
  return {
    id: String(id),
    label: String(label),
    url: action.url || "",
    nextStep: action.next_step || action.id || "",
  };
}

function suggestionFromProactiveEvent(event) {
  if (!event || typeof event !== "object") return null;
  const suggestionId = event.suggestion_id || event.id;
  if (!suggestionId) return null;
  return {
    id: String(suggestionId),
    source_event_id: event.source_event_id || "",
    title: event.title || "主动建议",
    body: event.body || "",
    priority: Number(event.priority || 0),
    status: "open",
    metadata: {
      ...(event.metadata || {}),
      actions: Array.isArray(event.actions) ? event.actions : event.metadata?.actions,
      source: event.source || event.metadata?.source,
    },
    created_at: event.created_at || "",
  };
}

function renderSuggestionCard(item, focusSuggestionId = "") {
  const metadata = item.metadata && typeof item.metadata === "object" ? item.metadata : {};
  const node = card("card suggestion-card");
  node.dataset.suggestionId = item.id || "";
  if (focusSuggestionId && item.id === focusSuggestionId) node.classList.add("focused-suggestion");

  const meta = document.createElement("time");
  const typeText = metadata.suggestion_type || metadata.source || "suggestion";
  meta.textContent = `${typeText} · 优先级 ${Number(item.priority || 0).toFixed(2)}`;
  node.appendChild(meta);

  const title = document.createElement("strong");
  title.textContent = item.title || "主动建议";
  node.appendChild(title);

  const jobCard = renderProactiveJobRecommendationCard({ ...item, metadata });
  if (jobCard) {
    node.appendChild(jobCard);
  } else {
    const body = document.createElement("p");
    body.textContent = item.body || "暂无详情。";
    node.appendChild(body);
  }

  const context = [];
  if (item.source_event_id) context.push(`来源事件：${item.source_event_id}`);
  if (metadata.source) context.push(`来源渠道：${metadata.source}`);
  if (metadata.reason) context.push(`判断原因：${metadata.reason}`);
  if (context.length) {
    const contextNode = document.createElement("p");
    contextNode.className = "muted small";
    contextNode.textContent = context.join("\n");
    node.appendChild(contextNode);
  }

  const actions = document.createElement("div");
  actions.className = "actions";
  const suggestionActions = Array.isArray(metadata.actions) ? metadata.actions : [];
  for (const rawAction of suggestionActions) {
    const action = normalizeSuggestionAction(rawAction);
    if (!action) continue;
    const actionButton = button(action.label);
    actionButton.addEventListener("click", () => {
      if (action.url) {
        openExternalUrl(action.url);
        return;
      }
      runSuggestionAction(item.id, action.id, actionButton);
    });
    actions.appendChild(actionButton);
  }
  const done = button("完成");
  done.addEventListener("click", () =>
    runSuggestionStatusUpdate(item.id, "done", node, done)
  );
  const dismiss = button("忽略");
  dismiss.addEventListener("click", () =>
    runSuggestionStatusUpdate(item.id, "dismissed", node, dismiss)
  );
  actions.append(done, dismiss);
  node.appendChild(actions);
  return node;
}

async function loadSuggestions(focusSuggestionId = "", fallbackEvent = null, parentContext = null) {
  if (!suggestionsContent) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  suggestionsContent.textContent = "加载中...";
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "suggestions",
    parentContext,
    load: () => api("/api/suggestions"),
    commit: (data) => {
      suggestionsContent.textContent = "";
      const items = [...(data || [])];
      const fallbackSuggestion = suggestionFromProactiveEvent(fallbackEvent);
      if (
        focusSuggestionId &&
        fallbackSuggestion &&
        !items.some((item) => item.id === focusSuggestionId)
      ) {
        items.unshift(fallbackSuggestion);
      }
      for (const item of items) {
        suggestionsContent.appendChild(renderSuggestionCard(item, focusSuggestionId));
      }
      if (!suggestionsContent.children.length) suggestionsContent.appendChild(emptyCard("暂无建议"));
      if (focusSuggestionId) {
        const focused = suggestionsContent.querySelector(
          `[data-suggestion-id="${cssEscapeValue(focusSuggestionId)}"]`
        );
        if (focused) focused.scrollIntoView({ block: "center", inline: "nearest" });
      }
    },
    onError: () => {
      suggestionsContent.textContent = "无法读取建议。";
    },
  });
}

async function updateSuggestion(id, status, node) {
  await api(`/api/suggestions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ status }) });
  node.remove();
  if (!suggestionsContent.children.length) suggestionsContent.appendChild(emptyCard("暂无建议"));
}

function showWorkbenchActionError(container, message) {
  if (!container) return;
  let error = container.querySelector?.(".workbench-action-error");
  if (!error) {
    error = document.createElement("p");
    error.className = "error workbench-action-error";
    container.appendChild(error);
  }
  error.textContent = message;
}

function runSuggestionStatusUpdate(id, status, node, actionButton) {
  actionButton.disabled = true;
  return runUiTask(
    () => updateSuggestion(id, status, node),
    () => {
      actionButton.disabled = false;
      showWorkbenchActionError(node, "建议状态更新失败，请稍后重试。");
    }
  );
}

async function runSuggestionAction(id, actionId, actionButton) {
  if (!id || !actionId) return;
  const previousText = actionButton.textContent;
  actionButton.disabled = true;
  actionButton.textContent = "处理中...";
  try {
    const result = await api(`/api/proactive/suggestions/${encodeURIComponent(id)}/action`, {
      method: "POST",
      body: JSON.stringify({
        action_id: actionId,
        reason: "user_selected_from_suggestion_workspace",
        conversation_id: chatConversationId || undefined,
      }),
    });
    workbenchNavigation.navigateToView("chatView");
    const routeResult = result.route_result || {};
    const pipelineResult = result.pipeline_result || {};
    const localResult = result.local_result || {};
    const pipelineName = routeResult.pipeline?.name || routeResult.pipeline?.id || pipelineResult.pipeline_id;
    const guard = routeResult.execution_guard || pipelineResult.execution_guard || {};
    const routeRequest = pipelineResult.output?.route_request || {};
    const resolvedSlots = pipelineResult.resolved_slots || {};
    const summary = result.chat_summary || [
      pipelineName ? `已按建议进入：${pipelineName}` : "建议动作已记录。",
      routeRequest.destination || resolvedSlots.destination ? `目的地：${routeRequest.destination || resolvedSlots.destination}` : "",
      pipelineResult.status ? `执行状态：${pipelineResult.status}` : "",
      guard.requires_confirmation ? "这个动作需要你最终确认后才会执行。" : "",
      localResult.status ? `当前状态：${localResult.status}` : "",
    ].filter(Boolean).join("\n");
    const fallbackSummary = summary || "建议动作已处理。";
    try {
      await loadChatHistory(true);
    } finally {
      if (!messages.textContent.includes(fallbackSummary)) {
        addMessage("assistant", fallbackSummary);
      }
    }
  } catch {
    actionButton.disabled = false;
    actionButton.textContent = previousText;
    const error = document.createElement("p");
    error.className = "error";
    error.textContent = "动作处理失败，请稍后重试。";
    actionButton.closest(".card")?.appendChild(error);
  }
}

function collectorStatusText(item) {
  if (!item.enabled) return "已关闭";
  if (item.paused) return "已暂停";
  return "采集中";
}

async function loadCollectors(parentContext = null) {
  if (!collectorsContent) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  collectorsContent.textContent = "加载中...";
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "collectors",
    parentContext,
    load: () => api("/api/collectors/status"),
    commit: (data) => {
      collectorsContent.textContent = "";
      for (const item of data.collectors || []) {
        const node = card();
        node.innerHTML = `<time>${collectorStatusText(item)} · ${item.health_status || "unknown"}</time><strong>${item.source}</strong><p>${JSON.stringify(item.details || {}, null, 2)}</p>`;
        const actions = document.createElement("div");
        actions.className = "actions";
        const toggle = button(item.enabled && !item.paused ? "暂停" : "开启");
        toggle.addEventListener("click", () => {
          const nextEnabled = !(item.enabled && !item.paused);
          runCollectorSettingsUpdate({
            routeContext: workbenchNavigation.currentRouteContext(),
            actionButton: toggle,
            mutate: () =>
              api(`/api/collectors/settings/${item.source}`, {
                method: "PATCH",
                body: JSON.stringify({
                  enabled: nextEnabled,
                  paused_until: null,
                  reason: nextEnabled ? "" : "user paused from workbench",
                }),
              }),
            refresh: (context) => loadCollectors(context),
            recover: () =>
              showWorkbenchActionError(node, "采集设置更新失败，请稍后重试。"),
          });
        });
        const pauseHour = button("暂停1小时");
        pauseHour.addEventListener("click", () => {
          const until = new Date(Date.now() + 60 * 60 * 1000).toISOString();
          runCollectorSettingsUpdate({
            routeContext: workbenchNavigation.currentRouteContext(),
            actionButton: pauseHour,
            mutate: () =>
              api(`/api/collectors/settings/${item.source}`, {
                method: "PATCH",
                body: JSON.stringify({
                  enabled: true,
                  paused_until: until,
                  reason: "temporary pause from workbench",
                }),
              }),
            refresh: (context) => loadCollectors(context),
            recover: () =>
              showWorkbenchActionError(node, "采集设置更新失败，请稍后重试。"),
          });
        });
        actions.append(toggle, pauseHour);
        node.appendChild(actions);
        collectorsContent.appendChild(node);
      }
    },
    onError: () => {
      collectorsContent.textContent = "无法读取采集设置。";
    },
  });
}

const webSearchProviderMeta = {
  exa: {
    name: "Exa",
    mark: "EX",
    description: "技术文档、论文、开源项目和公司研究优先使用。",
  },
  tavily: {
    name: "Tavily",
    mark: "TA",
    description: "最新新闻、实时变化和时效性信息优先使用。",
  },
  bocha: {
    name: "博查",
    mark: "博",
    description: "中文通用搜索、本地信息和中文来源补充。",
  },
};

function clearWebSearchKeyInput() {
  if (webSearchKeyInput) {
    webSearchKeyInput.value = "";
    webSearchKeyInput.type = "password";
  }
  if (webSearchToggleKeyVisibility) {
    webSearchToggleKeyVisibility.title = "显示本次输入";
    webSearchToggleKeyVisibility.setAttribute("aria-label", "显示本次输入");
  }
}

function webSearchHealthLabel(status) {
  return {
    healthy: "连接正常",
    untested: "待测试",
    not_configured: "未配置",
    invalid_key: "Key 无效",
    rate_limited: "请求受限",
    timeout: "连接超时",
    provider_error: "服务异常",
  }[status] || "状态未知";
}

function webSearchSourceLabel(source) {
  if (source === "database") return "数据库加密配置";
  if (source === "environment") return "环境变量配置";
  return "未配置";
}

function safeWebSearchError(error, fallback = "操作失败，请检查 Key 和网络后重试。") {
  const message = String(error?.message || "").toLowerCase();
  if (message.includes("provider_not_configured")) return "请先填写并保存 API Key。";
  if (message.includes("provider_auth_failed")) return "API Key 无效或没有访问权限。";
  if (message.includes("provider_rate_limited")) return "服务当前请求受限，请稍后重试。";
  if (message.includes("provider_test_timeout")) return "连接测试超时，请检查网络后重试。";
  if (message.includes("provider_secret_error")) {
    return "服务端尚未配置安全的 WEB_SEARCH_CONFIG_ENCRYPTION_SECRET，暂时不能保存 Key。";
  }
  return fallback;
}

function currentWebSearchProviderConfig(provider = selectedWebSearchProvider) {
  return (webSearchSettingsState?.providers || []).find((item) => item.provider === provider) || null;
}

function renderWebSearchProviderList() {
  if (!webSearchProviderList) return;
  webSearchProviderList.textContent = "";
  const providers = webSearchSettingsState?.providers || [];
  const configuredCount = providers.filter((item) => item.configured).length;
  const enabledCount = providers.filter(
    (item) => item.configured && item.enabled && item.connection_status !== "invalid_key",
  ).length;
  webSearchConfiguredSummary.textContent = configuredCount
    ? `已配置 ${configuredCount} 个服务，当前启用 ${enabledCount} 个。多个服务会按查询类型智能选择。`
    : "尚未配置搜索服务。配置任意一个后，所有公开搜索都会使用它。";
  for (const config of providers) {
    const meta = webSearchProviderMeta[config.provider] || { name: config.provider, mark: "WS", description: "" };
    const row = document.createElement("button");
    row.type = "button";
    row.className = "web-search-provider-row";
    row.dataset.provider = config.provider;
    const mark = document.createElement("span");
    mark.className = `web-search-provider-mark provider-${config.provider}`;
    mark.textContent = meta.mark;
    const copy = document.createElement("span");
    copy.className = "web-search-provider-copy";
    const name = document.createElement("strong");
    name.textContent = meta.name;
    const detail = document.createElement("small");
    detail.textContent = config.configured
      ? `${webSearchSourceLabel(config.config_source)} · ••••${config.key_hint || ""}`
      : "尚未配置 API Key";
    copy.append(name, detail);
    const status = document.createElement("span");
    status.className = `web-search-row-status status-${config.connection_status || "unknown"}`;
    status.textContent = webSearchHealthLabel(config.connection_status);
    const arrow = document.createElement("span");
    arrow.className = "web-search-row-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "›";
    row.append(mark, copy, status, arrow);
    row.addEventListener("click", () => openWebSearchProvider(config.provider));
    webSearchProviderList.appendChild(row);
  }
}

function renderWebSearchRouting() {
  if (!webSearchSettingsState) return;
  webSearchRoutingStrategy.value = webSearchSettingsState.strategy || "smart";
  webSearchRoutingOrder.value = (webSearchSettingsState.fallback_order || ["exa", "tavily", "bocha"]).join(",");
  webSearchConfigVersion.textContent = `配置 v${webSearchSettingsState.config_version || 1}`;
}

function renderWebSearchProviderDetail(provider) {
  const config = currentWebSearchProviderConfig(provider);
  if (!config) return;
  const meta = webSearchProviderMeta[provider] || { name: provider, description: "" };
  webSearchProviderDetailTitle.textContent = meta.name;
  webSearchProviderDescription.textContent = meta.description;
  webSearchProviderHealth.textContent = webSearchHealthLabel(config.connection_status);
  webSearchProviderHealth.className = `web-search-health status-${config.connection_status || "unknown"}`;
  webSearchProviderSource.textContent = webSearchSourceLabel(config.config_source);
  webSearchProviderKeyHint.textContent = config.configured && config.key_hint ? `•••• ${config.key_hint}` : "未配置";
  webSearchEnabledToggle.checked = Boolean(config.enabled);
  webSearchTestStored.disabled = !config.configured;
  webSearchDeleteKey.disabled = config.config_source !== "database";
  webSearchLastTestedAt.textContent = config.last_tested_at
    ? `最近测试：${new Date(config.last_tested_at).toLocaleString()}${config.last_test_latency_ms ? ` · ${config.last_test_latency_ms} ms` : ""}`
    : "尚未进行连接测试。";
  webSearchProviderStatus.textContent = config.last_test_latency_ms
    ? `上次连接耗时 ${config.last_test_latency_ms} ms`
    : "";
}

function openWebSearchProvider(provider) {
  selectedWebSearchProvider = provider;
  clearWebSearchKeyInput();
  webSearchProviderListPanel.classList.add("hidden");
  webSearchProviderDetail.classList.remove("hidden");
  renderWebSearchProviderDetail(provider);
}

function closeWebSearchProviderDetail() {
  selectedWebSearchProvider = "";
  clearWebSearchKeyInput();
  webSearchProviderStatus.textContent = "";
  webSearchProviderDetail.classList.add("hidden");
  webSearchProviderListPanel.classList.remove("hidden");
}

function setWebSearchDetailBusy(busy, message = "") {
  for (const control of [
    webSearchSaveAndTest,
    webSearchTestStored,
    webSearchDeleteKey,
    webSearchEnabledToggle,
    webSearchProviderBack,
  ]) {
    if (control) control.disabled = Boolean(busy);
  }
  if (message) webSearchProviderStatus.textContent = message;
}

async function loadWebSearchSettings(options = {}) {
  const reopenProvider = options?.reopenProvider || "";
  const parentContext = typeof options?.isCurrent === "function" ? options : null;
  if (!webSearchProviderList) return;
  if (!isRequestParentCurrent(parentContext)) return false;
  webSearchProviderList.textContent = "加载搜索服务...";
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "web-search-settings",
    parentContext,
    load: () => api("/api/web-search/settings"),
    commit: (nextState) => {
      webSearchSettingsState = nextState;
      renderWebSearchProviderList();
      renderWebSearchRouting();
      if (reopenProvider) openWebSearchProvider(reopenProvider);
    },
    onError: (error) => {
      webSearchProviderList.textContent = safeWebSearchError(error, "无法读取 Web Search 设置。");
    },
  });
}

async function saveAndTestWebSearchProvider(provider) {
  const apiKey = webSearchKeyInput.value.trim();
  if (!provider || !apiKey) {
    webSearchProviderStatus.textContent = "请粘贴新的 API Key。";
    return;
  }
  setWebSearchDetailBusy(true, "正在连接测试...");
  let finalMessage = "";
  try {
    await api(`/api/web-search/settings/${provider}`, {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey, enabled: webSearchEnabledToggle.checked }),
    });
    clearWebSearchKeyInput();
    await loadWebSearchSettings({ reopenProvider: provider });
    finalMessage = "连接测试通过，Key 已加密保存。";
  } catch (error) {
    finalMessage = safeWebSearchError(error);
  } finally {
    setWebSearchDetailBusy(false);
    renderWebSearchProviderDetail(provider);
    webSearchProviderStatus.textContent = finalMessage;
  }
}

async function testStoredWebSearchProvider(provider) {
  if (!provider) return;
  setWebSearchDetailBusy(true, "正在测试已保存 Key...");
  let finalMessage = "";
  try {
    const result = await api(`/api/web-search/settings/${provider}/test`, { method: "POST" });
    finalMessage = `连接正常 · ${result.latency_ms || 0} ms`;
  } catch (error) {
    finalMessage = safeWebSearchError(error);
  } finally {
    await loadWebSearchSettings({ reopenProvider: provider });
    setWebSearchDetailBusy(false);
    renderWebSearchProviderDetail(provider);
    webSearchProviderStatus.textContent = finalMessage;
  }
}

async function updateWebSearchProviderEnabled(provider, enabled) {
  if (!provider) return;
  webSearchProviderStatus.textContent = "正在更新...";
  try {
    await api(`/api/web-search/settings/${provider}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    await loadWebSearchSettings({ reopenProvider: provider });
    webSearchProviderStatus.textContent = enabled ? "已启用。" : "已停用。";
  } catch (error) {
    webSearchEnabledToggle.checked = !enabled;
    webSearchProviderStatus.textContent = safeWebSearchError(error);
  }
}

async function deleteWebSearchProviderKey(provider) {
  if (!provider || !window.confirm("删除数据库中保存的 Key？如果存在环境变量，将自动回退使用环境变量。")) return;
  setWebSearchDetailBusy(true, "正在删除数据库 Key...");
  let finalMessage = "";
  try {
    const result = await api(`/api/web-search/settings/${provider}/key`, { method: "DELETE" });
    clearWebSearchKeyInput();
    await loadWebSearchSettings({ reopenProvider: provider });
    finalMessage = result.config_source === "environment"
      ? "数据库 Key 已删除，当前回退使用环境变量。"
      : "数据库 Key 已删除。";
  } catch (error) {
    finalMessage = safeWebSearchError(error, "删除失败，请稍后重试。");
  } finally {
    setWebSearchDetailBusy(false);
    renderWebSearchProviderDetail(provider);
    webSearchProviderStatus.textContent = finalMessage;
  }
}

async function saveWebSearchRouting() {
  webSearchSaveRouting.disabled = true;
  webSearchRoutingStatus.textContent = "正在保存...";
  try {
    const order = webSearchRoutingOrder.value.split(",").filter(Boolean);
    await api("/api/web-search/settings/routing", {
      method: "PATCH",
      body: JSON.stringify({ strategy: webSearchRoutingStrategy.value, fallback_order: order }),
    });
    await loadWebSearchSettings();
    webSearchRoutingStatus.textContent = "路由设置已生效，无需重启服务。";
  } catch (error) {
    webSearchRoutingStatus.textContent = safeWebSearchError(error, "路由设置保存失败。");
  } finally {
    webSearchSaveRouting.disabled = false;
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

const assistantIdentityPlaceholderAddresses = new Set([
  "nomi@example.com",
  "+00000000000",
]);

function verifiedAssistantIdentityAddress(identity = {}) {
  const address = String(identity.address || "").trim();
  if (!address || assistantIdentityPlaceholderAddresses.has(address) || address === "nomi@example.com") {
    return "尚未验证";
  }
  if (!identity.last_verified_at) return "尚未验证";
  return address;
}

function assistantIdentityStatusLabel(status) {
  const labels = {
    unconfigured: "未配置",
    authorization_pending: "等待授权",
    verifying: "验证中",
    connected: "已连接",
    degraded: "连接异常",
    expired: "授权已过期",
    failed: "验证失败",
    disabled: "已停用",
    draft: "待确认",
    blocked: "发送失败",
    sending: "发送中",
    sent: "已发送",
    delivered: "已送达",
    read: "已读",
    rejected: "已拒绝",
    delivery_unknown: "送达状态待核实",
  };
  return labels[String(status || "")] || String(status || "未知状态");
}

function assistantIdentityTimestamp(value) {
  if (!value) return "尚无记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function appendAssistantIdentityListItem(container, { meta, title, body, status = "" }) {
  const item = document.createElement("article");
  item.className = "assistant-identity-list-item";
  const metaNode = document.createElement("time");
  metaNode.textContent = meta || "";
  const titleNode = document.createElement("strong");
  titleNode.textContent = title || "未命名记录";
  const bodyNode = document.createElement("p");
  bodyNode.textContent = body || "";
  item.append(metaNode, titleNode, bodyNode);
  if (status) item.dataset.status = status;
  container.appendChild(item);
  return item;
}

function runAssistantIdentityTask(task) {
  return runUiTask(task, (error) => {
    if (assistantIdentityStatus) {
      assistantIdentityStatus.textContent = `操作失败：${String(error?.message || error || "请稍后重试。")}`;
    }
  });
}

function renderAssistantIdentityGmail(identity, health = {}) {
  assistantIdentityGmail.textContent = "";
  const heading = document.createElement("div");
  heading.className = "assistant-identity-card-heading";
  const titleWrap = document.createElement("div");
  const eyebrow = document.createElement("span");
  eyebrow.className = "assistant-identity-eyebrow";
  eyebrow.textContent = "NOMI OWNED ACCOUNT";
  const title = document.createElement("h3");
  title.textContent = "Nomi Gmail";
  titleWrap.append(eyebrow, title);
  const badge = document.createElement("span");
  badge.className = `assistant-identity-badge status-${String(identity.status || "unknown")}`;
  badge.textContent = assistantIdentityStatusLabel(identity.status);
  heading.append(titleWrap, badge);

  const address = document.createElement("p");
  address.className = "assistant-identity-address";
  address.textContent = verifiedAssistantIdentityAddress(identity);

  const facts = document.createElement("dl");
  facts.className = "assistant-identity-facts";
  const factValues = [
    ["提供方", identity.provider || "尚未绑定"],
    ["最近验证", assistantIdentityTimestamp(identity.last_verified_at)],
    ["收件", health.checks?.inbound || "未检查"],
    ["发件", health.checks?.outbound || "未检查"],
  ];
  for (const [label, value] of factValues) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = String(value);
    wrapper.append(term, detail);
    facts.appendChild(wrapper);
  }

  const note = document.createElement("p");
  note.className = "assistant-identity-note";
  note.textContent = identity.last_error_code
    ? `最近错误：${identity.last_error_code}`
    : "OAuth 令牌由 Composio 管理，Nomi 页面不会读取或保存令牌。";

  const actions = document.createElement("div");
  actions.className = "assistant-identity-actions";
  const connect = button(identity.status === "connected" || identity.status === "degraded" ? "重新连接" : "连接 Gmail");
  connect.addEventListener("click", () => runAssistantIdentityTask(connectAssistantGmail));
  actions.appendChild(connect);
  if (!["unconfigured", "authorization_pending"].includes(identity.status)) {
    const verify = button("立即验证");
    verify.className = "secondary";
    verify.addEventListener("click", () =>
      runAssistantIdentityTask(() => verifyAssistantIdentity(identity.identity_id))
    );
    actions.appendChild(verify);
  }
  if (identity.status === "disabled") {
    const enable = button("启用");
    enable.className = "secondary";
    enable.addEventListener("click", () =>
      runAssistantIdentityTask(() => enableAssistantIdentity(identity.identity_id))
    );
    actions.appendChild(enable);
  } else if (identity.status !== "unconfigured") {
    const disable = button("停用");
    disable.className = "secondary";
    disable.addEventListener("click", () =>
      runAssistantIdentityTask(() => disableAssistantIdentity(identity.identity_id))
    );
    actions.appendChild(disable);
  }
  if (identity.status !== "unconfigured") {
    const disconnect = button("断开连接");
    disconnect.className = "secondary danger";
    disconnect.addEventListener("click", () =>
      runAssistantIdentityTask(() => disconnectAssistantIdentity(identity.identity_id))
    );
    actions.appendChild(disconnect);
  }

  assistantIdentityGmail.append(heading, address, facts, note, actions);
}

function renderAssistantIdentityInbox(items = []) {
  assistantIdentityInbox.textContent = "";
  const gmailItems = items.filter((item) =>
    String(item.identity_id || item.source_account_id || "") === "nomi_gmail_primary"
  );
  for (const item of gmailItems.slice(0, 8)) {
    appendAssistantIdentityListItem(assistantIdentityInbox, {
      meta: `${assistantIdentityTimestamp(item.occurred_at || item.created_at)} · ${item.classification || "邮件"}`,
      title: item.sender_key || "未知发件人",
      body: item.normalized_text || item.normalized_payload?.subject || "邮件内容已归档",
    });
  }
  if (!assistantIdentityInbox.children.length) assistantIdentityInbox.appendChild(emptyCard("暂无 Nomi Gmail 收件。"));
}

function setAssistantDraftActionButtonsDisabled(draftId, disabled) {
  const selector = `[data-draft-id="${cssEscapeValue(draftId)}"] button`;
  document.querySelectorAll(selector).forEach((node) => {
    node.disabled = disabled;
  });
}

async function refreshAssistantDraftSurfaces() {
  await Promise.allSettled([loadChatAssistantDrafts(), loadAssistantIdentities()]);
}

async function runAssistantDraftAction(draftId, operation) {
  const stableDraftId = String(draftId || "").trim();
  if (!stableDraftId || assistantDraftActionsInFlight.has(stableDraftId)) return null;
  assistantDraftActionsInFlight.add(stableDraftId);
  setAssistantDraftActionButtonsDisabled(stableDraftId, true);
  try {
    return await operation();
  } finally {
    assistantDraftActionsInFlight.delete(stableDraftId);
    await refreshAssistantDraftSurfaces();
  }
}

async function editAssistantDraft(draftId, draft = {}) {
  const subject = window.prompt("邮件主题", draft.subject || "");
  if (subject === null) return null;
  const bodyText = window.prompt("邮件正文", draft.body_text || "");
  if (bodyText === null) return null;
  return runAssistantDraftAction(draftId, () => api(`/api/assistant-outbound/drafts/${draftId}`, {
    method: "PATCH",
    body: JSON.stringify({ subject, body_text: bodyText }),
  }));
}

async function confirmAssistantDraft(draftId) {
  return runAssistantDraftAction(draftId, async () => {
    const confirmation = await api(`/api/assistant-outbound/drafts/${draftId}/confirm`, { method: "POST" });
    return sendAssistantDraft(draftId, confirmation.confirmation_token);
  });
}

async function sendAssistantDraft(draftId, confirmationToken) {
  return api(`/api/assistant-outbound/drafts/${draftId}/send`, {
    method: "POST",
    body: JSON.stringify({ confirmation_token: confirmationToken }),
  });
}

async function cancelAssistantDraft(draftId) {
  return runAssistantDraftAction(draftId, () => api(`/api/assistant-outbound/drafts/${draftId}/cancel`, {
    method: "POST",
  }));
}

function renderChatAssistantDrafts(items = []) {
  if (!chatAssistantDrafts) return;
  ensureChatAssistantDraftRegion();
  chatAssistantDrafts.replaceChildren();
  const visibleStatuses = ["draft", "blocked", "sending", "sent", "delivered", "read", "failed", "rejected", "delivery_unknown"];
  const pending = items.filter((draft) =>
    draft.identity_id === "nomi_gmail_primary"
      && draft.channel === "gmail"
      && visibleStatuses.includes(draft.status)
  );
  for (const draft of pending.slice(0, 5)) {
    const item = document.createElement("article");
    item.className = "message assistant chat-assistant-draft";
    item.dataset.draftId = draft.draft_id;
    item.dataset.status = draft.status;

    const meta = document.createElement("time");
    meta.textContent = `Nomi Gmail · ${assistantIdentityStatusLabel(draft.status)}`;
    const title = document.createElement("strong");
    title.textContent = draft.subject || "无主题邮件";
    const recipient = document.createElement("p");
    recipient.textContent = `收件人：${draft.recipient || "未填写"}`;
    const body = document.createElement("p");
    body.className = "assistant-draft-body";
    body.textContent = draft.body_text || "";
    const evidence = document.createElement("p");
    evidence.className = "assistant-draft-evidence";
    evidence.textContent = `依据：${(draft.source_evidence_ids || []).length} 条`;

    const failure = document.createElement("p");
    failure.className = "assistant-draft-failure";
    const guidance = draft.policy_result?.guidance || "请修改后重新确认，避免重复发送。";
    failure.textContent = `发送失败：${draft.reason || "提供方未接受请求"}。${guidance}`;
    failure.hidden = !["blocked", "failed", "rejected"].includes(draft.status);

    const actions = document.createElement("div");
    actions.className = "assistant-identity-actions compact";
    if (draft.status === "draft") {
      const confirm = button("确认并发送");
      confirm.addEventListener("click", () =>
        runAssistantIdentityTask(() => confirmAssistantDraft(draft.draft_id))
      );
      actions.appendChild(confirm);
    }
    if (["draft", "blocked"].includes(draft.status)) {
      const edit = button("修改");
      edit.className = "secondary";
      edit.addEventListener("click", () =>
        runAssistantIdentityTask(() => editAssistantDraft(draft.draft_id, draft))
      );
      const cancel = button("取消");
      cancel.className = "secondary";
      cancel.addEventListener("click", () =>
        runAssistantIdentityTask(() => cancelAssistantDraft(draft.draft_id))
      );
      actions.append(edit, cancel);
    }
    item.append(meta, title, recipient, body, evidence, failure);
    if (actions.children.length) item.appendChild(actions);
    chatAssistantDrafts.appendChild(item);
  }
  chatAssistantDrafts.hidden = !chatAssistantDrafts.children.length;
}

async function loadChatAssistantDrafts(parentContext = null) {
  if (!chatAssistantDrafts) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "chat-assistant-drafts",
    parentContext,
    load: () => api("/api/assistant-outbound/drafts?limit=20"),
    commit: (result) => renderChatAssistantDrafts(result.items || []),
    onError: () => {
      chatAssistantDrafts.replaceChildren();
      const error = document.createElement("p");
      error.className = "muted";
      error.textContent = "待确认草稿暂时无法读取。";
      chatAssistantDrafts.appendChild(error);
      chatAssistantDrafts.hidden = false;
    },
  });
}

function renderAssistantIdentityDrafts(items = []) {
  assistantIdentityDrafts.textContent = "";
  const pending = items.filter((item) => item.channel === "gmail" && ["draft", "blocked"].includes(item.status));
  for (const draft of pending.slice(0, 10)) {
    const item = appendAssistantIdentityListItem(assistantIdentityDrafts, {
      meta: `${assistantIdentityTimestamp(draft.updated_at || draft.created_at)} · ${assistantIdentityStatusLabel(draft.status)}`,
      title: draft.subject || "无主题邮件",
      body: `收件人：${draft.recipient || "未填写"}\n${draft.body_text || ""}`,
      status: draft.status,
    });
    item.dataset.draftId = draft.draft_id;
    const actions = document.createElement("div");
    actions.className = "assistant-identity-actions compact";
    if (draft.status === "draft") {
      const confirm = button("确认并发送");
      confirm.addEventListener("click", () =>
        runAssistantIdentityTask(() => confirmAssistantDraft(draft.draft_id))
      );
      actions.appendChild(confirm);
    }
    if (["draft", "blocked"].includes(draft.status)) {
      const edit = button("修改");
      edit.className = "secondary";
      edit.addEventListener("click", () =>
        runAssistantIdentityTask(() => editAssistantDraft(draft.draft_id, draft))
      );
      const cancel = button("取消");
      cancel.className = "secondary";
      cancel.addEventListener("click", () =>
        runAssistantIdentityTask(() => cancelAssistantDraft(draft.draft_id))
      );
      actions.append(edit, cancel);
    }
    item.appendChild(actions);
  }
  if (!assistantIdentityDrafts.children.length) assistantIdentityDrafts.appendChild(emptyCard("没有待确认草稿。"));
}

function renderAssistantIdentityHistory(items = []) {
  assistantIdentityHistory.textContent = "";
  for (const item of items.filter((entry) => entry.channel === "gmail").slice(0, 10)) {
    appendAssistantIdentityListItem(assistantIdentityHistory, {
      meta: `${assistantIdentityTimestamp(item.sent_at || item.updated_at || item.created_at)} · ${assistantIdentityStatusLabel(item.status)}`,
      title: item.subject || "无主题邮件",
      body: item.reason || item.provider_message_id || "提供方未返回消息编号",
      status: item.status,
    });
  }
  if (!assistantIdentityHistory.children.length) assistantIdentityHistory.appendChild(emptyCard("暂无发送记录。"));
}

function renderAssistantIdentityAudit(items = []) {
  assistantIdentityAudit.textContent = "";
  for (const item of items.slice(-10).reverse()) {
    appendAssistantIdentityListItem(assistantIdentityAudit, {
      meta: `${assistantIdentityTimestamp(item.created_at)} · ${item.actor || "system"}`,
      title: item.action || "审计事件",
      body: `${item.status || ""}${item.policy_result ? ` · ${item.policy_result}` : ""}`,
      status: item.status,
    });
  }
  if (!assistantIdentityAudit.children.length) assistantIdentityAudit.appendChild(emptyCard("暂无审计记录。"));
}

async function loadAssistantIdentities(parentContext = null) {
  if (!assistantIdentityGmail) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  assistantIdentityStatus.textContent = "正在读取服务端状态...";
  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "assistant-identities",
    parentContext,
    load: async () => {
      const identitiesData = await api("/api/assistant-identities");
      const gmail = (identitiesData.identities || []).find((item) => item.identity_id === "nomi_gmail_primary") || {
        identity_id: "nomi_gmail_primary",
        status: "unconfigured",
      };
      const identityId = gmail.identity_id;
      const results = await Promise.allSettled([
        api(`/api/assistant-identities/${identityId}/health`),
        api("/api/assistant-inbox?limit=20"),
        api("/api/assistant-outbound/drafts?limit=20"),
        api("/api/assistant-outbound/messages?limit=20"),
        api("/api/assistant-audit?limit=30"),
      ]);
      return { gmail, results };
    },
    commit: ({ gmail, results }) => {
      const [healthResult, inboxResult, draftsResult, historyResult, auditResult] = results;
      renderAssistantIdentityGmail(gmail, healthResult.status === "fulfilled" ? healthResult.value : {});
      renderAssistantIdentityInbox(inboxResult.status === "fulfilled" ? inboxResult.value.items : []);
      renderAssistantIdentityDrafts(draftsResult.status === "fulfilled" ? draftsResult.value.items : []);
      renderAssistantIdentityHistory(historyResult.status === "fulfilled" ? historyResult.value.items : []);
      renderAssistantIdentityAudit(auditResult.status === "fulfilled" ? auditResult.value.items : []);
      const failures = results.filter((result) => result.status === "rejected").length;
      assistantIdentityStatus.textContent = failures
        ? `${failures} 个数据区域暂时不可用，其余状态已从服务端刷新。`
        : "状态已从服务端刷新。";
    },
    onError: (error) => {
      assistantIdentityGmail.textContent = "助理身份状态加载失败。";
      assistantIdentityStatus.textContent = String(error?.message || "请检查服务端连接。");
    },
  });
}

async function connectAssistantGmail() {
  assistantIdentityStatus.textContent = "正在创建 Gmail 授权链接...";
  try {
    const result = await api("/api/assistant-identities/nomi_gmail_primary/connect-link", { method: "POST" });
    if (!result.redirect_url) throw new Error("授权服务未返回链接");
    window.location.assign(result.redirect_url);
  } catch (error) {
    assistantIdentityStatus.textContent = `无法开始授权：${String(error?.message || error)}`;
  }
}

async function verifyAssistantIdentity(identityId) {
  assistantIdentityStatus.textContent = "正在向提供方核验账号...";
  try {
    await api(`/api/assistant-identities/${identityId}/verify`, { method: "POST" });
  } finally {
    await loadAssistantIdentities();
  }
}

async function disableAssistantIdentity(identityId) {
  await api(`/api/assistant-identities/${identityId}/disable`, { method: "POST" });
  await loadAssistantIdentities();
}

async function enableAssistantIdentity(identityId) {
  await api(`/api/assistant-identities/${identityId}/enable`, { method: "POST" });
  await loadAssistantIdentities();
}

async function disconnectAssistantIdentity(identityId) {
  if (!window.confirm("断开 Nomi Gmail？历史审计会保留，但授权引用会被清除。")) return;
  await api(`/api/assistant-identities/${identityId}/disconnect`, { method: "POST" });
  await loadAssistantIdentities();
}

async function loadTools(parentContext = null) {
  const failureMessage = (error, fallback) => {
    if (!error) return fallback;
    const message = String(error.message || error || "").trim();
    return message || fallback;
  };
  if (!toolsContent) return false;
  if (!isRequestParentCurrent(parentContext)) return false;
  toolsContent.textContent = "";
  toolsContent.appendChild(renderBrowserLoginPanel({ collectors: [], loading: true }));

  return runLatestRequest({
    gate: workbenchRequestGate,
    key: "tools",
    parentContext,
    load: async () => {
      const [catalogResult, collectorResult, composioStatusResult] = await Promise.allSettled([
        api("/api/tools/catalog"),
        api("/api/collectors/status"),
        api("/api/integrations/composio/status"),
      ]);
      const data =
        catalogResult.status === "fulfilled"
          ? catalogResult.value
          : { tools: [], error: failureMessage(catalogResult.reason, "无法读取工具目录") };
      const collectorStatus =
        collectorResult.status === "fulfilled"
          ? collectorResult.value
          : { collectors: [], error: failureMessage(collectorResult.reason, "无法读取网页登录状态") };
      const composioStatus =
        composioStatusResult.status === "fulfilled"
          ? composioStatusResult.value
          : {
              configured: false,
              error: failureMessage(composioStatusResult.reason, "无法读取 Composio 状态"),
              readonly_toolkits: [],
            };
      const composioConnections = composioStatus.configured
        ? await api("/api/integrations/composio/toolkits?session_kind=readonly").catch((error) => ({
            toolkits: [],
            error: failureMessage(error, "无法同步 Composio 连接状态"),
          }))
        : { toolkits: [] };
      return { data, collectorStatus, composioStatus, composioConnections };
    },
    commit: ({ data, collectorStatus, composioStatus, composioConnections }) => {
      toolsContent.textContent = "";
      toolsContent.appendChild(renderBrowserLoginPanel(collectorStatus));
      toolsContent.appendChild(renderComposioPanel(composioStatus, composioConnections));
      const policy = card("card compact");
      policy.innerHTML = `<strong>执行权限规则</strong><p>读取可直接执行；写入、发消息、叫车、购买等动作都需要用户确认。付款/下单必须最终确认。</p>`;
      toolsContent.appendChild(policy);
      if (data.error) {
        toolsContent.appendChild(emptyCard("工具目录暂时不可用，网页登录入口仍可继续使用。"));
      }
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
    },
    onError: () => {
      toolsContent.textContent = "";
      toolsContent.appendChild(
        emptyCard("工具与账号连接状态暂时无法读取，请检查服务端连接后重试。")
      );
    },
  });
}

function collectorBySource(status) {
  return new Map((status.collectors || []).map((collector) => [collector.source, collector]));
}

function browserLoginStatusText(collector) {
  if (!collector) return "待检测";
  if (collector.status_label) return collector.status_label;
  if (collector.browser_login_status === "logged_in") return "已登录";
  if (collector.browser_login_status === "logged_out") return "未登录";
  if (collector.health_status === "healthy") return "采集正常";
  if (collector.health_status === "degraded") return "采集异常";
  return "待检测";
}

function renderBrowserLoginPanel(status) {
  const node = card("card integration-card");
  const collectors = collectorBySource(status);
  node.innerHTML = `
    <time>Managed Browser Login</time>
    <strong>云端浏览器登录</strong>
    <p>WhatsApp、Telegram、LinkedIn 等网页账号需要在服务器托管浏览器里登录。点击后会打开对应登录页和远程浏览器，账号密码仍由你自己输入。</p>
  `;
  const grid = document.createElement("div");
  grid.className = "connection-grid";
  for (const channel of browserLoginChannels) {
    const collector = collectors.get(channel.source);
    const row = document.createElement("div");
    row.className = "connection-row";
    const label = document.createElement("div");
    const detail = collector?.status_detail || channel.description;
    label.innerHTML = `<strong>${channel.name}</strong><span>${browserLoginStatusText(collector)} · ${detail}</span>`;
    const open = button(collector?.browser_login_status === "logged_in" ? "重新打开" : "打开登录");
    open.addEventListener("click", async () => {
      open.disabled = true;
      open.textContent = "打开中...";
      try {
        await api("/api/browser/open", {
          method: "POST",
          body: JSON.stringify({ source: channel.source }),
        });
        open.textContent = "已请求打开";
        const url = remoteBrowserUrl();
        if (url) {
          enterRemoteBrowserMode();
          openExternalUrl(url);
        }
      } catch {
        open.textContent = "打开失败";
      } finally {
        setTimeout(() => {
          open.disabled = false;
          open.textContent = collector?.browser_login_status === "logged_in" ? "重新打开" : "打开登录";
        }, 1800);
      }
    });
    row.append(label, open);
    grid.appendChild(row);
  }
  node.appendChild(grid);
  if (status.error) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = status.error;
    node.appendChild(note);
  } else if (status.loading) {
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = "正在同步网页登录状态...";
    node.appendChild(note);
  }
  return node;
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
  const guidanceRegion = document.createElement("section");
  guidanceRegion.className = "composio-guidance hidden";
  guidanceRegion.setAttribute("aria-live", "polite");
  guidanceRegion.setAttribute("role", "status");
  guidanceRegion.tabIndex = -1;
  const connectButtons = [];
  let connectBusy = false;
  let connectRequestSequence = 0;

  function clearGuidance() {
    guidanceRegion.replaceChildren();
    guidanceRegion.classList.add("hidden");
    guidanceRegion.classList.remove("success");
  }

  function showGuidance(error, retry) {
    const model = window.NomiComposioGuidance.guidanceForError(error);
    const title = document.createElement("strong");
    title.textContent = model.title;
    const message = document.createElement("p");
    message.textContent = model.message;
    const actions = document.createElement("div");
    actions.className = "composio-guidance-actions";
    if (model.showSettings) {
      const settingsButton = button("打开 Composio API Key 设置");
      settingsButton.className = "secondary";
      settingsButton.addEventListener("click", () => {
        window.open(model.settingsUrl, "_blank", "noopener,noreferrer");
      });
      actions.appendChild(settingsButton);
    }
    if (model.showRetry) {
      const retryButton = button("重试");
      retryButton.addEventListener("click", retry);
      actions.appendChild(retryButton);
    }
    guidanceRegion.replaceChildren(title, message, actions);
    guidanceRegion.classList.remove("success");
    guidanceRegion.classList.remove("hidden");
    guidanceRegion.focus();
  }

  function showAuthorizationLink(safeUrl) {
    const title = document.createElement("strong");
    title.textContent = "授权链接已生成";
    const message = document.createElement("p");
    message.textContent = "如果授权页没有自动打开，请点击下方按钮继续。";
    const actions = document.createElement("div");
    actions.className = "composio-guidance-actions";
    const manualLink = document.createElement("a");
    manualLink.className = "composio-guidance-manual-link";
    manualLink.href = safeUrl;
    manualLink.target = "_blank";
    manualLink.rel = "noopener noreferrer";
    manualLink.textContent = "打开授权";
    actions.appendChild(manualLink);
    guidanceRegion.replaceChildren(title, message, actions);
    guidanceRegion.classList.add("success");
    guidanceRegion.classList.remove("hidden");
    manualLink.focus();
  }

  function showAlreadyConnectedGuidance() {
    const title = document.createElement("strong");
    title.textContent = "账号已连接";
    const message = document.createElement("p");
    message.textContent = "Composio 已确认该账号连接有效。";
    guidanceRegion.replaceChildren(title, message);
    guidanceRegion.classList.add("success");
    guidanceRegion.classList.remove("hidden");
    guidanceRegion.focus();
  }

  function openComposioConnectUrl(safeUrl) {
    if (
      window.NomiAndroid &&
      typeof window.NomiAndroid.openExternalUrl === "function"
    ) {
      window.NomiAndroid.openExternalUrl(safeUrl);
    } else {
      window.open(safeUrl, "_blank", "noopener,noreferrer");
    }
    showAuthorizationLink(safeUrl);
  }

  function setConnectButtonsDisabled(disabled) {
    for (const buttonNode of connectButtons) {
      buttonNode.disabled = disabled || !status.configured;
    }
  }

  for (const slug of primaryToolkits) {
    const connection = connectedBySlug.get(slug);
    let isConnected = connection?.connected === true;
    const row = document.createElement("div");
    row.className = "connection-row";
    const label = document.createElement("div");
    const labelName = document.createElement("strong");
    labelName.textContent = connection?.name || slug;
    const connectionStatus = document.createElement("span");
    connectionStatus.textContent = isConnected ? "已连接" : "未连接";
    connectionStatus.tabIndex = -1;
    label.append(labelName, connectionStatus);
    const connect = button(isConnected ? "重新连接" : "连接");
    connect.disabled = !status.configured;
    connectButtons.push(connect);
    const attemptConnect = async () => {
      if (connectBusy) return;
      connectBusy = true;
      const requestId = ++connectRequestSequence;
      const guidanceHadFocus = guidanceRegion.contains(document.activeElement);
      clearGuidance();
      if (guidanceHadFocus) connectionStatus.focus();
      setConnectButtonsDisabled(true);
      connect.textContent = "生成链接...";
      try {
        const forceQuery = isConnected ? "?force=true" : "";
        const result = await api(`/api/integrations/composio/connect/${encodeURIComponent(slug)}${forceQuery}`, { method: "POST" });
        if (requestId !== connectRequestSequence) return;
        if (result.redirect_url) {
          const safeUrl = window.NomiComposioGuidance.safeConnectUrl(result.redirect_url);
          if (!safeUrl) throw new Error("授权服务返回了无效链接，请重试。");
          openComposioConnectUrl(safeUrl);
          return;
        }
        if (result.status === "already_connected") {
          isConnected = true;
          connectionStatus.textContent = "已连接";
          showAlreadyConnectedGuidance();
          return;
        }
        throw new Error("授权服务未返回链接，请重试。");
      } catch (error) {
        if (requestId !== connectRequestSequence) return;
        showGuidance(error, attemptConnect);
      } finally {
        if (requestId !== connectRequestSequence) return;
        connectBusy = false;
        connect.textContent = isConnected ? "重新连接" : "连接";
        setConnectButtonsDisabled(false);
      }
    };
    connect.addEventListener("click", attemptConnect);
    row.append(label, connect);
    grid.appendChild(row);
  }
  node.append(grid, guidanceRegion);
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
  if (!toolRouteResult) return;
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
  buttonNode.addEventListener("click", () => {
    workbenchNavigation.navigateToView(buttonNode.dataset.view);
  });
});

assistantSettingsToggle?.addEventListener("click", () => toggleAssistantSettings());
assistantSettingsClose?.addEventListener("click", () => toggleAssistantSettings(false));
settingsBackButton?.addEventListener("click", () => {
  workbenchNavigation.exitSettings();
});
assistantCloseButton?.addEventListener("click", closeAssistantWorkspace);
webSearchProviderBack?.addEventListener("click", closeWebSearchProviderDetail);
webSearchToggleKeyVisibility?.addEventListener("click", () => {
  webSearchKeyInput.type = webSearchKeyInput.type === "password" ? "text" : "password";
  const showing = webSearchKeyInput.type === "text";
  webSearchToggleKeyVisibility.title = showing ? "隐藏本次输入" : "显示本次输入";
  webSearchToggleKeyVisibility.setAttribute("aria-label", webSearchToggleKeyVisibility.title);
});
webSearchSaveAndTest?.addEventListener("click", () => saveAndTestWebSearchProvider(selectedWebSearchProvider));
webSearchTestStored?.addEventListener("click", () => testStoredWebSearchProvider(selectedWebSearchProvider));
webSearchDeleteKey?.addEventListener("click", () => deleteWebSearchProviderKey(selectedWebSearchProvider));
webSearchEnabledToggle?.addEventListener("change", () => {
  updateWebSearchProviderEnabled(selectedWebSearchProvider, webSearchEnabledToggle.checked);
});
webSearchSaveRouting?.addEventListener("click", saveWebSearchRouting);
window.addEventListener("pagehide", clearWebSearchKeyInput);
document.addEventListener?.("visibilitychange", () => {
  if (document.hidden) clearWebSearchKeyInput();
});
document.querySelectorAll(".assistant-settings-item").forEach((buttonNode) => {
  buttonNode.addEventListener("click", () => {
    workbenchNavigation.navigateToView(buttonNode.dataset.view);
    toggleAssistantSettings(false);
  });
});
document.querySelectorAll(".settings-nav-button").forEach((buttonNode) => {
  buttonNode.addEventListener("click", () => {
    const settingsSectionId = buttonNode.dataset.settingsSection;
    if (!settingsSectionIds.has(settingsSectionId)) return;
    workbenchNavigation.navigateToView(settingsSectionId);
  });
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

function localMessageAttachments(items) {
  return items.map((item) => ({
    attachment_id: item.attachment_id,
    filename: item.filename,
    mime_type: item.mime_type,
    byte_size: item.byte_size,
    status: item.status,
    kind: item.kind,
    preview_url: item.preview_url,
    content_url: item.content_url,
  }));
}

function renderAssistantRetry(node) {
  if (!node || node.querySelector(".assistant-retry")) return;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "assistant-retry";
  retry.textContent = "重试回复";
  retry.addEventListener("click", async () => {
    if (!activeChatAttempt) return;
    const payload = AttachmentDraft.beginSend(activeChatAttempt.text, attachmentDraft);
    if (!payload) return;
    activeChatAttempt.payload = { ...payload, conversation_id: chatConversationId || undefined, client_type: "web" };
    node.textContent = realtimePendingText;
    await submitChatOverHttp(activeChatAttempt.payload, node);
  });
  node.appendChild(retry);
}

async function submitChatOverHttp(payload, pendingNode) {
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (result.conversation_id) setChatConversationId(result.conversation_id);
    renderMessageContent(pendingNode, result.answer);
    if (result.sources?.length) pendingNode.appendChild(renderSources(result.sources));
    AttachmentDraft.commitSend(attachmentDraft, result.client_request_id || payload.client_request_id);
    activeChatAttempt = null;
    renderAttachmentTray();
    void loadChatAssistantDrafts();
  } catch {
    pendingNode.textContent = "请求失败，请检查模型服务或访问密码。";
    AttachmentDraft.markTransportFailed(attachmentDraft);
    renderAttachmentTray();
    renderAssistantRetry(pendingNode);
  } finally {
    refocusMessageInput();
  }
}

async function submitChatMessage() {
  const text = messageInput.value.trim();
  const payload = AttachmentDraft.beginSend(text, attachmentDraft);
  if (!payload) return;
  payload.conversation_id = chatConversationId || undefined;
  payload.client_type = "web";
  const selectedAttachments = localMessageAttachments(attachmentDraft.items);
  activeChatAttempt = { payload, text, attachments: selectedAttachments };
  messageInput.value = "";
  addMessage("user", text, [], selectedAttachments);
  renderAttachmentTray();
  refocusMessageInput();
  if (realtimeReady && realtimeSocket?.readyState === WebSocket.OPEN) {
    activeAssistantNode = addMessage("assistant", realtimePendingText);
    realtimeChatHadDelta = false;
    startRealtimeChatWatchdog();
    try {
      realtimeSocket.send(JSON.stringify({ type: "chat_message", ...payload }));
    } catch {
      failActiveRealtimeChat("实时通道发送失败，请重新发送或检查网络。");
    }
    refocusMessageInput();
    return;
  }
  const pendingNode = addMessage("assistant", realtimePendingText);
  await submitChatOverHttp(payload, pendingNode);
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitChatMessage();
});

attachmentButton.addEventListener("click", () => attachmentInput.click());
attachmentInput.addEventListener("change", () => {
  attachmentTrayError = "";
  const selected = Array.from(attachmentInput.files || []);
  const accepted = [];
  for (const file of selected) {
    try {
      accepted.push(AttachmentDraft.addSelectedFile(attachmentDraft, file));
    } catch (error) {
      attachmentTrayError = error.message || "无法添加附件。";
      break;
    }
  }
  attachmentInput.value = "";
  renderAttachmentTray();
  accepted.forEach((item) => uploadAttachment(item));
});
messageInput.addEventListener("input", updateAttachmentControls);
if (typeof document.addEventListener === "function") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      attachmentDraft.items.forEach(clearAttachmentPoll);
      return;
    }
    attachmentDraft.items.forEach(scheduleAttachmentPoll);
  });
}
if (AttachmentDraft) renderAttachmentTray();

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

workbenchNavigation.bindHashChanges(window);
window.addEventListener("nomi-pending-proactive", consumePendingProactive);

searchForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (query) loadSearch(query);
});
governanceFilters?.addEventListener("submit", (event) => {
  event.preventDefault();
  loadGovernance();
});
refreshGovernance?.addEventListener("click", loadGovernance);
refreshAgenda?.addEventListener("click", loadAgenda);
refreshCareer?.addEventListener("click", loadCareerBoard);
careerOffers?.addEventListener("click", loadCareerOffers);
careerAtsListPreview?.addEventListener("click", previewCareerAtsList);
careerAtsPreviewForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  previewCareerAtsPage();
});
careerProfileIngestForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  ingestCareerProfile();
});
careerResumeFileImportForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  importCareerResumeFile();
});
refreshSuggestions?.addEventListener("click", () => loadSuggestions(currentSuggestionFocusId()));
refreshCollectors?.addEventListener("click", loadCollectors);
refreshAssistantIdentities?.addEventListener("click", loadAssistantIdentities);
refreshTools?.addEventListener("click", loadTools);
toolRouteForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const request = toolRouteInput?.value.trim() || "";
  if (request) routeToolRequest(request);
});
fieldReleaseForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  releaseSensitiveField();
});

if (password()) showApp();
}
