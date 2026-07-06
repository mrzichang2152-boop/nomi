package com.par.assistant.android;

import java.net.Proxy;

import okhttp3.OkHttpClient;

final class NomiHttpClients {
    private NomiHttpClients() {
    }

    static OkHttpClient.Builder privateCloudBuilder() {
        return new OkHttpClient.Builder()
                .proxy(Proxy.NO_PROXY);
    }
}
