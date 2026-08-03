const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const guidance = require("../app/static/composio-guidance.js");

test("browser branch attaches guidance to globalThis without CommonJS", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "../app/static/composio-guidance.js"),
    "utf8"
  );
  const context = vm.createContext({ URL });

  assert.equal("module" in context, false);
  vm.runInContext(source, context);

  assert.equal(typeof context.NomiComposioGuidance, "object");
  assert.equal(
    context.NomiComposioGuidance.safeSettingsUrl("https://dashboard.composio.dev/settings"),
    "https://dashboard.composio.dev/settings"
  );
  assert.equal(
    context.NomiComposioGuidance.safeSettingsUrl("https://dashboard.composio.dev:444/settings"),
    context.NomiComposioGuidance.DASHBOARD_URL
  );
});

test("safeSettingsUrl accepts the fixed Composio dashboard URL", () => {
  assert.equal(globalThis.NomiComposioGuidance, guidance);
  assert.equal(
    guidance.safeSettingsUrl("https://dashboard.composio.dev/"),
    guidance.DASHBOARD_URL
  );
  assert.equal(
    guidance.safeSettingsUrl("https://dashboard.composio.dev/settings/api-keys?tab=permissions#sessions"),
    "https://dashboard.composio.dev/settings/api-keys?tab=permissions#sessions"
  );
  assert.equal(
    guidance.safeSettingsUrl("https://dashboard.composio.dev:443/settings"),
    "https://dashboard.composio.dev/settings"
  );
});

test("safeSettingsUrl rejects insecure and deceptive URLs", () => {
  const unsafeValues = [
    "http://dashboard.composio.dev",
    "https://attacker.example@dashboard.composio.dev/settings",
    "https://dashboard.composio.dev@attacker.example/settings",
    "https://sub.dashboard.composio.dev/settings",
    "https://dashboard.composio.dev.attacker.example/settings",
    "https://dashboard.composio.dev:444/settings",
    "https://attacker.example/settings",
    "javascript:alert(1)",
    "not a URL",
  ];

  for (const value of unsafeValues) {
    assert.equal(guidance.safeSettingsUrl(value), guidance.DASHBOARD_URL, value);
  }
});

test("safeConnectUrl accepts only the exact Composio Connect HTTPS origin", () => {
  assert.equal(
    guidance.safeConnectUrl("https://connect.composio.dev/link/ln_123?source=nomi#authorize"),
    "https://connect.composio.dev/link/ln_123?source=nomi#authorize"
  );
  assert.equal(
    guidance.safeConnectUrl("https://connect.composio.dev:443/link/ln_123"),
    "https://connect.composio.dev/link/ln_123"
  );
});

test("safeConnectUrl rejects insecure, deceptive, and non-Connect URLs without fallback", () => {
  const unsafeValues = [
    "http://connect.composio.dev/link/ln_123",
    "https://attacker.example@connect.composio.dev/link/ln_123",
    "https://connect.composio.dev@attacker.example/link/ln_123",
    "https://sub.connect.composio.dev/link/ln_123",
    "https://connect.composio.dev.attacker.example/link/ln_123",
    "https://connect.composio.dev:444/link/ln_123",
    "https://dashboard.composio.dev/link/ln_123",
    "javascript:alert(1)",
    "not a URL",
    "",
  ];

  for (const value of unsafeValues) {
    assert.equal(guidance.safeConnectUrl(value), "", value);
  }
});

test("createApiError parses a structured permission failure into a real Error", () => {
  const error = guidance.createApiError("403", JSON.stringify({
    detail: {
      code: "composio_api_key_insufficient_permissions",
      message: "provider detail token=ak_live_permission_secret",
      settings_url: "https://dashboard.composio.dev/settings/api-keys",
      required_permissions: ["sessions:read", "sessions:write"],
      retryable: false,
    },
  }));

  assert.ok(error instanceof Error);
  assert.equal(error.status, 403);
  assert.equal(error.code, "composio_api_key_insufficient_permissions");
  assert.equal(error.message, "Composio API Key 权限不足，无法创建账号授权会话。");
  assert.equal(error.settingsUrl, "https://dashboard.composio.dev/settings/api-keys");
  assert.deepEqual(error.requiredPermissions, ["sessions:read", "sessions:write"]);
  assert.equal(error.retryable, false);
});

test("createApiError reads a top-level payload when detail is not an object", () => {
  const requiredPermissions = [{ area: "sessions", access: "read_and_write" }];
  const error = guidance.createApiError(503, JSON.stringify({
    detail: "not structured",
    code: "composio_rate_limited",
    message: "provider detail token=ak_live_rate_secret",
    settings_url: "https://dashboard.composio.dev.attacker.example/steal",
    required_permissions: requiredPermissions,
    retryable: true,
  }));

  assert.equal(error.code, "composio_rate_limited");
  assert.equal(error.message, "Composio 服务请求频率受限，请稍后重试。");
  assert.equal(error.settingsUrl, guidance.DASHBOARD_URL);
  assert.deepEqual(error.requiredPermissions, requiredPermissions);
  assert.equal(error.retryable, true);
});

