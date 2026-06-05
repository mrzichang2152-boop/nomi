package com.par.assistant.android;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public final class MicrophonePermissionActivityTest {
    @Test
    public void buildsDedicatedLaunchSpecForFloatingServicePermissionRequest() {
        MicrophonePermissionActivity.LaunchSpec spec = MicrophonePermissionActivity.launchSpec("voice_long_press");

        assertEquals(MicrophonePermissionActivity.class.getName(), spec.activityClassName);
        assertEquals("voice_long_press", spec.reason);
        assertEquals(true, spec.newTask);
    }
}
