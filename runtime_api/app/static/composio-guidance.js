(function attachModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NomiComposioGuidance = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createComposioGuidanceModule() {
  "use strict";

  const DASHBOARD_URL = "https://dashboard.composio.dev";
  const DASHBOARD_ORIGIN = new URL(DASHBOARD_URL).origin;
  const CONNECT_ORIGIN = new URL("https://connect.composio.dev").origin;
  const FALLBACK_MESSAGE = "请求失败，请稍后重试。";
  const PUBLIC_MESSAGES = Object.freeze({
    composio_api_key_insufficient_permissions: "Composio API Key 权限不足，无法创建账号授权会话。",
    composio_api_key_invalid: "Composio API Key 无效或已失效。",
    composio_connect_failed: "Composio 暂时无法创建授权链接，请稍后重试。",
    composio_rate_limited: "Composio 服务请求频率受限，请稍后重试。",
    composio_upstream_unavailable: "Composio 上游服务暂时不可用。",
  });

  function isObjectRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function safeSettingsUrl(value) {
    try {
      const candidate = new URL(value);
      if (
        candidate.origin !== DASHBOARD_ORIGIN ||
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

  function safeConnectUrl(value) {
    try {
      const candidate = new URL(value);
      if (
        candidate.origin !== CONNECT_ORIGIN ||
        candidate.username ||
        candidate.password
      ) {
        return "";
      }
      return candidate.toString();
    } catch (_error) {
      return "";
    }
  }

  function publicMessageForCode(code) {
    return Object.prototype.hasOwnProperty.call(PUBLIC_MESSAGES, code)
      ? PUBLIC_MESSAGES[code]
      : FALLBACK_MESSAGE;
  }

  function normalizedStatus(value) {
    try {
      const status = Number(value);
      return Number.isInteger(status) && status >= 100 && status <= 599 ? status : 0;
    } catch (_error) {
      return 0;
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
    const code = typeof source.code === "string" && source.code.trim()
      ? source.code
      : "request_failed";
    const error = new Error(publicMessageForCode(code));
    error.status = normalizedStatus(status);
    error.code = code;
    error.settingsUrl = safeSettingsUrl(source.settings_url);
    error.requiredPermissions = Array.isArray(source.required_permissions)
      ? source.required_permissions.slice()
      : [];
    // Provider/automatic retry semantics; guidance keeps manual retry available.
    error.retryable = source.retryable !== false;
    return error;
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
        message: publicMessageForCode(error.code),
        settingsUrl: safeSettingsUrl(error.settingsUrl),
        showSettings: true,
        showRetry: true,
      };
    }
    return {
      title: "Composio 连接失败",
      message: publicMessageForCode(error && error.code),
      settingsUrl: safeSettingsUrl(error && error.settingsUrl),
      showSettings: false,
      showRetry: true,
    };
  }

  return {
    DASHBOARD_URL,
    createApiError,
    guidanceForError,
    safeConnectUrl,
    safeSettingsUrl,
  };
});
