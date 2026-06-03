package com.poxelgraphic.stafforyx;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    protected void load() {
        super.load();
        getBridge().getWebView().setWebChromeClient(new StafforyxWebChromeClient(getBridge()));
    }
}
