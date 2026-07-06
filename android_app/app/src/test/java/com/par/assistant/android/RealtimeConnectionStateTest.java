package com.par.assistant.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import okhttp3.Request;
import okhttp3.WebSocket;
import okio.ByteString;

import org.junit.Test;

public final class RealtimeConnectionStateTest {
    @Test
    public void newOrConnectingSocketIsNotReadyForChatUntilOpen() {
        RealtimeConnectionState state = new RealtimeConnectionState();
        WebSocket socket = fakeSocket();

        assertFalse(state.isOpen(socket));

        state.markConnecting(socket);

        assertFalse(state.isOpen(socket));

        state.markOpen(socket);

        assertTrue(state.isOpen(socket));
    }

    @Test
    public void staleSocketCallbacksCannotCloseNewOpenConnection() {
        RealtimeConnectionState state = new RealtimeConnectionState();
        WebSocket oldSocket = fakeSocket();
        WebSocket newSocket = fakeSocket();

        state.markConnecting(oldSocket);
        state.markOpen(oldSocket);
        assertTrue(state.isOpen(oldSocket));

        state.markConnecting(newSocket);
        assertFalse(state.isOpen(oldSocket));
        assertFalse(state.isOpen(newSocket));

        state.markOpen(newSocket);
        assertTrue(state.isOpen(newSocket));

        state.markClosed(oldSocket);
        assertTrue(state.isOpen(newSocket));
        assertFalse(state.isOpen(oldSocket));
    }

    private static WebSocket fakeSocket() {
        return new WebSocket() {
            @Override
            public Request request() {
                return new Request.Builder().url("ws://example.test/ws").build();
            }

            @Override
            public long queueSize() {
                return 0;
            }

            @Override
            public boolean send(String text) {
                return true;
            }

            @Override
            public boolean send(ByteString bytes) {
                return true;
            }

            @Override
            public boolean close(int code, String reason) {
                return true;
            }

            @Override
            public void cancel() {
            }
        };
    }
}
