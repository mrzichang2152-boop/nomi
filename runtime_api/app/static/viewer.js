(function () {
  window.NomiViewerBuild = "20260722-file-viewer-v2";
  const root = document.querySelector("#viewerRoot");
  const filenameNode = document.querySelector("#viewerFilename");
  const statusNode = document.querySelector("#viewerStatus");
  const errorPanel = document.querySelector("#viewerError");
  const errorMessage = document.querySelector("#viewerErrorMessage");
  const retryButton = document.querySelector("#retryViewer");
  const closeButton = document.querySelector("#closeViewer");
  const downloadButton = document.querySelector("#downloadViewer");
  let controller = null;
  let loadedFile = null;
  let downloadInProgress = false;
  let nativeDownloadPending = false;
  let loadToken = 0;

  function viewerPassword() {
    try {
      if (window.NomiViewer && typeof window.NomiViewer.getPassword === "function") {
        return String(window.NomiViewer.getPassword() || "");
      }
    } catch {}
    try {
      return String(localStorage.getItem("par-password") || "");
    } catch {
      return "";
    }
  }

  function destroyViewer() {
    if (controller && typeof controller.destroy === "function") controller.destroy();
    controller = null;
    root.replaceChildren();
  }

  function showError(message) {
    destroyViewer();
    statusNode.textContent = "加载失败";
    errorMessage.textContent = message;
    errorPanel.hidden = false;
    downloadButton.disabled = !loadedFile;
  }

  function loadErrorMessage(response) {
    if (response.status === 401) return "访问凭证已失效，请返回 Nomi 重新进入。";
    if (response.status === 404) return "文件不存在或已经被清理。";
    return `文件读取失败（${response.status}）。`;
  }

  function enableDownloadAfterRendererSettles() {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (loadedFile && !downloadInProgress && !nativeDownloadPending) {
          downloadButton.disabled = false;
        }
      });
    });
  }

  async function loadViewer() {
    const token = ++loadToken;
    errorPanel.hidden = true;
    destroyViewer();
    statusNode.textContent = "正在加载文件";
    const params = new URLSearchParams(location.search);
    const source = window.NomiFileViewerLinks.normalizeSource(params.get("source"), location.origin);
    const requestedFilename = String(params.get("filename") || "").trim();
    const requestedMimeType = String(params.get("mime_type") || "").trim();
    loadedFile = null;
    downloadButton.disabled = true;
    filenameNode.textContent = requestedFilename || "Nomi 文件";
    document.title = `${requestedFilename || "Nomi 文件"} · Nomi`;
    if (!source) {
      showError("文件地址不受 Nomi 查看器支持。");
      return;
    }
    try {
      const response = await fetch(source, { headers: { "x-par-password": viewerPassword() } });
      if (!response.ok) throw new Error(loadErrorMessage(response));
      const blob = await response.blob();
      const metadata = window.NomiFileViewerLinks.resolveFileMetadata({
        filename: requestedFilename,
        mimeType: requestedMimeType,
        contentDisposition: response.headers.get("Content-Disposition"),
        contentType: response.headers.get("Content-Type"),
        blobType: blob.type,
      });
      filenameNode.textContent = metadata.filename;
      document.title = `${metadata.filename} · Nomi`;
      loadedFile = {
        blob,
        source,
        metadata,
      };
      downloadButton.disabled = false;
      const file = new File([blob], metadata.filename, { type: metadata.mimeType });
      const viewer = window.FlyfishFileViewerWebFull;
      if (!viewer || typeof viewer.mountViewer !== "function") throw new Error("文件查看组件没有正确加载。");
      viewer.setDefaultFullAssetBaseUrl(
        new URL("/static/vendor/file-viewer/", location.origin).href
      );
      controller = window.FlyfishFileViewerWebFull.mountViewer(root, {
        file,
        options: {
          // The PPTX renderer installs its fit styles in the document scope.
          // This page is dedicated to viewing, so scoped isolation preserves
          // those styles without exposing the rest of the Nomi workbench.
          styleIsolation: "scoped",
          theme: "light",
          fit: { mode: "contain", resize: "always", padding: 12 },
          toolbar: {
            position: "bottom-right",
            download: false,
            print: false,
            exportHtml: false,
            zoom: true,
            search: false,
            theme: false,
          },
        },
        onStateChange(state) {
          if (token !== loadToken) return;
          if (state.error) {
            showError(state.error instanceof Error ? state.error.message : "该文件无法按原格式显示。");
          } else if (state.ready) {
            // Some renderers temporarily disable document-level controls while
            // mounting. Restore the viewer-owned download command only after
            // the original file is ready for interaction.
            downloadButton.disabled = false;
            enableDownloadAfterRendererSettles();
            statusNode.textContent = `${Math.max(1, Math.ceil(blob.size / 1024))} KB · 原格式查看`;
          } else if (state.loading) {
            statusNode.textContent = "正在解析文件";
          }
        },
      });
    } catch (error) {
      showError(error instanceof Error ? error.message : "文件加载失败，请重新尝试。");
    }
  }

  function closeViewer() {
    try {
      if (window.NomiViewer && typeof window.NomiViewer.closeViewer === "function") {
        window.NomiViewer.closeViewer();
        return;
      }
    } catch {}
    if (history.length > 1) history.back();
    else window.close();
  }

  async function downloadOriginalFile() {
    if (!loadedFile || downloadInProgress) return;
    downloadInProgress = true;
    downloadButton.disabled = true;
    const previousStatus = statusNode.textContent;
    statusNode.textContent = "正在下载原文件";
    try {
      if (window.NomiViewer && typeof window.NomiViewer.downloadFile === "function") {
        const accepted = window.NomiViewer.downloadFile(
          loadedFile.source,
          loadedFile.metadata.filename,
          loadedFile.metadata.mimeType
        );
        if (accepted === false) throw new Error("download rejected");
        nativeDownloadPending = true;
        statusNode.textContent = "正在保存到 Download/Nomi";
        return;
      }

      const objectUrl = URL.createObjectURL(loadedFile.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = loadedFile.metadata.filename;
      anchor.hidden = true;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      statusNode.textContent = "原文件已下载";
    } catch {
      statusNode.textContent = "下载失败，请重新尝试";
    } finally {
      if (!nativeDownloadPending) {
        downloadInProgress = false;
        downloadButton.disabled = !loadedFile;
        if (statusNode.textContent === "正在下载原文件") statusNode.textContent = previousStatus;
      }
    }
  }

  window.NomiViewerDownloadFinished = function (success, message) {
    nativeDownloadPending = false;
    downloadInProgress = false;
    downloadButton.disabled = !loadedFile;
    statusNode.textContent = String(
      message || (success ? "原文件已下载" : "下载失败，请重新尝试")
    );
  };

  retryButton.addEventListener("click", loadViewer);
  closeButton.addEventListener("click", closeViewer);
  downloadButton.addEventListener("click", downloadOriginalFile);
  window.addEventListener("pagehide", destroyViewer);
  loadViewer();
})();
