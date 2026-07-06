package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ConfigPrefsTest {
    @Test
    public void remoteBrowserUrlUsesReadableNoVncModeForPhoneScreensAndAutoconnects() {
        String url = ConfigPrefs.remoteBrowserUrlFor("http://206.119.171.141", "par-dev");

        assertEquals(
                "http://206.119.171.141:6080/vnc_lite.html?path=websockify&autoconnect=1&resize=remote&quality=6&compression=2&show_dot=1&password=par-dev-vnc",
                url
        );
    }

    @Test
    public void remoteBrowserUrlEncodesDerivedVncPassword() {
        String url = ConfigPrefs.remoteBrowserUrlFor("http://example.test", "p a/r");

        assertEquals(
                "http://example.test:6080/vnc_lite.html?path=websockify&autoconnect=1&resize=remote&quality=6&compression=2&show_dot=1&password=p+a%2Fr-vnc",
                url
        );
    }
}
