(function attachModule(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NomiChatAttachments = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createAttachmentModule() {
  "use strict";

  const MAX_ATTACHMENTS = 8;
  const MAX_TOTAL_BYTES = 64 * 1024 * 1024;
  const TERMINAL_STATUSES = new Set(["ready", "failed", "rejected", "deleted", "expired"]);
  const POLLABLE_STATUSES = new Set(["uploaded", "queued", "processing"]);

  function defaultIdFactory() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
    return `nomi-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function draftError(code, message) {
    const error = new Error(message || code);
    error.code = code;
    return error;
  }

  function createDraftState(options = {}) {
    return {
      items: [],
      idFactory: options.idFactory || defaultIdFactory,
      client_request_id: null,
      in_flight_request_id: null,
    };
  }

  function totalBytes(draft) {
    return draft.items.reduce((sum, item) => sum + Number(item.byte_size || 0), 0);
  }

  function addSelectedFile(draft, file) {
    if (draft.items.length >= MAX_ATTACHMENTS) {
      throw draftError("too_many_attachments", "单条消息最多选择 8 个附件。");
    }
    const byteSize = Number(file && file.size || 0);
    if (byteSize < 0 || totalBytes(draft) + byteSize > MAX_TOTAL_BYTES) {
      throw draftError("attachments_too_large", "单条消息的附件总大小不能超过 64 MiB。");
    }
    const item = {
      file,
      filename: String(file && file.name || "attachment"),
      mime_type: String(file && file.type || "application/octet-stream"),
      byte_size: byteSize,
      client_upload_id: String(draft.idFactory()),
      attachment_id: null,
      status: "selected",
      kind: "file",
      preview_url: null,
      content_url: null,
      error_code: null,
      error_message: null,
    };
    draft.items.push(item);
    return item;
  }

  function itemAt(draft, index) {
    const item = draft.items[index];
    if (!item) throw draftError("attachment_not_found", "附件草稿不存在。");
    return item;
  }

  function applyServerState(item, state = {}) {
    if (state.attachment_id) item.attachment_id = String(state.attachment_id);
    if (state.filename) item.filename = String(state.filename);
    if (state.mime_type) item.mime_type = String(state.mime_type);
    if (state.byte_size !== undefined) item.byte_size = Number(state.byte_size || 0);
    if (state.kind) item.kind = String(state.kind);
    if (state.preview_url !== undefined) item.preview_url = state.preview_url;
    if (state.content_url !== undefined) item.content_url = state.content_url;
    item.error_code = state.error_code || null;
    item.error_message = state.error_message || null;
    return item;
  }

  function markUploading(draft, index) {
    const item = itemAt(draft, index);
    item.status = "uploading";
    item.error_code = null;
    item.error_message = null;
    return item;
  }

  function markUploaded(draft, index, state = {}) {
    const item = applyServerState(itemAt(draft, index), state);
    item.status = state.status === "ready" ? "ready" : String(state.status || "processing");
    return item;
  }

  function markReady(draft, index, state = {}) {
    const item = applyServerState(itemAt(draft, index), state);
    item.status = "ready";
    return item;
  }

  function markFailed(draft, index, state = {}) {
    const item = applyServerState(itemAt(draft, index), state);
    item.status = String(state.status || "failed");
    item.error_code = state.error_code || "attachment_failed";
    item.error_message = state.error_message || "附件处理失败。";
    return item;
  }

  function retryItem(draft, index) {
    const item = itemAt(draft, index);
    item.attachment_id = null;
    item.status = "selected";
    item.preview_url = null;
    item.content_url = null;
    item.error_code = null;
    item.error_message = null;
    return item;
  }

  function removeItem(draft, index) {
    const removed = draft.items.splice(index, 1)[0];
    if (!removed) throw draftError("attachment_not_found", "附件草稿不存在。");
    return removed;
  }

  function shouldPoll(item, documentVisible = true) {
    return Boolean(documentVisible && item && item.attachment_id && POLLABLE_STATUSES.has(item.status));
  }

  function canSend(text, draft) {
    if (!draft || draft.in_flight_request_id) return false;
    const hasText = Boolean(String(text || "").trim());
    const hasAttachments = draft.items.length > 0;
    if (!hasText && !hasAttachments) return false;
    return draft.items.every((item) => item.status === "ready" && item.attachment_id);
  }

  function ensureClientRequestId(draft) {
    if (!draft.client_request_id) draft.client_request_id = String(draft.idFactory());
    return draft.client_request_id;
  }

  function buildChatPayload(text, draft) {
    return {
      message: String(text || "").trim(),
      attachment_ids: draft.items.map((item) => item.attachment_id).filter(Boolean),
      client_request_id: ensureClientRequestId(draft),
    };
  }

  function beginSend(text, draft) {
    if (!canSend(text, draft)) return null;
    const payload = buildChatPayload(text, draft);
    draft.in_flight_request_id = payload.client_request_id;
    return payload;
  }

  function markTransportFailed(draft) {
    draft.in_flight_request_id = null;
  }

  function commitSend(draft, clientRequestId) {
    if (!draft.in_flight_request_id || draft.in_flight_request_id !== clientRequestId) return false;
    draft.items.splice(0, draft.items.length);
    draft.in_flight_request_id = null;
    draft.client_request_id = null;
    return true;
  }

  function attachmentKey(item, index) {
    return String(item && (item.attachment_id || item.client_upload_id) || `attachment-${index}`);
  }

  function mergeAttachments(local = [], remote = []) {
    const merged = new Map();
    local.forEach((item, index) => merged.set(attachmentKey(item, index), { ...item }));
    remote.forEach((item, index) => {
      const key = attachmentKey(item, index);
      merged.set(key, { ...(merged.get(key) || {}), ...item });
    });
    return Array.from(merged.values());
  }

  function messageKey(message, index) {
    return String(message && (message.id || message.message_id || message.client_request_id) || `message-${index}`);
  }

  function mergeHistory(local = [], remote = []) {
    const order = [];
    const merged = new Map();
    local.forEach((message, index) => {
      const key = messageKey(message, index);
      order.push(key);
      merged.set(key, { ...message, attachments: mergeAttachments([], message.attachments || []) });
    });
    remote.forEach((message, index) => {
      const key = messageKey(message, index);
      if (!merged.has(key)) order.push(key);
      const current = merged.get(key) || {};
      merged.set(key, {
        ...current,
        ...message,
        attachments: mergeAttachments(current.attachments || [], message.attachments || []),
      });
    });
    return order.map((key) => merged.get(key));
  }

  return {
    MAX_ATTACHMENTS,
    MAX_TOTAL_BYTES,
    TERMINAL_STATUSES,
    addSelectedFile,
    beginSend,
    buildChatPayload,
    canSend,
    commitSend,
    createDraftState,
    ensureClientRequestId,
    markFailed,
    markReady,
    markTransportFailed,
    markUploaded,
    markUploading,
    mergeHistory,
    removeItem,
    retryItem,
    shouldPoll,
    totalBytes,
  };
});
