(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.NomiFileViewerLinks = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const ATTACHMENT_PATTERN = /^\/api\/chat\/attachments\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/content\/?$/i;
  const ARTIFACT_PATTERN = /^\/api\/artifacts\/[A-Za-z0-9_-]+\/download\/?$/;
  const ATTACHMENT_PREFIX = "/api/chat/attachments/";
  const ARTIFACT_PREFIX = "/api/artifacts/";

  function normalizeOrigin(value) {
    const raw = String(value || "").trim();
    if (!raw) return "http://nomi.invalid";
    try {
      return new URL(raw).origin;
    } catch {
      return "";
    }
  }

  function normalizeSource(value, origin) {
    const raw = String(value || "").trim();
    if (!raw || raw.startsWith("//") || raw.includes("..") || raw.includes("\\")) return "";
    const baseOrigin = normalizeOrigin(origin || (typeof location !== "undefined" ? location.origin : ""));
    if (!baseOrigin) return "";
    try {
      const parsed = new URL(raw, `${baseOrigin}/`);
      if (parsed.origin !== baseOrigin) return "";
      const path = parsed.pathname.replace(/\/$/, "");
      const attachment = path.startsWith(ATTACHMENT_PREFIX) && ATTACHMENT_PATTERN.test(path);
      const artifact = path.startsWith(ARTIFACT_PREFIX) && ARTIFACT_PATTERN.test(path);
      if (!attachment && !artifact) return "";
      return path;
    } catch {
      return "";
    }
  }

  function buildViewerUrl(options, origin) {
    const input = options || {};
    const source = normalizeSource(input.source, origin);
    if (!source) return "";
    const params = new URLSearchParams({ source });
    const filename = String(input.filename || "").trim();
    const mimeType = String(input.mimeType || "").trim();
    if (filename) params.set("filename", filename);
    if (mimeType) params.set("mime_type", mimeType);
    return `/viewer?${params.toString()}`;
  }

  function sanitizeFilename(value) {
    const raw = String(value || "")
      .replace(/[\u0000-\u001f\u007f]/g, "")
      .replace(/\\/g, "/")
      .trim();
    if (!raw) return "";
    const segments = raw
      .split("/")
      .map((segment) => segment.trim())
      .filter((segment) => segment && segment !== "." && segment !== "..");
    const filename = String(segments[segments.length - 1] || "").trim();
    return filename === "." || filename === ".." ? "" : filename;
  }

  function decodeExtendedFilename(value) {
    const raw = String(value || "").trim().replace(/^"|"$/g, "");
    const match = raw.match(/^([^']*)'[^']*'(.*)$/);
    const encoded = match ? match[2] : raw;
    try {
      return decodeURIComponent(encoded);
    } catch {
      return encoded;
    }
  }

  function contentDispositionParameter(header, name) {
    const escapedName = name.replace("*", "\\*");
    const pattern = new RegExp(
      `(?:^|;)\\s*${escapedName}\\s*=\\s*(?:"((?:\\\\.|[^"])*)"|([^;]*))`,
      "i"
    );
    const match = String(header || "").match(pattern);
    if (!match) return "";
    return String(match[1] !== undefined ? match[1].replace(/\\(["\\])/g, "$1") : match[2]).trim();
  }

  function parseContentDispositionFilename(header) {
    const extended = contentDispositionParameter(header, "filename*");
    if (extended) return sanitizeFilename(decodeExtendedFilename(extended));
    return sanitizeFilename(contentDispositionParameter(header, "filename"));
  }

  function normalizeMimeType(value) {
    const mimeType = String(value || "").split(";", 1)[0].trim().toLowerCase();
    if (!/^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/.test(mimeType)) return "";
    return mimeType;
  }

  function hasUsefulExtension(filename) {
    return /\.[a-z0-9]{1,16}$/i.test(String(filename || ""));
  }

  function usefulMimeType(value) {
    const mimeType = normalizeMimeType(value);
    return mimeType && mimeType !== "application/octet-stream" ? mimeType : "";
  }

  function resolveFileMetadata(options) {
    const input = options || {};
    const requestedFilename = sanitizeFilename(input.filename);
    const responseFilename = parseContentDispositionFilename(input.contentDisposition);
    const filename =
      (hasUsefulExtension(requestedFilename) && requestedFilename) ||
      responseFilename ||
      requestedFilename ||
      "Nomi 文件";

    const requestedMimeType = normalizeMimeType(input.mimeType);
    const responseMimeType = normalizeMimeType(input.contentType);
    const blobMimeType = normalizeMimeType(input.blobType);
    const mimeType =
      usefulMimeType(requestedMimeType) ||
      usefulMimeType(responseMimeType) ||
      usefulMimeType(blobMimeType) ||
      requestedMimeType ||
      responseMimeType ||
      blobMimeType ||
      "application/octet-stream";

    return { filename, mimeType };
  }

  return {
    normalizeSource,
    buildViewerUrl,
    sanitizeFilename,
    parseContentDispositionFilename,
    normalizeMimeType,
    resolveFileMetadata,
  };
});
