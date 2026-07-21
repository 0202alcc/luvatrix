package com.luvatrix.app

import android.hardware.HardwareBuffer
import android.view.Surface

object NativeVulkan {
    init {
        System.loadLibrary("luvatrix_vulkan_renderer")
    }

    fun ensureLoaded() = Unit

    external fun probeVulkan(): Int

    external fun setSurface(surface: Surface?)

    external fun setBitmapGlyphTable(tableText: String): Boolean

    external fun presentRgba(rgba: ByteArray, revision: Int, width: Int, height: Int): Boolean

    external fun presentScene(sceneJson: String, revision: Int, width: Int, height: Int, presentationMode: String): Boolean

    external fun presentSceneBinary(scenePacket: ByteArray, revision: Int, width: Int, height: Int, presentationMode: String): Boolean

    external fun presentSceneTransform(revision: Int, contentOffsetX: Double, contentOffsetY: Double): Boolean

    external fun setCameraPreviewEnabled(enabled: Boolean)

    external fun setCameraCoverMode(mode: String)

    external fun setCameraDownsampleMode(mode: String): Boolean

    external fun setCameraConvolutionLayers(layers: Int): Boolean

    external fun setCameraColorMode(mode: String): Boolean

    external fun setCameraFrameYuv420(
        slot: String,
        yPlane: ByteArray,
        uPlane: ByteArray,
        vPlane: ByteArray,
        width: Int,
        height: Int,
        yRowStride: Int,
        uRowStride: Int,
        vRowStride: Int,
        yPixelStride: Int,
        uPixelStride: Int,
        vPixelStride: Int,
        timestampNs: Long,
        droppedFrames: Long,
        rotationDegrees: Int,
    )

    external fun clearCameraFrameSlot(slot: String)

    external fun setCameraFrameHardwareBuffer(
        slot: String,
        hardwareBuffer: HardwareBuffer,
        width: Int,
        height: Int,
        timestampNs: Long,
        rotationDegrees: Int,
    ): Boolean

    external fun clearCameraHardwareBufferSlot(slot: String)

    external fun cameraTelemetryJson(): String
}
