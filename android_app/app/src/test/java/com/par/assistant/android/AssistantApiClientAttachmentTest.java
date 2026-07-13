package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.par.assistant.core.ServerConfig;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.List;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import okhttp3.MediaType;
import okhttp3.RequestBody;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

public final class AssistantApiClientAttachmentTest {
    private MockWebServer server;
    private AssistantApiClient client;

    @Before
    public void start() throws Exception {
        server = new MockWebServer();
        server.start();
        client = new AssistantApiClient(ServerConfig.create(server.url("/").toString(), "secret"));
    }

    @After
    public void stop() throws Exception {
        server.shutdown();
    }

    @Test
    public void uploadUsesMultipartAuthStableClientIdAndChineseFilename() throws Exception {
        server.enqueue(json(202, "{\"attachment_id\":\"11111111-1111-1111-1111-111111111111\",\"filename\":\"项目简历.pdf\",\"mime_type\":\"application/pdf\",\"byte_size\":4,\"status\":\"processing\",\"kind\":\"document\"}"));
        AttachmentDraft draft = AttachmentDraft.create("content://resume/1", "项目简历.pdf", "application/pdf", 4, "upload-stable-1");

        ChatAttachment uploaded = client.uploadAttachment(
                draft,
                RequestBody.create("test".getBytes(StandardCharsets.UTF_8), MediaType.get("application/pdf"))
        );

        RecordedRequest request = server.takeRequest();
        assertEquals("/api/chat/attachments", request.getPath());
        assertEquals("secret", request.getHeader("x-par-password"));
        String multipart = request.getBody().readUtf8();
        assertTrue(multipart.contains("name=\"client_upload_id\""));
        assertTrue(multipart.contains("upload-stable-1"));
        assertTrue(multipart.contains("项目简历.pdf"));
        assertEquals("11111111-1111-1111-1111-111111111111", uploaded.attachmentId);
        assertEquals("processing", uploaded.status);
    }

    @Test
    public void streamedBodyArrivesAtMockServerByteForByteWithoutReadAllBuffering() throws Exception {
        byte[] content = new byte[160 * 1024 + 31];
        for (int index = 0; index < content.length; index++) content[index] = (byte) (index % 251);
        server.enqueue(json(202, "{\"attachment_id\":\"21111111-1111-1111-1111-111111111111\",\"filename\":\"large.pdf\",\"mime_type\":\"application/pdf\",\"byte_size\":" + content.length + ",\"status\":\"processing\",\"kind\":\"document\"}"));
        AttachmentDraft draft = AttachmentDraft.create("content://large", "large.pdf", "application/pdf", content.length, "upload-large-1");
        AttachmentUploadRequestBody body = new AttachmentUploadRequestBody(
                MediaType.get("application/pdf"),
                content.length,
                () -> new java.io.ByteArrayInputStream(content),
                8 * 1024,
                null,
                () -> false
        );

        client.uploadAttachment(draft, body);

        byte[] multipart = server.takeRequest().getBody().readByteArray();
        byte[] headerEnd = "\r\n\r\n".getBytes(StandardCharsets.UTF_8);
        int filename = indexOf(multipart, "filename=\"large.pdf\"".getBytes(StandardCharsets.UTF_8), 0);
        int contentStart = indexOf(multipart, headerEnd, filename) + headerEnd.length;
        int contentEnd = indexOf(multipart, "\r\n--".getBytes(StandardCharsets.UTF_8), contentStart);
        byte[] received = Arrays.copyOfRange(multipart, contentStart, contentEnd);
        assertTrue(filename >= 0 && contentStart >= headerEnd.length && contentEnd > contentStart);
        assertEquals(content.length, received.length);
        assertTrue(Arrays.equals(
                MessageDigest.getInstance("SHA-256").digest(content),
                MessageDigest.getInstance("SHA-256").digest(received)
        ));
    }

    @Test
    public void statusRetryAndDeleteUseProtectedLifecycleEndpoints() throws Exception {
        String ready = "{\"attachment_id\":\"11111111-1111-1111-1111-111111111111\",\"filename\":\"a.pdf\",\"mime_type\":\"application/pdf\",\"byte_size\":4,\"status\":\"ready\",\"lifecycle\":\"active\",\"kind\":\"document\",\"preview_url\":null,\"content_url\":\"/content\"}";
        server.enqueue(json(200, ready));
        server.enqueue(json(202, ready));
        server.enqueue(new MockResponse().setResponseCode(204));

        ChatAttachment status = client.attachmentStatus("11111111-1111-1111-1111-111111111111");
        ChatAttachment retried = client.retryAttachment(status.attachmentId);
        client.deleteAttachment(status.attachmentId);

        assertEquals("ready", status.status);
        assertEquals("ready", retried.status);
        assertEquals("GET", server.takeRequest().getMethod());
        assertEquals("POST", server.takeRequest().getMethod());
        assertEquals("DELETE", server.takeRequest().getMethod());
    }

    @Test
    public void attachmentOnlyChatKeepsOrderedIdsAndClientRequestId() throws Exception {
        server.enqueue(json(200, "{\"answer\":\"已理解附件\",\"conversation_id\":\"conv-a\"}"));

        ChatResult result = client.chat(
                "",
                "conv-a",
                List.of(),
                "android-request-a",
                List.of("attachment-1", "attachment-2")
        );

        JSONObject body = new JSONObject(server.takeRequest().getBody().readUtf8());
        assertEquals("", body.getString("message"));
        assertEquals("android-request-a", body.getString("client_request_id"));
        assertEquals("attachment-1", body.getJSONArray("attachment_ids").getString(0));
        assertEquals("attachment-2", body.getJSONArray("attachment_ids").getString(1));
        assertEquals("已理解附件", result.answer);
    }

    private static MockResponse json(int code, String body) {
        return new MockResponse().setResponseCode(code).setHeader("content-type", "application/json").setBody(body);
    }

    private static int indexOf(byte[] source, byte[] target, int fromIndex) {
        if (source == null || target == null || target.length == 0) return -1;
        for (int index = Math.max(0, fromIndex); index <= source.length - target.length; index++) {
            boolean match = true;
            for (int offset = 0; offset < target.length; offset++) {
                if (source[index + offset] != target[offset]) {
                    match = false;
                    break;
                }
            }
            if (match) return index;
        }
        return -1;
    }
}
