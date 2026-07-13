package com.par.assistant.android;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.junit.Test;

public final class WebWorkspaceAttachmentChooserTest {
    @Test
    public void chooserSessionCancelsStaleCallbackAndDeliversOrderedSelectionOnce() {
        WebWorkspaceActivity.ChooserSession<String> session = new WebWorkspaceActivity.ChooserSession<>();
        RecordingResult<String> stale = new RecordingResult<>();
        RecordingResult<String> active = new RecordingResult<>();

        session.begin(stale);
        session.begin(active);

        assertEquals(1, stale.results.size());
        assertNull(stale.results.get(0));
        assertTrue(session.hasActiveCallback());

        session.deliver(Arrays.asList("content://one", "content://two"));
        session.deliver(List.of("content://ignored"));

        assertEquals(1, active.results.size());
        assertEquals(Arrays.asList("content://one", "content://two"), active.results.get(0));
        assertFalse(session.hasActiveCallback());
    }

    @Test
    public void chooserSessionCancellationAndActivityRecreationCleanupReturnNull() {
        WebWorkspaceActivity.ChooserSession<String> session = new WebWorkspaceActivity.ChooserSession<>();
        RecordingResult<String> cancelled = new RecordingResult<>();

        session.begin(cancelled);
        session.cancel();
        session.cancel();

        assertEquals(1, cancelled.results.size());
        assertNull(cancelled.results.get(0));
        assertFalse(session.hasActiveCallback());
    }

    @Test
    public void approvedAcceptTypesMapExtensionsAndMimesWithoutCameraCapture() {
        String[] types = WebWorkspaceActivity.approvedMimeTypes(new String[]{
                ".png,.pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "image/*",
                "video/mp4"
        });

        assertArrayEquals(new String[]{
                "image/png",
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "image/jpeg",
                "image/webp",
                "image/gif"
        }, types);
    }

    @Test
    public void activityUsesSafMultipleSelectionPersistableReadGrantsAndBothResultShapes() throws Exception {
        String activity = read("java/com/par/assistant/android/WebWorkspaceActivity.java");
        String manifest = read("AndroidManifest.xml");

        assertTrue(activity.contains("onShowFileChooser"));
        assertTrue(activity.contains("Intent.ACTION_OPEN_DOCUMENT"));
        assertTrue(activity.contains("Intent.CATEGORY_OPENABLE"));
        assertTrue(activity.contains("Intent.EXTRA_ALLOW_MULTIPLE"));
        assertTrue(activity.contains("Intent.EXTRA_MIME_TYPES"));
        assertTrue(activity.contains("Intent.FLAG_GRANT_READ_URI_PERMISSION"));
        assertTrue(activity.contains("Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION"));
        assertTrue(activity.contains("takePersistableUriPermission"));
        assertTrue(activity.contains("getClipData()"));
        assertTrue(activity.contains("getData()"));
        assertTrue(activity.contains("ValueCallback<Uri[]>"));
        assertTrue(activity.contains("fileChooserSession.cancel()"));
        assertFalse(activity.contains("ACTION_IMAGE_CAPTURE"));
        assertFalse(activity.contains("EXTRA_INITIAL_INTENTS"));
        assertTrue(manifest.contains("orientation|screenSize|keyboardHidden|screenLayout|smallestScreenSize|uiMode"));
    }

    private static String read(String relativePath) throws Exception {
        return new String(Files.readAllBytes(sourcePath(relativePath)), StandardCharsets.UTF_8);
    }

    private static Path sourcePath(String relativePath) {
        Path appModulePath = Paths.get("src/main", relativePath);
        if (Files.exists(appModulePath)) return appModulePath;
        return Paths.get("app/src/main", relativePath);
    }

    private static final class RecordingResult<T> implements WebWorkspaceActivity.ChooserResult<T> {
        private final List<List<T>> results = new ArrayList<>();

        @Override
        public void onResult(List<T> value) {
            results.add(value == null ? null : new ArrayList<>(value));
        }
    }
}
