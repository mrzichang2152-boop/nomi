const test = require("node:test");
const assert = require("node:assert/strict");

const attachments = require("../app/static/chat-attachments.js");

function file(name, size, type) {
  return { name, size, type };
}

test("attachment-only draft becomes sendable only when every item is ready", () => {
  const draft = attachments.createDraftState({ idFactory: () => "upload-1" });
  attachments.addSelectedFile(draft, file("图.png", 120, "image/png"));
  assert.equal(attachments.canSend("", draft), false);

  attachments.markReady(draft, 0, { attachment_id: "a-1", status: "ready" });

  assert.equal(attachments.canSend("", draft), true);
  assert.deepEqual(attachments.buildChatPayload("", draft).attachment_ids, ["a-1"]);
});

test("text and attachment payload preserves the user's selection order", () => {
  let sequence = 0;
  const draft = attachments.createDraftState({ idFactory: () => `upload-${++sequence}` });
  attachments.addSelectedFile(draft, file("brief.pdf", 200, "application/pdf"));
  attachments.addSelectedFile(draft, file("photo.jpg", 100, "image/jpeg"));
  attachments.markReady(draft, 1, { attachment_id: "image-id" });
  attachments.markReady(draft, 0, { attachment_id: "document-id" });

  const payload = attachments.buildChatPayload("请结合附件分析", draft);

  assert.equal(payload.message, "请结合附件分析");
  assert.deepEqual(payload.attachment_ids, ["document-id", "image-id"]);
});

test("client rejects more than eight files and more than 64 MiB total", () => {
  const draft = attachments.createDraftState({ idFactory: () => crypto.randomUUID() });
  for (let index = 0; index < 8; index += 1) {
    attachments.addSelectedFile(draft, file(`${index}.txt`, 1, "text/plain"));
  }
  assert.throws(
    () => attachments.addSelectedFile(draft, file("ninth.txt", 1, "text/plain")),
    (error) => error.code === "too_many_attachments"
  );

  const oversized = attachments.createDraftState({ idFactory: () => crypto.randomUUID() });
  attachments.addSelectedFile(oversized, file("large.pdf", 64 * 1024 * 1024, "application/pdf"));
  assert.throws(
    () => attachments.addSelectedFile(oversized, file("one-more-byte.txt", 1, "text/plain")),
    (error) => error.code === "attachments_too_large"
  );
});

test("polling runs only for visible non-terminal uploaded drafts", () => {
  const draft = attachments.createDraftState({ idFactory: () => "stable-upload" });
  attachments.addSelectedFile(draft, file("report.docx", 10, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"));
  const item = draft.items[0];
  assert.equal(attachments.shouldPoll(item, true), false);

  attachments.markUploaded(draft, 0, { attachment_id: "a-1", status: "stored" });
  assert.equal(attachments.shouldPoll(item, true), true);

  attachments.markUploaded(draft, 0, { attachment_id: "a-1", status: "processing" });
  assert.equal(attachments.shouldPoll(item, true), true);
  assert.equal(attachments.shouldPoll(item, false), false);

  attachments.markReady(draft, 0, { attachment_id: "a-1", status: "ready" });
  assert.equal(attachments.shouldPoll(item, true), false);
});

test("retry preserves client_upload_id and remove preserves the text-owned draft", () => {
  const draft = attachments.createDraftState({ idFactory: () => "stable-upload" });
  attachments.addSelectedFile(draft, file("broken.pdf", 10, "application/pdf"));
  attachments.markFailed(draft, 0, { error_code: "parse_failed", error_message: "无法解析" });

  const retried = attachments.retryItem(draft, 0);
  assert.equal(retried.client_upload_id, "stable-upload");
  assert.equal(retried.status, "selected");
  assert.equal(retried.attachment_id, null);
  assert.equal(attachments.removeItem(draft, 0).filename, "broken.pdf");
  assert.equal(draft.items.length, 0);
});

test("transport fallback reuses one client request id and cannot double submit", () => {
  let sequence = 0;
  const draft = attachments.createDraftState({ idFactory: () => `id-${++sequence}` });
  attachments.addSelectedFile(draft, file("note.txt", 10, "text/plain"));
  attachments.markReady(draft, 0, { attachment_id: "a-1" });

  const first = attachments.beginSend("分析", draft);
  assert.equal(attachments.beginSend("分析", draft), null);
  attachments.markTransportFailed(draft);
  const fallback = attachments.beginSend("分析", draft);

  assert.equal(first.client_request_id, fallback.client_request_id);
  assert.deepEqual(first.attachment_ids, fallback.attachment_ids);
});

test("committed send clears files and rotates ids only after acknowledgement", () => {
  let sequence = 0;
  const draft = attachments.createDraftState({ idFactory: () => `id-${++sequence}` });
  attachments.addSelectedFile(draft, file("note.txt", 10, "text/plain"));
  attachments.markReady(draft, 0, { attachment_id: "a-1" });
  const sent = attachments.beginSend("", draft);

  assert.equal(draft.items.length, 1);
  assert.equal(attachments.commitSend(draft, "wrong-id"), false);
  assert.equal(draft.items.length, 1);
  assert.equal(attachments.commitSend(draft, sent.client_request_id), true);
  assert.equal(draft.items.length, 0);
  assert.notEqual(attachments.ensureClientRequestId(draft), sent.client_request_id);
});

test("history merge deduplicates messages and attachments by stable ids", () => {
  const local = [{
    id: "m-1",
    role: "user",
    content: "本地",
    attachments: [{ attachment_id: "a-1", filename: "one.pdf" }],
  }];
  const remote = [
    {
      id: "m-1",
      role: "user",
      content: "服务端",
      attachments: [
        { attachment_id: "a-1", filename: "one.pdf" },
        { attachment_id: "a-2", filename: "two.png" },
      ],
    },
    { id: "m-2", role: "assistant", content: "完成" },
  ];

  const merged = attachments.mergeHistory(local, remote);

  assert.deepEqual(merged.map((message) => message.id), ["m-1", "m-2"]);
  assert.equal(merged[0].content, "服务端");
  assert.deepEqual(merged[0].attachments.map((item) => item.attachment_id), ["a-1", "a-2"]);
});
