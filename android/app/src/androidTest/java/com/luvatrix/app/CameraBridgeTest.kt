package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CameraBridgeTest {
    @Test
    fun viewDoesNotCreateCameraBridgeUntilCameraApiIsUsed() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val view = LuvatrixVulkanView(context)

        assertFalse(view.isCameraBridgeInitializedForTest())
        view.stopCameraPreview()
        assertFalse(view.isCameraBridgeInitializedForTest())

        view.cameraTelemetryJson()
        assertTrue(view.isCameraBridgeInitializedForTest())
    }

    @Test
    fun bridgeTelemetryIsCallableWithoutPreview() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val bridge = CameraBridge(context)

        assertFalse(bridge.isCameraManagerInitializedForTest())
        assertFalse(bridge.isProcessingExecutorInitializedForTest())
        val telemetry = JSONObject(bridge.telemetryJson())

        assertTrue(telemetry.has("status"))
        assertTrue(telemetry.has("permission"))
        assertTrue(telemetry.has("camera.capabilities.raw"))
        assertTrue(bridge.isCameraManagerInitializedForTest())
        assertFalse(bridge.isProcessingExecutorInitializedForTest())
    }

    @Test
    fun nativeCameraTelemetryIsCallable() {
        NativeVulkan.setCameraPreviewEnabled(true)
        val telemetry = JSONObject(NativeVulkan.cameraTelemetryJson())
        NativeVulkan.setCameraPreviewEnabled(false)

        assertTrue(telemetry.getBoolean("preview_enabled"))
        assertTrue(telemetry.has("has_frame"))
        assertTrue(telemetry.has("cover_mode"))
        assertTrue(telemetry.getJSONObject("slots").has("primary"))
        assertTrue(telemetry.getJSONObject("slots").has("secondary"))
    }

    @Test
    fun cameraInventoryQueryReturnsJsonShape() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val bridge = CameraBridge(context)
        val inventory = JSONObject(bridge.inventoryJson())

        assertTrue(inventory.has("cameras"))
        assertTrue(inventory.has("concurrent_camera_id_sets"))
        assertTrue(inventory.has("dual_supported"))
    }
}