test("createApiError never echoes non-JSON, HTML, or malformed JSON bodies", () => {
  const unsafeBodies = [
    "provider request failed with secret ak_live_123",
    "<html><body>private gateway failure</body></html>",
    '{"detail":{"message":"truncated secret"}',
    '{"private_provider_error":"raw JSON body"}',
  ];

  for (const rawText of unsafeBodies) {
    const error = guidance.createApiError(502, rawText);
    assert.ok(error instanceof Error);
    assert.equal(error.message, "请求失败，请稍后重试。");
    assert.equal(error.message.includes(rawText), false);
    assert.equal(error.code, "request_failed");
    assert.equal(error.settingsUrl, guidance.DASHBOARD_URL);
    assert.deepEqual(error.requiredPermissions, []);
    assert.equal(error.retryable, true);
    const model = guidance.guidanceForError(error);
    assert.equal(model.message, "请求失败，请稍后重试。");
    assert.equal(model.showSettings, false);
    assert.equal(model.showRetry, true);
  }
});

test("createApiError allowlists fields without prototype pollution", () => {
  const error = guidance.createApiError(500, '{"detail":{"__proto__":{"polluted":true},"polluted":true,"unknown_payload":{"secret":"private"},"required_permissions":{"__proto__":{"polluted":true}}}}');

  assert.deepEqual(error.requiredPermissions, []);
  assert.equal(error.polluted, undefined);
  assert.equal(error.unknown_payload, undefined);
  assert.equal({}.polluted, undefined);
  assert.equal(Object.getPrototypeOf(error), Error.prototype);
  assert.deepEqual(Object.keys(error).sort(), [
    "code",
    "requiredPermissions",
    "retryable",
    "settingsUrl",
    "status",
  ]);
});

test("createApiError normalizes status and applies safe defaults", () => {
  for (const status of [Number.NaN, "not-a-status", undefined, -1, 700]) {
    assert.equal(guidance.createApiError(status, "{}").status, 0, String(status));
  }

  const error = guidance.createApiError("502", "{}");
  assert.equal(error.status, 502);
  assert.equal(error.code, "request_failed");
  assert.equal(error.message, "请求失败，请稍后重试。");
  assert.equal(error.retryable, true);

  const explicitlyNotRetryable = guidance.createApiError(403, JSON.stringify({
    detail: { code: "composio_api_key_invalid", retryable: false },
  }));
  assert.equal(explicitlyNotRetryable.retryable, false);
  assert.equal(guidance.guidanceForError(explicitlyNotRetryable).showRetry, true);
});

test("unknown structured provider messages are never exposed", () => {
  const secret = "ak_live_secret";
  const error = guidance.createApiError(502, JSON.stringify({
    detail: {
      code: "unknown_provider_failure",
      message: `provider failed; token=${secret}`,
      retryable: true,
    },
  }));

  assert.equal(error.code, "unknown_provider_failure");
  assert.equal(error.message, "请求失败，请稍后重试。");
  assert.equal(error.message.includes(secret), false);

  const model = guidance.guidanceForError(error);
  assert.equal(model.message, "请求失败，请稍后重试。");
  assert.equal(model.message.includes(secret), false);
  assert.equal(model.showSettings, false);
  assert.equal(model.showRetry, true);
});

test("guidanceForError returns the permission guidance model with manual retry", () => {
  const error = guidance.createApiError(403, JSON.stringify({
    detail: {
      code: "composio_api_key_insufficient_permissions",
      message: "upstream text must not replace the permission guidance",
      settings_url: "https://attacker.example/steal",
      retryable: false,
    },
  }));

  assert.equal(error.retryable, false);
  assert.deepEqual(guidance.guidanceForError(error), {
    title: "Composio API Key 权限不足",
    message: "当前 Key 无法创建授权会话。请创建具备 Sessions 读写权限的 Key，并更新 Nomi 配置。",
    settingsUrl: guidance.DASHBOARD_URL,
    showSettings: true,
    showRetry: true,
  });
});

test("guidanceForError shows settings for an invalid Composio API key", () => {
  const error = guidance.createApiError(401, JSON.stringify({
    detail: {
      code: "composio_api_key_invalid",
      message: "provider detail token=ak_live_invalid_secret",
      settings_url: "https://dashboard.composio.dev/settings/api-keys",
      retryable: false,
    },
  }));

  assert.deepEqual(guidance.guidanceForError(error), {
    title: "Composio API Key 无效",
    message: "Composio API Key 无效或已失效。",
    settingsUrl: "https://dashboard.composio.dev/settings/api-keys",
    showSettings: true,
    showRetry: true,
  });
});

test("generic Composio failures allow retry without exposing settings", () => {
  const cases = [
    [502, "composio_connect_failed", "Composio 暂时无法创建授权链接，请稍后重试。"],
    [503, "composio_rate_limited", "Composio 服务请求频率受限，请稍后重试。"],
    [502, "composio_upstream_unavailable", "Composio 上游服务暂时不可用。"],
  ];

  for (const [status, code, message] of cases) {
    const error = guidance.createApiError(status, JSON.stringify({
      detail: { code, message: `provider detail token=ak_live_${code}`, retryable: true },
    }));
    assert.equal(error.retryable, true, code);
    assert.equal(error.message, message, code);
    assert.deepEqual(guidance.guidanceForError(error), {
      title: "Composio 连接失败",
      message,
      settingsUrl: guidance.DASHBOARD_URL,
      showSettings: false,
      showRetry: true,
    }, code);
  }
});

test("guidanceForError replaces direct HTML and raw JSON messages with a safe local message", () => {
  for (const message of [
    "<html><body>private upstream failure</body></html>",
    '{"secret":"raw provider body"}',
  ]) {
    const error = new Error(message);
    error.code = "composio_connect_failed";

    const model = guidance.guidanceForError(error);
    assert.equal(model.message, "Composio 暂时无法创建授权链接，请稍后重试。");
    assert.equal(model.showSettings, false);
    assert.equal(model.showRetry, true);
  }
});
