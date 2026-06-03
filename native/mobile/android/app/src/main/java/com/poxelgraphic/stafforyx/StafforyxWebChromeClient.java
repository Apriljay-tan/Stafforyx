package com.poxelgraphic.stafforyx;

import android.Manifest;
import android.webkit.PermissionRequest;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebChromeClient;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

public class StafforyxWebChromeClient extends BridgeWebChromeClient {

    private final ActivityResultLauncher<String[]> permissionLauncher;
    private PermissionRequest pendingPermissionRequest;

    public StafforyxWebChromeClient(Bridge bridge) {
        super(bridge);

        permissionLauncher = bridge.registerForActivityResult(
            new ActivityResultContracts.RequestMultiplePermissions(),
            (Map<String, Boolean> permissionResults) -> {
                PermissionRequest request = pendingPermissionRequest;
                pendingPermissionRequest = null;

                if (request == null) {
                    return;
                }

                boolean granted = true;
                for (Boolean permissionGranted : permissionResults.values()) {
                    if (!permissionGranted) {
                        granted = false;
                        break;
                    }
                }

                answerPermissionRequest(request, granted);
            }
        );
    }

    @Override
    public void onPermissionRequest(PermissionRequest request) {
        List<String> requestedResources = Arrays.asList(request.getResources());
        List<String> runtimePermissions = new ArrayList<>();

        if (requestedResources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) {
            runtimePermissions.add(Manifest.permission.CAMERA);
        }

        if (requestedResources.contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) {
            runtimePermissions.add(Manifest.permission.RECORD_AUDIO);
        }

        if (runtimePermissions.isEmpty()) {
            answerPermissionRequest(request, true);
            return;
        }

        pendingPermissionRequest = request;
        permissionLauncher.launch(runtimePermissions.toArray(new String[0]));
    }

    private void answerPermissionRequest(PermissionRequest request, boolean granted) {
        try {
            if (granted) {
                request.grant(request.getResources());
            } else {
                request.deny();
            }
        } catch (IllegalStateException ignored) {
        }
    }
}
