from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "runtime_api" / "app" / "static"
RUNTIME_API = ROOT / "runtime_api"
if str(RUNTIME_API) not in sys.path:
    sys.path.insert(0, str(RUNTIME_API))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runtime_exposes_a_self_hosted_direct_file_viewer():
    main = read(ROOT / "runtime_api" / "app" / "main.py")
    html = read(STATIC / "viewer.html")

    assert '@app.get("/viewer")' in main
    assert "viewer.html" in main
    assert 'Content-Security-Policy' in html
    assert 'href="/static/viewer.css?v=20260722-file-viewer-v2"' in html
    assert 'src="/static/vendor/file-viewer/flyfish-file-viewer-web-full.iife.js"' in html
    assert 'src="/static/file-viewer-links.js?v=20260722-file-viewer-v2"' in html
    assert 'src="/static/viewer.js?v=20260722-file-viewer-v2"' in html
    assert "http://" not in html
    assert "https://" not in html


def test_viewer_fetches_authenticated_original_bytes_and_mounts_a_file():
    script = read(STATIC / "viewer.js")

    assert '"x-par-password"' in script.lower()
    assert "new File([blob]" in script
    assert "FlyfishFileViewerWebFull.mountViewer" in script
    assert 'new URL("/static/vendor/file-viewer/", location.origin).href' in script
    assert 'styleIsolation: "scoped"' in script
    assert 'styleIsolation: "shadow"' not in script
    assert 'fit: { mode: "contain", resize: "always", padding: 12 }' in script
    assert "search: false" in script
    assert "destroy" in script
    assert "加载文件" in script
    assert "重新尝试" in script
    assert "NomiViewer" in script
    assert "convert" not in script.lower()
    assert "pdf" not in script.lower() or "convert" not in script.lower()
    assert "cdn" not in script.lower()


def test_viewer_resolves_response_metadata_before_mounting_the_original_file():
    script = read(STATIC / "viewer.js")

    assert "NomiFileViewerLinks.resolveFileMetadata" in script
    assert 'response.headers.get("Content-Disposition")' in script
    assert 'response.headers.get("Content-Type")' in script
    assert "blob.type" in script
    assert "new File([blob], metadata.filename, { type: metadata.mimeType })" in script
    assert "filenameNode.textContent = metadata.filename" in script
    assert "document.title = `${metadata.filename} · Nomi`" in script


def test_viewer_has_an_accessible_original_file_download_command():
    html = read(STATIC / "viewer.html")
    css = read(STATIC / "viewer.css")

    assert 'id="downloadViewer"' in html
    assert 'aria-label="下载原文件"' in html
    assert 'title="下载"' in html
    assert 'class="topbar-actions"' in html
    assert ".topbar-actions" in css
    assert ".icon-button:disabled" in css


def test_viewer_retains_the_authenticated_blob_for_web_and_android_downloads():
    script = read(STATIC / "viewer.js")

    assert "loadedFile = {" in script
    assert "blob," in script
    assert "source," in script
    assert "metadata," in script
    assert "window.NomiViewer.downloadFile" in script
    assert "URL.createObjectURL" in script
    assert "anchor.download = loadedFile.metadata.filename" in script
    assert "URL.revokeObjectURL" in script
    assert 'downloadButton.addEventListener("click", downloadOriginalFile)' in script
    assert "downloadButton.disabled = false" in script


def test_viewer_reenables_download_after_the_renderer_reports_ready():
    script = read(STATIC / "viewer.js")

    ready_branch = script.split("else if (state.ready)", 1)[1].split(
        "else if (state.loading)", 1
    )[0]
    assert "downloadButton.disabled = false" in ready_branch
    assert "enableDownloadAfterRendererSettles()" in ready_branch
    assert "requestAnimationFrame" in script
    assert 'window.NomiViewerBuild = "20260722-file-viewer-v2"' in script


def test_android_download_stays_pending_until_the_native_completion_callback():
    script = read(STATIC / "viewer.js")

    assert "window.NomiViewerDownloadFinished" in script
    assert "nativeDownloadPending" in script
    assert "const accepted = window.NomiViewer.downloadFile(" in script
    assert "if (accepted === false)" in script
    assert "if (!nativeDownloadPending)" in script
    assert 'statusNode.textContent = "正在保存到 Download/Nomi"' in script


def test_web_chat_opens_attachments_and_artifacts_in_the_internal_viewer():
    html = read(STATIC / "index.html")
    app = read(STATIC / "app.js")

    assert 'src="/static/file-viewer-links.js"' in html
    assert "NomiFileViewerLinks" in app
    assert "openInternalFileViewer" in app
    assert "点击查看" in app
    assert "downloadAttachment(attachment)" not in app
    assert "window.NomiAndroid.openFileViewer" in app
    assert "window.NomiAndroid.downloadArtifact" not in app
    assert "function formatAttachmentSize" in app
    assert "+function formatAttachmentSize" not in app


def test_docker_builds_a_pinned_minimal_flyfish_asset_set():
    package = read(ROOT / "runtime_api" / "file_viewer" / "package.json")
    build = read(ROOT / "runtime_api" / "file_viewer" / "build-assets.mjs")
    dockerfile = read(ROOT / "runtime_api" / "Dockerfile")

    assert '"@file-viewer/web-full": "2.1.29"' in package
    for renderer in ("image", "pdf", "word", "presentation", "spreadsheet", "text"):
        assert renderer in build
    for vendor in ("docx", "pdf", "pptx", "xlsx"):
        assert f'"vendor/{vendor}"' in build
    assert "npm ci" in dockerfile
    assert "build-assets.mjs" in dockerfile
    assert "static/vendor/file-viewer" in dockerfile


def test_viewer_source_validation_is_owned_by_a_testable_helper():
    helper = read(STATIC / "file-viewer-links.js")

    assert "/api/chat/attachments/" in helper
    assert "/api/artifacts/" in helper
    assert "normalizeSource" in helper
    assert "buildViewerUrl" in helper
    assert "password" not in helper.lower()


def test_scoped_viewer_keeps_mobile_zoom_controls_inside_the_viewport():
    css = read(STATIC / "viewer.css")

    assert '#viewerRoot [part~="toolbar"]' in css
    assert '#viewerRoot [part~="toolbar-group"]' in css
    assert '#viewerRoot [part~="button"]' in css
    assert "max-width: calc(100% - 24px)" in css


def test_versioned_viewer_assets_are_cached_immutably(tmp_path):
    from app.static_assets import ImmutableViewerStaticFiles

    vendor = tmp_path / "vendor" / "file-viewer"
    vendor.mkdir(parents=True)
    (vendor / "renderer.js").write_text("renderer", encoding="utf-8")
    (tmp_path / "app.js").write_text("app", encoding="utf-8")

    app = FastAPI()
    app.mount("/static", ImmutableViewerStaticFiles(directory=tmp_path), name="static")
    client = TestClient(app)

    viewer_response = client.get("/static/vendor/file-viewer/renderer.js")
    normal_response = client.get("/static/app.js")

    assert viewer_response.status_code == 200
    assert viewer_response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert normal_response.headers["cache-control"] == "no-cache"
