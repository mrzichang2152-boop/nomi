package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ExternalAuthOverlayStateTest {
    @Test
    public void cancelMessageExplainsThatAuthorizationWasClosed() {
        assertEquals(
                "授权页面已关闭，正在刷新账号状态。",
                ExternalAuthOverlayState.cancelMessage()
        );
    }
}
