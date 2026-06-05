package com.par.assistant.android;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ConfigPrefsTest {
    @Test
    public void remoteBrowserUrlScalesNoVncForPhoneScreensAndAutoconnects() {
        String url = ConfigPrefs.remoteBrowserUrlFor("http://206.119.171.141");

        assertEquals(
                "http://206.119.171.141:6080/vnc.html?autoconnect=1&resize=scale&quality=6&compression=2&show_dot=1",
                url
        );
    }
}
