(function attachModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NomiComposioGuidance = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createComposioGuidanceModule() {
  "use strict";

  const DASHBOARD_URL = "https://dashboard.composio.dev";
  const FALLBACK_MESSAGE = "请求失败，请稍后重试。";

  function isObjectRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function safeSettingsUrl(value) {
    try {
      const candidate = new URL(value);
      if (
        candidate.protocol !== "https:" ||
        candidate.hostname !== "dashboard.composio.dev" ||
        candidate.username ||
        candidate.password
      ) {
        return DASHBOARD_URL;
      }
      return candidate.pathname === "/" && !candidate.search && !candidate.hash
        ? DASHBOARD_URL
        : candidate.toString();
    } catch (_error) {
      return DASHBOARD_URL;
    }
  }

  function createApiError(status, rawText) {
    let payload = null;
    try {
      payload = JSON.parse(rawText);
    } catch (_error) {
      payload = null;
    }

    const source = isObjectRecord(payload && payload.detail)
      ? payload.detail
      : (isObjectRecord(payload) ? payload : {});
    const message = typeof source.message === "string" && source.message
      ? source.message
      : FALLBACK_MESSAGE;
    const error = new Error(message);
    error.status = Number(status);
    error.code = typeof source.code === "string" ? source.code : null;
    error.settingsUrl = safeSettingsUrl(source.settings_url);
    error.requiredPermissions = Array.isArray(source.required_permissions)
      ? source.required_permissions.slice()
      : [];
    error.retryable = source.retryable === true;
    return error;
  }

  function safeErrorMessage(error, fallback) {
    if (!error || typeof error.message !== "string") return fallback;
    const normalized = error.message.trim();
    if (
      !normalized ||
      normalized.startsWith("{") ||
      normalized.startsWith("[") ||
      normalized.includes("<") ||
      normalized.includes(">")
    ) {
      return fallback;
    }
    return error.message;
  }

  function guidanceForError(error) {
    if (error && error.code === "composio_api_key_insufficient_permissions") {
      return {
        title: "Composio API Key 权限不足",
        message: "当前 Key 无法创建授权会话。请创建具备 Sessions 读写权限的 Key，并更新 Nomi 配置。",
        settingsUrl: safeSettingsUrl(error.settingsUrl),
        showSettings: true,
        showRetry: true,
      };
    }
    if (error && error.code === "composio_api_key_invalid") {
      return {
        title: "Composio API Key 无效",
        message: safeErrorMessage(error, "Composio API Key 无效，请更新配置。"),
        settingsUrl: safeSettingsUrl(error.settingsUrl),
        showSettings: true,
        showRetry: true,
      };
    }
    return {
      title: "Composio 连接失败",
      message: safeErrorMessage(error, FALLBACK_MESSAGE),
      settingsUrl: safeSettingsUrl(error && error.settingsUrl),
      showSettings: false,
      showRetry: true,
    };
  }

  return {
    DASHBOARD_URL,
    createApiError,
    guidanceForError,
    safeSettingsUrl,
  };
});
