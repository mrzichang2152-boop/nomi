package com.par.assistant.android;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;

final class OriginalFileDownload {
    static final class Result {
        final boolean success;
        final String message;

        Result(boolean success, String message) {
            this.success = success;
            this.message = message == null ? "" : message;
        }
    }

    private OriginalFileDownload() {
    }

    static String resolveDownloadUrl(String baseUrl, String source) {
        String cleanSource = source == null ? "" : source.trim();
        if (!FileViewerUrls.isAllowedSource(cleanSource)) return "";
        try {
            URI base = new URI(baseUrl == null ? "" : baseUrl.trim());
            if (base.getScheme() == null || base.getHost() == null) return "";
            URI resolved = base.resolve(cleanSource);
            if (!origin(base).equals(origin(resolved))) return "";
            return origin(base) + resolved.getPath().replaceAll("/$", "");
        } catch (Exception ignored) {
            return "";
        }
    }

    static String safeFilename(String value) {
        String clean = value == null ? "" : value.trim();
        int slash = Math.max(clean.lastIndexOf('/'), clean.lastIndexOf('\\'));
        if (slash >= 0) clean = clean.substring(slash + 1);
        clean = clean.replaceAll("[\\p{Cntrl}:*?\"<>|]", "").trim();
        if (clean.isEmpty() || ".".equals(clean) || "..".equals(clean)) return "Nomi-file";
        return clean.length() > 180 ? clean.substring(clean.length() - 180) : clean;
    }

    static String safeMimeType(String value) {
        String raw = value == null ? "" : value;
        if (raw.indexOf('\r') >= 0 || raw.indexOf('\n') >= 0) {
            return "application/octet-stream";
        }
        String clean = raw.split(";", 2)[0].trim().toLowerCase(Locale.ROOT);
        if (!clean.matches("^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")) {
            return "application/octet-stream";
        }
        return clean;
    }

    static Result download(
            Context context,
            String baseUrl,
            String password,
            String source,
            String filename,
            String mimeType
    ) {
        String url = resolveDownloadUrl(baseUrl, source);
        if (context == null || url.isEmpty()) return new Result(false, "文件地址不受 Nomi 支持。");
        String cleanFilename = safeFilename(filename);
        String cleanMimeType = safeMimeType(mimeType);
        OkHttpClient client = NomiHttpClients.privateCloudBuilder()
                .readTimeout(2, TimeUnit.MINUTES)
                .build();
        Request request = new Request.Builder()
                .url(url)
                .header("x-par-password", password == null ? "" : password)
                .get()
                .build();
        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                return new Result(false, httpFailureMessage(response.code()));
            }
            ResponseBody body = response.body();
            if (body == null) return new Result(false, "服务器没有返回文件内容。");
            String responseMime = safeMimeType(response.header("Content-Type", cleanMimeType));
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                return writeMediaStore(context, body, cleanFilename, responseMime);
            }
            return writeLegacyAppDownload(context, body, cleanFilename);
        } catch (IOException error) {
            return new Result(false, "下载失败，请检查网络后重试。");
        }
    }

    private static Result writeMediaStore(
            Context context,
            ResponseBody body,
            String filename,
            String mimeType
    ) throws IOException {
        ContentResolver resolver = context.getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, filename);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mimeType);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Nomi");
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri itemUri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (itemUri == null) return new Result(false, "无法创建系统下载记录。");
        try (InputStream input = body.byteStream(); OutputStream output = resolver.openOutputStream(itemUri, "w")) {
            if (output == null) throw new IOException("download output unavailable");
            copy(input, output);
            ContentValues complete = new ContentValues();
            complete.put(MediaStore.MediaColumns.IS_PENDING, 0);
            resolver.update(itemUri, complete, null, null);
            return new Result(true, "已下载到 Download/Nomi/" + filename);
        } catch (IOException error) {
            resolver.delete(itemUri, null, null);
            throw error;
        }
    }

    private static Result writeLegacyAppDownload(Context context, ResponseBody body, String filename)
            throws IOException {
        File downloads = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
        if (downloads == null) return new Result(false, "设备下载目录不可用。");
        File nomiDirectory = new File(downloads, "Nomi");
        if (!nomiDirectory.exists() && !nomiDirectory.mkdirs()) {
            return new Result(false, "无法创建 Nomi 下载目录。");
        }
        File target = nextAvailableFile(nomiDirectory, filename);
        try (InputStream input = body.byteStream(); OutputStream output = new FileOutputStream(target)) {
            copy(input, output);
        }
        return new Result(true, "文件已保存到 Nomi 下载目录：" + target.getName());
    }

    private static File nextAvailableFile(File directory, String filename) {
        File candidate = new File(directory, filename);
        if (!candidate.exists()) return candidate;
        int dot = filename.lastIndexOf('.');
        String stem = dot > 0 ? filename.substring(0, dot) : filename;
        String extension = dot > 0 ? filename.substring(dot) : "";
        for (int index = 2; index < 10_000; index++) {
            candidate = new File(directory, stem + " (" + index + ")" + extension);
            if (!candidate.exists()) return candidate;
        }
        return new File(directory, System.currentTimeMillis() + "-" + filename);
    }

    private static void copy(InputStream input, OutputStream output) throws IOException {
        byte[] buffer = new byte[32 * 1024];
        int read;
        while ((read = input.read(buffer)) >= 0) {
            if (read > 0) output.write(buffer, 0, read);
        }
        output.flush();
    }

    private static String httpFailureMessage(int status) {
        if (status == 401) return "访问凭证已失效，请返回 Nomi 重新登录。";
        if (status == 404) return "文件不存在或已经被清理。";
        return "文件下载失败（HTTP " + status + "）。";
    }

    private static String origin(URI uri) {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
        int port = uri.getPort();
        return scheme + "://" + host + (port >= 0 ? ":" + port : "");
    }
}
