package com.par.assistant.android;

import okhttp3.WebSocket;

final class RealtimeConnectionState {
    private WebSocket currentSocket;
    private boolean open;

    synchronized void markConnecting(WebSocket socket) {
        currentSocket = socket;
        open = false;
    }

    synchronized void markOpen(WebSocket socket) {
        if (socket == currentSocket) {
            open = true;
        }
    }

    synchronized void markClosed(WebSocket socket) {
        if (socket == currentSocket) {
            open = false;
        }
    }

    synchronized void clear(WebSocket socket) {
        if (socket == null || socket == currentSocket) {
            currentSocket = null;
            open = false;
        }
    }

    synchronized boolean isOpen(WebSocket socket) {
        return socket != null && socket == currentSocket && open;
    }
}
