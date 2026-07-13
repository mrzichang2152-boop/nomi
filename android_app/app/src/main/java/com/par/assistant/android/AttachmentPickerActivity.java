package com.par.assistant.android;

import android.app.Activity;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;

public final class AttachmentPickerActivity extends Activity {
    private static final int REQUEST_PICK = 7001;
    private static final String KEY_LAUNCHED = "attachment_picker_launched";
    static final String[] APPROVED_MIME_TYPES = new String[] {
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
            "text/markdown"
    };

    static Intent intent(Context context) {
        return new Intent(context, AttachmentPickerActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (savedInstanceState == null || !savedInstanceState.getBoolean(KEY_LAUNCHED, false)) {
            launchPicker();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        outState.putBoolean(KEY_LAUNCHED, true);
        super.onSaveInstanceState(outState);
    }

    private void launchPicker() {
        Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .setType("*/*")
                .putExtra(Intent.EXTRA_MIME_TYPES, APPROVED_MIME_TYPES)
                .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(picker, REQUEST_PICK);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_PICK) return;
        if (resultCode != RESULT_OK || data == null) {
            notifyService(FloatingBallService.ACTION_ATTACHMENTS_CANCELLED, List.of());
            finish();
            return;
        }
        LinkedHashSet<Uri> ordered = new LinkedHashSet<>();
        ClipData clipData = data.getClipData();
        if (clipData != null) {
            for (int index = 0; index < clipData.getItemCount() && ordered.size() < FloatingAttachmentController.MAX_ATTACHMENTS; index++) {
                Uri uri = clipData.getItemAt(index).getUri();
                if (uri != null) ordered.add(uri);
            }
        } else if (data.getData() != null) {
            ordered.add(data.getData());
        }
        notifyService(FloatingBallService.ACTION_ATTACHMENTS_SELECTED, new ArrayList<>(ordered));
        finish();
    }

    private void notifyService(String action, List<Uri> uris) {
        ArrayList<String> uriValues = new ArrayList<>();
        ArrayList<String> filenames = new ArrayList<>();
        ArrayList<String> mimeTypes = new ArrayList<>();
        ArrayList<Long> byteSizes = new ArrayList<>();
        for (Uri uri : uris) {
            try {
                getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } catch (SecurityException ignored) {
                // Some document providers grant only a temporary read permission.
            }
            Metadata metadata = metadata(uri);
            if (metadata.mimeType.isEmpty()) continue;
            uriValues.add(uri.toString());
            filenames.add(metadata.filename);
            mimeTypes.add(metadata.mimeType);
            byteSizes.add(metadata.byteSize);
        }
        Intent service = new Intent(this, FloatingBallService.class)
                .setAction(action)
                .putStringArrayListExtra(FloatingBallService.EXTRA_ATTACHMENT_URIS, uriValues)
                .putStringArrayListExtra(FloatingBallService.EXTRA_ATTACHMENT_FILENAMES, filenames)
                .putStringArrayListExtra(FloatingBallService.EXTRA_ATTACHMENT_MIME_TYPES, mimeTypes)
                .putExtra(FloatingBallService.EXTRA_ATTACHMENT_BYTE_SIZES, byteSizes);
        startService(service);
    }

    private Metadata metadata(Uri uri) {
        String filename = "attachment";
        long byteSize = -1L;
        try (Cursor cursor = getContentResolver().query(
                uri,
                new String[] { OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE },
                null,
                null,
                null
        )) {
            if (cursor != null && cursor.moveToFirst()) {
                int nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                int sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE);
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) filename = cursor.getString(nameIndex);
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) byteSize = cursor.getLong(sizeIndex);
            }
        }
        String mimeType = approvedMimeType(filename, getContentResolver().getType(uri));
        return new Metadata(filename, mimeType, byteSize);
    }

    static String approvedMimeType(String filename, String detectedMimeType) {
        String detected = detectedMimeType == null ? "" : detectedMimeType.trim().toLowerCase();
        if (Arrays.asList(APPROVED_MIME_TYPES).contains(detected)) return detected;
        String name = filename == null ? "" : filename.trim().toLowerCase();
        if (name.endsWith(".png")) return "image/png";
        if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
        if (name.endsWith(".webp")) return "image/webp";
        if (name.endsWith(".gif")) return "image/gif";
        if (name.endsWith(".pdf")) return "application/pdf";
        if (name.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (name.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        if (name.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        if (name.endsWith(".csv")) return "text/csv";
        if (name.endsWith(".txt")) return "text/plain";
        if (name.endsWith(".md")) return "text/markdown";
        return "";
    }

    private static final class Metadata {
        final String filename;
        final String mimeType;
        final long byteSize;

        Metadata(String filename, String mimeType, long byteSize) {
            this.filename = filename;
            this.mimeType = mimeType;
            this.byteSize = byteSize;
        }
    }
}
