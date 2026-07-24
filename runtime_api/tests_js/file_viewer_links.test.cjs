const test = require("node:test");
const assert = require("node:assert/strict");

const links = require("../app/static/file-viewer-links.js");

const ATTACHMENT = "/api/chat/attachments/11111111-1111-4111-8111-111111111111/content";
const ARTIFACT = "/api/artifacts/task_2026-07-15_A1/download";

test("viewer accepts only supported same-origin original-file endpoints", () => {
  assert.equal(links.normalizeSource(ATTACHMENT), ATTACHMENT);
  assert.equal(links.normalizeSource(ARTIFACT), ARTIFACT);
  assert.equal(
    links.normalizeSource(`https://nomi.test${ATTACHMENT}`, "https://nomi.test"),
    ATTACHMENT
  );

  for (const unsafe of [
    "https://evil.test/file.pdf",
    "//evil.test/file.pdf",
    "/api/chat/attachments/11111111-1111-4111-8111-111111111111/preview",
    "/api/artifacts/a/download/../secret",
    "/api/login",
    "file:///sdcard/Download/a.pdf",
    "content://downloads/a.pdf",
  ]) {
    assert.equal(links.normalizeSource(unsafe, "https://nomi.test"), "", unsafe);
  }
});

test("viewer URL contains encoded display metadata but never a password", () => {
  const url = links.buildViewerUrl({
    source: `${ARTIFACT}?password=must-not-leak`,
    filename: "季度 汇报.pptx",
    mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  });

  assert.match(url, /^\/viewer\?/);
  const parsed = new URL(url, "https://nomi.test");
  assert.equal(parsed.searchParams.get("source"), ARTIFACT);
  assert.equal(parsed.searchParams.get("filename"), "季度 汇报.pptx");
  assert.equal(
    parsed.searchParams.get("mime_type"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  );
  assert.equal(parsed.searchParams.has("password"), false);
  assert.equal(url.includes("must-not-leak"), false);
});

test("unsupported source cannot produce a viewer URL", () => {
  assert.equal(
    links.buildViewerUrl({ source: "https://evil.test/private.pdf", filename: "private.pdf" }),
    ""
  );
});

test("content disposition parser handles quoted and UTF-8 filenames", () => {
  assert.equal(
    links.parseContentDispositionFilename('attachment; filename="quarterly report.pptx"'),
    "quarterly report.pptx"
  );
  assert.equal(
    links.parseContentDispositionFilename(
      "attachment; filename=legacy.pptx; filename*=UTF-8''%E5%AD%A3%E5%BA%A6%20%E6%B1%87%E6%8A%A5.pptx"
    ),
    "季度 汇报.pptx"
  );
});

test("content disposition parser removes path components and control characters", () => {
  assert.equal(
    links.parseContentDispositionFilename('attachment; filename="../../private\\\\report\u0000.pptx"'),
    "report.pptx"
  );
  assert.equal(links.sanitizeFilename("folder/subfolder/report.docx"), "report.docx");
  assert.equal(links.sanitizeFilename("..\\\\..\\\\sheet.xlsx"), "sheet.xlsx");
});

test("mime normalization removes parameters and rejects unusable values", () => {
  assert.equal(links.normalizeMimeType(" Application/PDF ; charset=binary "), "application/pdf");
  assert.equal(links.normalizeMimeType("text/plain; charset=utf-8"), "text/plain");
  assert.equal(links.normalizeMimeType("application"), "");
  assert.equal(links.normalizeMimeType(""), "");
});

test("explicit useful metadata takes precedence over response headers", () => {
  assert.deepEqual(
    links.resolveFileMetadata({
      filename: "approved deck.pptx",
      mimeType: "application/vnd.custom-presentation",
      contentDisposition: 'attachment; filename="response-name.pptx"',
      contentType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      blobType: "application/octet-stream",
    }),
    {
      filename: "approved deck.pptx",
      mimeType: "application/vnd.custom-presentation",
    }
  );
});

test("response headers replace generic caller metadata and strip MIME parameters", () => {
  assert.deepEqual(
    links.resolveFileMetadata({
      filename: "Nomi 文件",
      mimeType: "application/octet-stream",
      contentDisposition: "attachment; filename*=UTF-8''Nomi_auto_delivery_visual_20260720.pptx",
      contentType:
        "application/vnd.openxmlformats-officedocument.presentationml.presentation; charset=binary",
      blobType: "application/octet-stream",
    }),
    {
      filename: "Nomi_auto_delivery_visual_20260720.pptx",
      mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
  );
});

test("blob type and safe defaults are used when headers are absent", () => {
  assert.deepEqual(
    links.resolveFileMetadata({ filename: "notes.txt", blobType: "text/plain; charset=utf-8" }),
    { filename: "notes.txt", mimeType: "text/plain" }
  );
  assert.deepEqual(links.resolveFileMetadata({}), {
    filename: "Nomi 文件",
    mimeType: "application/octet-stream",
  });
});
