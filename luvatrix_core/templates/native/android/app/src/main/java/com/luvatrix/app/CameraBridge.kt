package com.luvatrix.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.hardware.HardwareBuffer
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCaptureSession.CaptureCallback
import android.hardware.camera2.CaptureFailure
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.DngCreator
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.StreamConfigurationMap
import android.media.Image
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.util.Range
import android.util.Size
import android.view.Surface
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import kotlin.math.roundToInt
import java.util.concurrent.atomic.AtomicLong

class CameraBridge(private val context: Context) {
    private companion object {
        const val RAW_CAPTURE_TIMEOUT_MS = 5_000L
        const val PREVIEW_MODE_CPU_YUV = "cpu_yuv"
        const val PREVIEW_MODE_GPU_PRIVATE_VULKAN = "gpu_private_vulkan"
        const val PREVIEW_QUALITY_MAX = "max"
        const val PREVIEW_QUALITY_BALANCED = "balanced"
        const val PREVIEW_QUALITY_FAST = "fast"
        const val PREVIEW_TARGET_AUTO = "auto"
        const val PREVIEW_TARGET_FULL = "full"
        const val PREVIEW_TARGET_RAW = "raw"
        const val PREVIEW_TARGET_SOLO = "solo"
        const val PREVIEW_PIPELINE_PREVIEW = "preview"
        const val PREVIEW_PIPELINE_RECORD = "record"
        const val PREVIEW_PIPELINE_HQ = "hq"
        const val PREVIEW_PIPELINE_RAWISH = "rawish"
        val RAW_ISO_STEPS = listOf(100, 200, 400, 800, 1600, 3200)
        val RAW_SHUTTER_STEPS_NS = listOf(
            1_000_000L,
            2_000_000L,
            4_000_000L,
            8_000_000L,
            16_666_667L,
            33_333_333L,
            66_666_667L,
            125_000_000L,
            250_000_000L,
        )
        val RAW_FOCUS_STEPS_DIOPTERS = listOf(0.0f, 0.5f, 1.0f, 2.0f, 4.0f, 8.0f, 12.0f)
    }

    private val cameraManager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    private val streams = LinkedHashMap<String, CameraStream>()
    private val telemetryLock = Any()
    private var handlerThread: HandlerThread? = null
    private var handler: Handler? = null
    private var mode: String = "stopped"
    private var status: String = "stopped"
    private var lastError: String = ""
    private var primaryCameraId: String? = null
    private var secondaryCameraId: String? = null
    private var pendingStart: (() -> Unit)? = null
    private var probeAuditLogged = false
    private var rawCaptureStatus: String = "unavailable"
    private var rawCaptureLastError: String = ""
    private var rawCaptureLastDngPath: String = ""
    private var rawCaptureLastMetadataPath: String = ""
    private var rawCaptureMetadata: JSONObject = JSONObject()
    private var rawCaptureMode: String = "auto"
    private var rawIsoStepIndex: Int = 3
    private var rawShutterStepIndex: Int = 5
    private var rawFocusStepIndex: Int = 0
    private var previewResultMetadata: JSONObject = JSONObject()
    private var primaryPreviewMode: String = PREVIEW_MODE_GPU_PRIVATE_VULKAN
    private var previewQualityMode: String = PREVIEW_QUALITY_MAX
    private var previewTargetMode: String = PREVIEW_TARGET_RAW
    private var previewPipelineMode: String = PREVIEW_PIPELINE_HQ
    private var previewPipelineApplied: JSONObject = JSONObject()
    private var lastGoodPrivateCombo: LastGoodPrivateCombo? = null

    private data class LastGoodPrivateCombo(
        val cameraId: String,
        val qualityMode: String,
        val width: Int,
        val height: Int,
        val includeYuvCache: Boolean,
        val includeRawSensor: Boolean,
    )

    private data class ManualControlValues(
        val iso: Int,
        val shutterNs: Long,
        val frameDurationNs: Long,
        val focusDistanceDiopters: Float,
    )

    fun startPreview(cameraId: String? = null) {
        if (!hasCameraPermission()) {
            status = "permission_denied"
            lastError = "CAMERA runtime permission is not granted"
            pendingStart = { startPreview(cameraId) }
            return
        }
        val selected = cameraId ?: firstRearCameraId()
        if (selected == null) {
            stopPreview()
            status = "unavailable"
            lastError = "no back camera with YUV_420_888 output"
            return
        }
        stopActiveStreams()
        ensureThread()
        mode = "single"
        status = "starting"
        lastError = ""
        primaryCameraId = selected
        secondaryCameraId = null
        NativeVulkan.setCameraPreviewEnabled(true)
        NativeVulkan.setCameraCoverMode("pixel_crop")
        startStream(slot = "primary", cameraId = selected)
    }

    fun startDualPreview(primaryCameraId: String, secondaryCameraId: String) {
        if (!hasCameraPermission()) {
            status = "permission_denied"
            lastError = "CAMERA runtime permission is not granted"
            pendingStart = { startDualPreview(primaryCameraId, secondaryCameraId) }
            return
        }
        if (primaryCameraId == secondaryCameraId) {
            status = "dual_unsupported"
            lastError = "primary and secondary camera IDs must differ"
            return
        }
        if (!isConcurrentPairSupported(primaryCameraId, secondaryCameraId)) {
            stopActiveStreams()
            status = "dual_unsupported"
            mode = "single"
            lastError = "camera pair is not advertised as concurrent by Camera2"
            startPreview(primaryCameraId)
            return
        }
        stopActiveStreams()
        ensureThread()
        mode = "dual"
        status = "starting"
        lastError = ""
        this.primaryCameraId = primaryCameraId
        this.secondaryCameraId = secondaryCameraId
        NativeVulkan.setCameraPreviewEnabled(true)
        NativeVulkan.setCameraCoverMode("pixel_crop")
        startStream(slot = "primary", cameraId = primaryCameraId)
        startStream(slot = "secondary", cameraId = secondaryCameraId)
    }

    fun setPrimaryCamera(cameraId: String) {
        val secondary = secondaryCameraId
        if (mode == "dual" && secondary != null && secondary != cameraId && isConcurrentPairSupported(cameraId, secondary)) {
            startDualPreview(cameraId, secondary)
        } else {
            startPreview(cameraId)
        }
    }

    fun setDualPreviewEnabled(enabled: Boolean) {
        if (!enabled) {
            startPreview(primaryCameraId)
            return
        }
        val primary = primaryCameraId ?: firstRearCameraId()
        val secondary = secondaryCameraId ?: secondaryRearCameraId(primary)
        if (primary == null || secondary == null) {
            status = "dual_unsupported"
            lastError = "not enough rear cameras exposed by Camera2"
            return
        }
        startDualPreview(primary, secondary)
    }

    fun stopPreview() {
        status = "stopped"
        mode = "stopped"
        stopActiveStreams()
        NativeVulkan.setCameraPreviewEnabled(false)
        handlerThread?.quitSafely()
        handlerThread = null
        handler = null
    }

    fun setCoverMode(mode: String) {
        NativeVulkan.setCameraCoverMode(mode)
    }

    fun captureRawStill(): String {
        if (!hasCameraPermission()) {
            updateRawCaptureTelemetry("error", null, "CAMERA runtime permission is not granted")
            return rawCaptureTelemetryJson().toString()
        }
        val stream = streams["primary"]
        if (stream == null) {
            updateRawCaptureTelemetry("error", null, "primary camera preview is not running")
            return rawCaptureTelemetryJson().toString()
        }
        val h = handler
        if (h == null) {
            updateRawCaptureTelemetry("error", stream.rawSizeOrNull(), "camera handler is unavailable")
            return rawCaptureTelemetryJson().toString()
        }
        stream.captureRawStill(h)
        return rawCaptureTelemetryJson().toString()
    }

    fun setRawCaptureMode(mode: String): String {
        rawCaptureMode = if (mode.lowercase() == "manual") "manual" else "auto"
        restartActivePreview()
        return rawControlsJson().toString()
    }

    fun setPreviewManualMode(mode: String): String {
        return setRawCaptureMode(mode)
    }

    fun adjustRawIso(deltaSteps: Int): String {
        rawCaptureMode = "manual"
        rawIsoStepIndex = (rawIsoStepIndex + deltaSteps).coerceIn(0, RAW_ISO_STEPS.lastIndex)
        restartActivePreview()
        return rawControlsJson().toString()
    }

    fun adjustRawShutter(deltaSteps: Int): String {
        rawCaptureMode = "manual"
        rawShutterStepIndex = (rawShutterStepIndex + deltaSteps).coerceIn(0, RAW_SHUTTER_STEPS_NS.lastIndex)
        restartActivePreview()
        return rawControlsJson().toString()
    }

    fun adjustRawFocus(deltaSteps: Int): String {
        rawCaptureMode = "manual"
        rawFocusStepIndex = (rawFocusStepIndex + deltaSteps).coerceIn(0, RAW_FOCUS_STEPS_DIOPTERS.lastIndex)
        restartActivePreview()
        return rawControlsJson().toString()
    }

    fun resetRawCaptureControls(): String {
        rawCaptureMode = "auto"
        rawIsoStepIndex = 3
        rawShutterStepIndex = 5
        rawFocusStepIndex = 0
        previewResultMetadata = JSONObject()
        restartActivePreview()
        return rawControlsJson().toString()
    }

    fun setPreviewQualityMode(mode: String): String {
        val normalized = when (mode.lowercase()) {
            PREVIEW_QUALITY_FAST -> PREVIEW_QUALITY_FAST
            PREVIEW_QUALITY_BALANCED -> PREVIEW_QUALITY_BALANCED
            else -> PREVIEW_QUALITY_MAX
        }
        if (previewQualityMode != normalized) {
            previewQualityMode = normalized
            val primary = primaryCameraId
            val secondary = secondaryCameraId
            if (this.mode == "dual" && primary != null && secondary != null) {
                startDualPreview(primary, secondary)
            } else if (this.mode != "stopped") {
                startPreview(primary)
            }
        }
        return JSONObject().put("preview_quality", previewQualityMode).toString()
    }

    fun setPreviewTargetMode(mode: String): String {
        val normalized = when (mode.lowercase()) {
            PREVIEW_TARGET_FULL -> PREVIEW_TARGET_FULL
            PREVIEW_TARGET_RAW -> PREVIEW_TARGET_RAW
            PREVIEW_TARGET_SOLO -> PREVIEW_TARGET_SOLO
            else -> PREVIEW_TARGET_RAW
        }
        if (previewTargetMode != normalized) {
            previewTargetMode = normalized
            val primary = primaryCameraId
            val secondary = secondaryCameraId
            if (this.mode == "dual" && primary != null && secondary != null) {
                startDualPreview(primary, secondary)
            } else if (this.mode != "stopped") {
                startPreview(primary)
            }
        }
        return JSONObject().put("preview_target_mode", previewTargetMode).toString()
    }

    fun setPreviewPipelineMode(mode: String): String {
        val normalized = when (mode.lowercase()) {
            PREVIEW_PIPELINE_RECORD -> PREVIEW_PIPELINE_RECORD
            PREVIEW_PIPELINE_HQ -> PREVIEW_PIPELINE_HQ
            PREVIEW_PIPELINE_RAWISH -> PREVIEW_PIPELINE_RAWISH
            else -> PREVIEW_PIPELINE_PREVIEW
        }
        if (previewPipelineMode != normalized) {
            previewPipelineMode = normalized
            val primary = primaryCameraId
            val secondary = secondaryCameraId
            if (this.mode == "dual" && primary != null && secondary != null) {
                startDualPreview(primary, secondary)
            } else if (this.mode != "stopped") {
                startPreview(primary)
            }
        }
        return JSONObject()
            .put("preview_pipeline_mode", previewPipelineMode)
            .put("preview_pipeline", previewPipelineApplied)
            .toString()
    }

    fun telemetryJson(): String {
        val nativeTelemetry = try {
            JSONObject(NativeVulkan.cameraTelemetryJson())
        } catch (_: Throwable) {
            JSONObject()
        }
        synchronized(telemetryLock) {
            val perCamera = JSONObject()
            for ((slot, stream) in streams) {
                perCamera.put(slot, stream.telemetryJson())
            }
            return JSONObject()
                .put("status", status)
                .put("mode", mode)
                .put("permission", if (hasCameraPermission()) "granted" else "denied")
                .put("camera_id", primaryCameraId ?: JSONObject.NULL)
                .put("primary_camera_id", primaryCameraId ?: JSONObject.NULL)
                .put("secondary_camera_id", secondaryCameraId ?: JSONObject.NULL)
                .put("active_camera_ids", JSONArray(activeCameraIds()))
                .put("dual_supported", dualSupported())
                .put("dual_active", mode == "dual")
                .put("inventory", JSONObject(inventoryJson()))
                .put("streams", perCamera)
                .put("native", nativeTelemetry)
                .put("raw_capture", rawCaptureTelemetryJson())
                .put("raw_controls", rawControlsJson())
                .put("preview_controls", previewControlsJson())
                .put("preview_quality", previewQualityMode)
                .put("preview_target_mode", previewTargetMode)
                .put("preview_pipeline_mode", previewPipelineMode)
                .put("preview_pipeline", previewPipelineApplied)
                .put("preview_renderer", nativeTelemetry.optString("preview_renderer", "cpu_yuv"))
                .put("preview_gpu_ready", nativeTelemetry.optBoolean("preview_gpu_ready", false))
                .put("private_preview", streams["primary"]?.privatePreviewJson() ?: JSONObject())
                .put("gpu_preview", nativeTelemetry.optJSONObject("gpu_preview") ?: JSONObject())
                .put("session_targets", JSONArray(streams["primary"]?.sessionTargets().orEmpty()))
                .put("last_error", lastError)
                .toString()
        }
    }

    fun requestPermissionIfNeeded(activity: Activity, requestCode: Int): Boolean {
        if (hasCameraPermission()) return true
        activity.requestPermissions(arrayOf(Manifest.permission.CAMERA), requestCode)
        return false
    }

    fun onPermissionResult(granted: Boolean) {
        if (granted) {
            val start = pendingStart
            pendingStart = null
            if (start != null) {
                start()
            } else {
                startPreview(primaryCameraId)
            }
        } else {
            status = "permission_denied"
            lastError = "CAMERA runtime permission was denied"
        }
    }

    fun inventoryJson(): String {
        return buildInventoryJson(writeAudit = true).toString()
    }

    fun cameraProbeAuditJson(): String {
        return buildInventoryJson(writeAudit = true).toString()
    }

    fun isPreviewActive(): Boolean {
        return mode != "stopped" && status != "stopped"
    }

    private fun rawCaptureTelemetryJson(): JSONObject {
        val rawSize = streams["primary"]?.rawSizeOrNull()
        val supported = rawSize != null
        val status = when {
            rawCaptureStatus == "capturing" || rawCaptureStatus == "saved" || rawCaptureStatus == "error" -> rawCaptureStatus
            supported -> "ready"
            else -> "unavailable"
        }
        val out = JSONObject()
            .put("status", status)
            .put("raw_supported", supported)
            .put("width", rawSize?.width ?: rawCaptureMetadata.optInt("width", 0))
            .put("height", rawSize?.height ?: rawCaptureMetadata.optInt("height", 0))
            .put("last_dng_path", rawCaptureLastDngPath)
            .put("last_metadata_path", rawCaptureLastMetadataPath)
            .put("last_error", rawCaptureLastError)
        for (key in rawCaptureMetadata.keys()) {
            out.put(key, rawCaptureMetadata.opt(key))
        }
        return out
    }

    private fun rawControlsJson(): JSONObject {
        val requested = requestedManualControls(primaryCameraId)
        val cameraId = primaryCameraId
        val chars = try {
            if (cameraId != null) cameraManager.getCameraCharacteristics(cameraId) else null
        } catch (_: Throwable) {
            null
        }
        val isoRange = chars?.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
        val exposureRange = chars?.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
        val maxFocus = chars?.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE)
        return JSONObject()
            .put("mode", rawCaptureMode)
            .put("requested_iso", requested.iso)
            .put("requested_shutter_ns", requested.shutterNs)
            .put("requested_frame_duration_ns", requested.frameDurationNs)
            .put("requested_focus_distance_diopters", requested.focusDistanceDiopters.toDouble())
            .put("iso_range", rangeJson(isoRange))
            .put("exposure_time_range_ns", rangeJson(exposureRange))
            .put("focus_distance_range_diopters", if (maxFocus != null) JSONArray(listOf(0.0, maxFocus.toDouble())) else JSONObject.NULL)
            .put("iso_steps", JSONArray(RAW_ISO_STEPS))
            .put("shutter_steps_ns", JSONArray(RAW_SHUTTER_STEPS_NS))
            .put("focus_steps_diopters", JSONArray(RAW_FOCUS_STEPS_DIOPTERS.map { it.toDouble() }))
    }

    private fun previewControlsJson(): JSONObject {
        val requested = requestedManualControls(primaryCameraId)
        val out = JSONObject()
            .put("mode", rawCaptureMode)
            .put("requested_iso", requested.iso)
            .put("requested_shutter_ns", requested.shutterNs)
            .put("requested_frame_duration_ns", requested.frameDurationNs)
            .put("requested_focus_distance_diopters", requested.focusDistanceDiopters.toDouble())
        for (key in previewResultMetadata.keys()) {
            out.put(key, previewResultMetadata.opt(key))
        }
        return out
    }

    private fun requestedManualControls(cameraId: String?): ManualControlValues {
        val chars = try {
            if (cameraId != null) cameraManager.getCameraCharacteristics(cameraId) else null
        } catch (_: Throwable) {
            null
        }
        val isoRange = chars?.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
        val exposureRange = chars?.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
        val maxFocus = chars?.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE)
        val requestedIso = clampRange(RAW_ISO_STEPS[rawIsoStepIndex], isoRange)
        val requestedShutterNs = clampRange(RAW_SHUTTER_STEPS_NS[rawShutterStepIndex], exposureRange)
        val requestedFocus = if (maxFocus != null) {
            RAW_FOCUS_STEPS_DIOPTERS[rawFocusStepIndex].coerceIn(0.0f, maxFocus)
        } else {
            RAW_FOCUS_STEPS_DIOPTERS[rawFocusStepIndex]
        }
        return ManualControlValues(
            iso = requestedIso,
            shutterNs = requestedShutterNs,
            frameDurationNs = maxOf(requestedShutterNs, 33_333_333L),
            focusDistanceDiopters = requestedFocus,
        )
    }

    private fun restartActivePreview() {
        val primary = primaryCameraId
        val secondary = secondaryCameraId
        if (mode == "dual" && primary != null && secondary != null) {
            startDualPreview(primary, secondary)
        } else if (mode != "stopped") {
            startPreview(primary)
        }
    }

    private fun updatePreviewResultTelemetry(result: CaptureResult) {
        previewResultMetadata = JSONObject()
            .put("actual_iso", result.get(CaptureResult.SENSOR_SENSITIVITY) ?: JSONObject.NULL)
            .put("actual_exposure_time_ns", result.get(CaptureResult.SENSOR_EXPOSURE_TIME) ?: JSONObject.NULL)
            .put("actual_frame_duration_ns", result.get(CaptureResult.SENSOR_FRAME_DURATION) ?: JSONObject.NULL)
            .put("actual_focus_distance_diopters", result.get(CaptureResult.LENS_FOCUS_DISTANCE) ?: JSONObject.NULL)
            .put("ae_state", aeStateName(result.get(CaptureResult.CONTROL_AE_STATE)))
            .put("af_state", afStateName(result.get(CaptureResult.CONTROL_AF_STATE)))
            .put("awb_state", awbStateName(result.get(CaptureResult.CONTROL_AWB_STATE)))
            .put("exposure_compensation", result.get(CaptureResult.CONTROL_AE_EXPOSURE_COMPENSATION) ?: JSONObject.NULL)
    }

    private fun <T : Comparable<T>> clampRange(value: T, range: Range<T>?): T {
        if (range == null) return value
        return when {
            value < range.lower -> range.lower
            value > range.upper -> range.upper
            else -> value
        }
    }

    private fun <T : Comparable<T>> rangeJson(range: Range<T>?): Any {
        if (range == null) return JSONObject.NULL
        return JSONArray(listOf(range.lower, range.upper))
    }

    private fun updateRawCaptureTelemetry(status: String, rawSize: Size?, error: String = "", metadata: JSONObject = JSONObject()) {
        rawCaptureStatus = status
        rawCaptureLastError = error
        rawCaptureMetadata = metadata
        if (status == "ready" || status == "capturing" || status == "unavailable") {
            rawCaptureLastDngPath = ""
            rawCaptureLastMetadataPath = ""
        }
        if (rawSize != null) {
            rawCaptureMetadata.put("width", rawSize.width)
            rawCaptureMetadata.put("height", rawSize.height)
        }
    }

    private fun setRawCaptureSaved(dngPath: String, metadataPath: String, metadata: JSONObject) {
        rawCaptureStatus = "saved"
        rawCaptureLastDngPath = dngPath
        rawCaptureLastMetadataPath = metadataPath
        rawCaptureLastError = ""
        rawCaptureMetadata = metadata
    }

    private fun buildInventoryJson(writeAudit: Boolean): JSONObject {
        val cameras = JSONArray()
        for (id in cameraManager.cameraIdList) {
            cameras.put(cameraInventoryEntry(id))
        }
        val payload = JSONObject()
            .put("cameras", cameras)
            .put("probe_summary", probeSummaryJson(cameras))
            .put("hidden_camera_probes", hiddenCameraProbesJson())
            .put("concurrent_camera_id_sets", concurrentCameraIdSetsJson())
            .put("dual_supported", dualSupported())
        if (writeAudit) {
            writeProbeAudit(payload)
        }
        return payload
    }

    private fun hasCameraPermission(): Boolean {
        return context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    }

    private fun ensureThread() {
        if (handlerThread != null && handler != null) return
        val thread = HandlerThread("luvatrix-camera")
        thread.start()
        handlerThread = thread
        handler = Handler(thread.looper)
    }

    private fun startStream(slot: String, cameraId: String) {
        val h = handler ?: return
        val yuvCacheSize = chooseYuvCacheSize(cameraId)
        if (yuvCacheSize == null) {
            status = "error"
            lastError = "camera $cameraId has no YUV_420_888 preview size"
            return
        }
        val privatePreviewCandidates = if (
            slot == "primary" &&
            primaryPreviewMode == PREVIEW_MODE_GPU_PRIVATE_VULKAN &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        ) {
            choosePrivatePreviewCandidates(cameraId, previewQualityMode)
        } else {
            emptyList()
        }
        val stream = CameraStream(
            slot = slot,
            cameraId = cameraId,
            yuvCacheSize = yuvCacheSize,
            privatePreviewCandidates = privatePreviewCandidates,
            preferredPreviewMode = if (slot == "primary") primaryPreviewMode else PREVIEW_MODE_CPU_YUV,
        )
        streams[slot] = stream
        stream.open(h)
    }

    private fun stopActiveStreams() {
        for (stream in streams.values) {
            stream.close()
        }
        streams.clear()
        NativeVulkan.clearCameraFrameSlot("primary")
        NativeVulkan.clearCameraFrameSlot("secondary")
    }

    private fun activeCameraIds(): List<String> {
        return streams.values.map { it.cameraId }
    }

    private fun firstRearCameraId(): String? {
        return rearCameraIds().firstOrNull()
    }

    private fun secondaryRearCameraId(primary: String?): String? {
        return rearCameraIds().firstOrNull { it != primary }
    }

    private fun rearCameraIds(): List<String> {
        return cameraManager.cameraIdList.filter { id ->
            val chars = cameraManager.getCameraCharacteristics(id)
            chars.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK &&
                chooseYuvCacheSize(id) != null
        }
    }

    private fun chooseYuvCacheSize(cameraId: String): Size? {
        val chars = cameraManager.getCameraCharacteristics(cameraId)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return null
        val sizes = map.getOutputSizes(ImageFormat.YUV_420_888)?.toList().orEmpty()
        if (sizes.isEmpty()) return null
        val bounded = sizes.filter { it.width <= 1920 && it.height <= 1080 }
        return (bounded.ifEmpty { sizes }).maxByOrNull { it.width.toLong() * it.height.toLong() }
    }

    private fun choosePrivatePreviewCandidates(cameraId: String, qualityMode: String = PREVIEW_QUALITY_MAX): List<Size> {
        val chars = cameraManager.getCameraCharacteristics(cameraId)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return emptyList()
        val sorted = map.getOutputSizes(ImageFormat.PRIVATE)
            ?.toList()
            .orEmpty()
            .distinctBy { "${it.width}x${it.height}" }
            .sortedWith(
                compareByDescending<Size> { it.width.toLong() * it.height.toLong() }
                    .thenByDescending { it.width }
                    .thenByDescending { it.height },
            )
        return orderPrivatePreviewCandidatesForQuality(sorted, qualityMode)
    }

    private fun orderPrivatePreviewCandidatesForQuality(candidates: List<Size>, qualityMode: String): List<Size> {
        if (qualityMode == PREVIEW_QUALITY_MAX || candidates.isEmpty()) return candidates
        val targetWidth = if (qualityMode == PREVIEW_QUALITY_FAST) 1920 else 2560
        val targetHeight = if (qualityMode == PREVIEW_QUALITY_FAST) 1080 else 1440
        val preferred = candidates.filter { size ->
            size.width <= targetWidth &&
                size.height <= targetHeight &&
                kotlin.math.abs((size.width.toDouble() / size.height.toDouble()) - (16.0 / 9.0)) < 0.08
        }
        val start = (preferred.ifEmpty { candidates.filter { it.width <= targetWidth && it.height <= targetHeight } })
            .maxByOrNull { it.width.toLong() * it.height.toLong() }
            ?: candidates.last()
        val startArea = start.width.toLong() * start.height.toLong()
        val smallerOrEqual = candidates.filter { it.width.toLong() * it.height.toLong() <= startArea }
        val larger = candidates.filter { it.width.toLong() * it.height.toLong() > startArea }
        return (smallerOrEqual + larger).distinctBy { "${it.width}x${it.height}" }
    }

    private fun chooseRawSize(cameraId: String): Size? {
        val chars = cameraManager.getCameraCharacteristics(cameraId)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return null
        return map.getOutputSizes(ImageFormat.RAW_SENSOR)
            ?.toList()
            .orEmpty()
            .maxByOrNull { it.width.toLong() * it.height.toLong() }
    }

    private fun previewTemplate(): Int {
        return if (previewPipelineMode == PREVIEW_PIPELINE_RECORD) {
            CameraDevice.TEMPLATE_RECORD
        } else {
            CameraDevice.TEMPLATE_PREVIEW
        }
    }

    private fun configureRequest(builder: CaptureRequest.Builder) {
        val applied = JSONArray()
        val errors = JSONArray()
        fun <T> setOption(key: CaptureRequest.Key<T>, value: T, label: String) {
            try {
                builder.set(key, value)
                applied.put(label)
            } catch (exc: Throwable) {
                errors.put(
                    JSONObject()
                        .put("key", label)
                        .put("error", exc.message ?: exc.javaClass.simpleName),
                )
            }
        }
        if (rawCaptureMode == "manual") {
            val controls = requestedManualControls(primaryCameraId)
            setOption(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_OFF, "control_off")
            setOption(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF, "ae_off")
            setOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF, "af_off")
            setOption(CaptureRequest.CONTROL_AWB_MODE, CaptureRequest.CONTROL_AWB_MODE_OFF, "awb_off")
            setOption(CaptureRequest.SENSOR_SENSITIVITY, controls.iso, "sensor_iso_${controls.iso}")
            setOption(CaptureRequest.SENSOR_EXPOSURE_TIME, controls.shutterNs, "sensor_exposure_${controls.shutterNs}")
            setOption(CaptureRequest.SENSOR_FRAME_DURATION, controls.frameDurationNs, "sensor_frame_${controls.frameDurationNs}")
            setOption(CaptureRequest.LENS_FOCUS_DISTANCE, controls.focusDistanceDiopters, "lens_focus_${controls.focusDistanceDiopters}")
            setOption(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_OFF, "edge_off")
            setOption(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_OFF, "nr_off")
            setOption(CaptureRequest.TONEMAP_MODE, CaptureRequest.TONEMAP_MODE_FAST, "tonemap_fast")
            setOption(CaptureRequest.COLOR_CORRECTION_ABERRATION_MODE, CaptureRequest.COLOR_CORRECTION_ABERRATION_MODE_OFF, "aberration_off")
            previewPipelineApplied = JSONObject()
                .put("mode", previewPipelineMode)
                .put("manual_preview", true)
                .put("template", if (previewPipelineMode == PREVIEW_PIPELINE_RECORD) "record" else "preview")
                .put("applied_options", applied)
                .put("errors", errors)
            return
        }
        setOption(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO, "control_auto")
        setOption(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON, "ae_on")
        setOption(CaptureRequest.CONTROL_AWB_MODE, CaptureRequest.CONTROL_AWB_MODE_AUTO, "awb_auto")
        when (previewPipelineMode) {
            PREVIEW_PIPELINE_RECORD -> {
                setOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO, "af_continuous_video")
                setOption(CaptureRequest.CONTROL_CAPTURE_INTENT, CaptureRequest.CONTROL_CAPTURE_INTENT_VIDEO_RECORD, "intent_video_record")
                setOption(CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE, CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE_ON, "video_stabilization_on")
            }
            PREVIEW_PIPELINE_HQ -> {
                setOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE, "af_continuous_picture")
                setOption(CaptureRequest.CONTROL_CAPTURE_INTENT, CaptureRequest.CONTROL_CAPTURE_INTENT_PREVIEW, "intent_preview")
                setOption(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_HIGH_QUALITY, "edge_high_quality")
                setOption(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_HIGH_QUALITY, "nr_high_quality")
                setOption(CaptureRequest.TONEMAP_MODE, CaptureRequest.TONEMAP_MODE_HIGH_QUALITY, "tonemap_high_quality")
                setOption(CaptureRequest.COLOR_CORRECTION_ABERRATION_MODE, CaptureRequest.COLOR_CORRECTION_ABERRATION_MODE_HIGH_QUALITY, "aberration_high_quality")
            }
            PREVIEW_PIPELINE_RAWISH -> {
                setOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE, "af_continuous_picture")
                setOption(CaptureRequest.CONTROL_CAPTURE_INTENT, CaptureRequest.CONTROL_CAPTURE_INTENT_PREVIEW, "intent_preview")
                setOption(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_OFF, "edge_off")
                setOption(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_OFF, "nr_off")
                setOption(CaptureRequest.TONEMAP_MODE, CaptureRequest.TONEMAP_MODE_FAST, "tonemap_fast")
                setOption(CaptureRequest.COLOR_CORRECTION_ABERRATION_MODE, CaptureRequest.COLOR_CORRECTION_ABERRATION_MODE_OFF, "aberration_off")
            }
            else -> {
                setOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE, "af_continuous_picture")
                setOption(CaptureRequest.CONTROL_CAPTURE_INTENT, CaptureRequest.CONTROL_CAPTURE_INTENT_PREVIEW, "intent_preview")
            }
        }
        previewPipelineApplied = JSONObject()
            .put("mode", previewPipelineMode)
            .put("template", if (previewPipelineMode == PREVIEW_PIPELINE_RECORD) "record" else "preview")
            .put("applied_options", applied)
            .put("errors", errors)
    }

    private fun configureRawCaptureRequest(builder: CaptureRequest.Builder, cameraId: String) {
        if (rawCaptureMode != "manual") {
            configureRequest(builder)
            return
        }
        val controls = requestedManualControls(cameraId)
        builder.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_OFF)
        builder.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF)
        builder.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF)
        builder.set(CaptureRequest.CONTROL_AWB_MODE, CaptureRequest.CONTROL_AWB_MODE_OFF)
        builder.set(CaptureRequest.SENSOR_SENSITIVITY, controls.iso)
        builder.set(CaptureRequest.SENSOR_EXPOSURE_TIME, controls.shutterNs)
        builder.set(CaptureRequest.SENSOR_FRAME_DURATION, controls.frameDurationNs)
        builder.set(CaptureRequest.LENS_FOCUS_DISTANCE, controls.focusDistanceDiopters)
        builder.set(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_OFF)
        builder.set(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_OFF)
    }

    private fun dualSupported(): Boolean {
        val rear = rearCameraIds()
        for (i in rear.indices) {
            for (j in i + 1 until rear.size) {
                if (isConcurrentPairSupported(rear[i], rear[j])) return true
            }
        }
        return false
    }

    private fun isConcurrentPairSupported(a: String, b: String): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return false
        return cameraManager.concurrentCameraIds.any { ids -> ids.contains(a) && ids.contains(b) }
    }

    private fun concurrentCameraIdSetsJson(): JSONArray {
        val out = JSONArray()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return out
        for (ids in cameraManager.concurrentCameraIds) {
            out.put(JSONArray(ids.toList()))
        }
        return out
    }

    private fun cameraInventoryEntry(id: String): JSONObject {
        val chars = cameraManager.getCameraCharacteristics(id)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val caps = chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)?.toSet().orEmpty()
        val sizes = map?.getOutputSizes(ImageFormat.YUV_420_888)?.map {
            JSONObject().put("width", it.width).put("height", it.height)
        }.orEmpty()
        val physicalIds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            chars.physicalCameraIds.toList()
        } else {
            emptyList()
        }
        val logicalMultiCamera = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
            caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA)
        val focalLengths = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
            ?.map { it.toDouble() }
            .orEmpty()
        return JSONObject()
            .put("id", id)
            .put("camera_id", id)
            .put("facing", facingName(chars.get(CameraCharacteristics.LENS_FACING)))
            .put("physical_camera_ids", JSONArray(physicalIds))
            .put("physical_camera_details", physicalCameraDetailsJson(physicalIds))
            .put("is_logical_multi_camera", logicalMultiCamera)
            .put("focal_lengths_mm", JSONArray(focalLengths))
            .put("sensor_orientation", chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: JSONObject.NULL)
            .put("color_filter_arrangement", colorFilterName(chars.get(CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT)))
            .put("yuv_420_888_sizes", JSONArray(sizes))
            .put("resolution_probe", resolutionProbeJson(id, facingName(chars.get(CameraCharacteristics.LENS_FACING)), chars, map, caps))
            .put("raw_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW))
            .put("monochrome_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME))
            .put("manual_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR))
            .put("manual_post_processing_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING))
    }

    private fun resolutionProbeJson(
        cameraId: String,
        facing: String,
        chars: CameraCharacteristics,
        standardMap: StreamConfigurationMap?,
        caps: Set<Int>,
    ): JSONObject {
        val errors = JSONArray()
        val maximumMap = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            try {
                chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP_MAXIMUM_RESOLUTION)
            } catch (exc: Throwable) {
                errors.put(probeErrorJson("maximum_resolution_map", exc))
                null
            }
        } else {
            null
        }
        if (standardMap == null) {
            errors.put(JSONObject().put("scope", "standard_map").put("error", "missing SCALER_STREAM_CONFIGURATION_MAP"))
        }
        val standardFormats = formatReportsJson(standardMap, MapKind.STANDARD, errors)
        val highResolutionFormats = formatReportsJson(standardMap, MapKind.HIGH_RESOLUTION, errors)
        val maximumResolutionFormats = formatReportsJson(maximumMap, MapKind.MAXIMUM_RESOLUTION, errors)
        val standardRaw = outputSizesJson(standardMap, ImageFormat.RAW_SENSOR)
        val standardJpeg = outputSizesJson(standardMap, ImageFormat.JPEG)
        val highResolutionJpeg = highResolutionOutputSizesJson(standardMap, ImageFormat.JPEG)
        val highResolutionRaw = highResolutionOutputSizesJson(standardMap, ImageFormat.RAW_SENSOR)
        val maximumResolutionJpeg = outputSizesJson(maximumMap, ImageFormat.JPEG)
        val maximumResolutionRaw = outputSizesJson(maximumMap, ImageFormat.RAW_SENSOR)
        val largestStill = largestSizeFromFormatReports(
            listOf(standardFormats, highResolutionFormats, maximumResolutionFormats),
            stillOnly = true,
        )
        val largestAny = largestSizeFromFormatReports(
            listOf(standardFormats, highResolutionFormats, maximumResolutionFormats),
            stillOnly = false,
        )
        val public108MpCandidate = megapixelsFromJson(largestStill) >= 80.0 || megapixelsFromJson(largestAny) >= 80.0
        val probeStatus = when {
            standardMap == null -> "failed"
            errors.length() > 0 -> "partial"
            else -> "complete"
        }
        val public108MpVerdict = when {
            public108MpCandidate -> "yes"
            probeStatus == "complete" -> "no_complete"
            probeStatus == "partial" -> "no_partial"
            else -> "unknown_failed"
        }
        return JSONObject()
            .put("sdk_int", Build.VERSION.SDK_INT)
            .put("camera_id", cameraId)
            .put("facing", facing)
            .put("hardware_level", hardwareLevelName(chars.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)))
            .put("capability_names", capabilityNamesJson(caps))
            .put("request_keys", cameraKeyNamesJson(chars.availableCaptureRequestKeys))
            .put("result_keys", cameraKeyNamesJson(chars.availableCaptureResultKeys))
            .put("characteristics_keys", cameraKeyNamesJson(chars.keys))
            .put("vendor_key_names", vendorInterestingKeyNamesJson(chars))
            .put(
                "standard",
                JSONObject()
                    .put("yuv_420_888", outputSizesJson(standardMap, ImageFormat.YUV_420_888))
                    .put("jpeg", standardJpeg)
                    .put("raw_sensor", standardRaw)
                    .put("formats", standardFormats),
            )
            .put(
                "high_resolution",
                JSONObject()
                    .put("yuv_420_888", highResolutionOutputSizesJson(standardMap, ImageFormat.YUV_420_888))
                    .put("jpeg", highResolutionJpeg)
                    .put("raw_sensor", highResolutionRaw)
                    .put("formats", highResolutionFormats),
            )
            .put(
                "maximum_resolution",
                JSONObject()
                    .put("supported", maximumMap != null)
                    .put("yuv_420_888", outputSizesJson(maximumMap, ImageFormat.YUV_420_888))
                    .put("jpeg", maximumResolutionJpeg)
                    .put("raw_sensor", maximumResolutionRaw)
                    .put("formats", maximumResolutionFormats),
            )
            .put(
                "sensor_geometry",
                JSONObject()
                    .put("pixel_array_size", sizeJson(chars.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE)))
                    .put("active_array_size", rectJson(chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)))
                    .put(
                        "pixel_array_size_maximum_resolution",
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                            sizeJson(chars.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE_MAXIMUM_RESOLUTION))
                        } else {
                            JSONObject.NULL
                        },
                    )
                    .put(
                        "active_array_size_maximum_resolution",
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                            rectJson(chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE_MAXIMUM_RESOLUTION))
                        } else {
                            JSONObject.NULL
                        },
                    ),
            )
            .put(
                "capabilities",
                JSONObject()
                    .put("ultra_high_resolution_sensor", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_ULTRA_HIGH_RESOLUTION_SENSOR))
                    .put("remosaic_reprocessing", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_REMOSAIC_REPROCESSING))
                    .put("raw", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW))
                    .put("manual_sensor", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR))
                    .put("manual_post_processing", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING)),
            )
            .put("public_108mp_candidate", public108MpCandidate)
            .put("public_108mp_verdict", public108MpVerdict)
            .put("probe_status", probeStatus)
            .put("probe_errors", errors)
            .put("largest_public_still", largestStill ?: JSONObject.NULL)
            .put("largest_public_any", largestAny ?: JSONObject.NULL)
            .put("maximum_resolution_supported", maximumMap != null)
            .put("raw_public_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW) && (standardRaw.length() > 0 || highResolutionRaw.length() > 0 || maximumResolutionRaw.length() > 0))
    }

    private enum class MapKind {
        STANDARD,
        HIGH_RESOLUTION,
        MAXIMUM_RESOLUTION,
    }

    private fun formatReportsJson(map: StreamConfigurationMap?, kind: MapKind, errors: JSONArray): JSONArray {
        val out = JSONArray()
        if (map == null) return out
        val formats = try {
            (map.outputFormats.toList() + stillLikeFormatIds()).distinct().sorted()
        } catch (exc: Throwable) {
            errors.put(probeErrorJson("${kind.name.lowercase()}_formats", exc))
            return out
        }
        for (format in formats) {
            val sizes = try {
                when (kind) {
                    MapKind.HIGH_RESOLUTION -> map.getHighResolutionOutputSizes(format)?.toList().orEmpty()
                    else -> map.getOutputSizes(format)?.toList().orEmpty()
                }
            } catch (exc: Throwable) {
                errors.put(probeErrorJson("${kind.name.lowercase()}_format_$format", exc))
                emptyList()
            }
            if (sizes.isEmpty()) continue
            val sizeArray = sizesWithDurationsJson(map, format, sizes, kind, errors)
            out.put(
                JSONObject()
                    .put("format", format)
                    .put("format_name", formatName(format))
                    .put("still_like", isStillLikeFormat(format))
                    .put("sizes", sizeArray)
                    .put("max_size", largestSizeFromArray(sizeArray) ?: JSONObject.NULL)
                    .put("max_megapixels", maxMegapixels(sizeArray)),
            )
        }
        return out
    }

    private fun sizesWithDurationsJson(
        map: StreamConfigurationMap,
        format: Int,
        sizes: List<Size>,
        kind: MapKind,
        errors: JSONArray,
    ): JSONArray {
        val out = JSONArray()
        for (size in sizes.sortedWith(compareByDescending<Size> { it.width.toLong() * it.height.toLong() }.thenByDescending { it.width })) {
            val item = sizeJson(size) as JSONObject
            try {
                item.put("min_frame_duration_ns", map.getOutputMinFrameDuration(format, size))
            } catch (exc: Throwable) {
                errors.put(probeErrorJson("${kind.name.lowercase()}_min_duration_${format}_${size.width}x${size.height}", exc))
            }
            try {
                item.put("stall_duration_ns", map.getOutputStallDuration(format, size))
            } catch (exc: Throwable) {
                errors.put(probeErrorJson("${kind.name.lowercase()}_stall_duration_${format}_${size.width}x${size.height}", exc))
            }
            out.put(item)
        }
        return out
    }

    private fun probeSummaryJson(cameras: JSONArray): JSONObject {
        var status = "complete"
        var rawPublic = false
        var verdict = "no_complete"
        var largestStill: JSONObject? = null
        var largestAny: JSONObject? = null
        for (idx in 0 until cameras.length()) {
            val camera = cameras.optJSONObject(idx) ?: continue
            val probe = camera.optJSONObject("resolution_probe") ?: continue
            rawPublic = rawPublic || probe.optBoolean("raw_public_supported", false)
            val probeStatus = probe.optString("probe_status", "failed")
            status = combineProbeStatus(status, probeStatus)
            largestStill = largerSize(largestStill, probe.optJSONObject("largest_public_still"))
            largestAny = largerSize(largestAny, probe.optJSONObject("largest_public_any"))
            if (probe.optString("public_108mp_verdict") == "yes") {
                verdict = "yes"
            }
        }
        if (verdict != "yes") {
            verdict = when (status) {
                "complete" -> "no_complete"
                "partial" -> "no_partial"
                else -> "unknown_failed"
            }
        }
        return JSONObject()
            .put("public_108mp_verdict", verdict)
            .put("largest_public_still", largestStill ?: JSONObject.NULL)
            .put("largest_public_any", largestAny ?: JSONObject.NULL)
            .put("raw_public_supported", rawPublic)
            .put("probe_status", status)
    }

    private fun combineProbeStatus(current: String, next: String): String {
        if (current == "failed" || next == "failed") return "failed"
        if (current == "partial" || next == "partial") return "partial"
        return "complete"
    }

    private fun largerSize(a: JSONObject?, b: JSONObject?): JSONObject? {
        if (a == null) return b
        if (b == null) return a
        return if (megapixelsFromJson(b) > megapixelsFromJson(a)) b else a
    }

    private fun largestSizeFromFormatReports(reports: List<JSONArray>, stillOnly: Boolean): JSONObject? {
        var largest: JSONObject? = null
        for (reportArray in reports) {
            for (idx in 0 until reportArray.length()) {
                val report = reportArray.optJSONObject(idx) ?: continue
                if (stillOnly && !report.optBoolean("still_like", false)) continue
                largest = largerSize(largest, report.optJSONObject("max_size"))
            }
        }
        return largest
    }

    private fun largestSizeFromArray(sizes: JSONArray): JSONObject? {
        var largest: JSONObject? = null
        for (idx in 0 until sizes.length()) {
            largest = largerSize(largest, sizes.optJSONObject(idx))
        }
        return largest
    }

    private fun megapixelsFromJson(size: JSONObject?): Double {
        return size?.optDouble("megapixels", 0.0) ?: 0.0
    }

    private fun stillLikeFormatIds(): List<Int> {
        return listOf(
            ImageFormat.JPEG,
            ImageFormat.RAW_SENSOR,
            ImageFormat.RAW10,
            ImageFormat.RAW12,
            ImageFormat.RAW_PRIVATE,
            ImageFormat.DEPTH_JPEG,
            ImageFormat.HEIC,
            ImageFormat.JPEG_R,
        )
    }

    private fun isStillLikeFormat(format: Int): Boolean {
        return stillLikeFormatIds().contains(format)
    }

    private fun formatName(format: Int): String {
        return when (format) {
            ImageFormat.JPEG -> "JPEG"
            ImageFormat.YUV_420_888 -> "YUV_420_888"
            ImageFormat.RAW_SENSOR -> "RAW_SENSOR"
            ImageFormat.RAW10 -> "RAW10"
            ImageFormat.RAW12 -> "RAW12"
            ImageFormat.RAW_PRIVATE -> "RAW_PRIVATE"
            ImageFormat.PRIVATE -> "PRIVATE"
            ImageFormat.DEPTH_JPEG -> "DEPTH_JPEG"
            ImageFormat.DEPTH16 -> "DEPTH16"
            ImageFormat.HEIC -> "HEIC"
            ImageFormat.JPEG_R -> "JPEG_R"
            else -> "FORMAT_$format"
        }
    }

    private fun capabilityNamesJson(caps: Set<Int>): JSONArray {
        val names = caps.map { capabilityName(it) }.sorted()
        return JSONArray(names)
    }

    private fun capabilityName(capability: Int): String {
        return when (capability) {
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE -> "BACKWARD_COMPATIBLE"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR -> "MANUAL_SENSOR"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING -> "MANUAL_POST_PROCESSING"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW -> "RAW"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_PRIVATE_REPROCESSING -> "PRIVATE_REPROCESSING"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_READ_SENSOR_SETTINGS -> "READ_SENSOR_SETTINGS"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE -> "BURST_CAPTURE"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING -> "YUV_REPROCESSING"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_DEPTH_OUTPUT -> "DEPTH_OUTPUT"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO -> "CONSTRAINED_HIGH_SPEED_VIDEO"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MOTION_TRACKING -> "MOTION_TRACKING"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA -> "LOGICAL_MULTI_CAMERA"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME -> "MONOCHROME"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SECURE_IMAGE_DATA -> "SECURE_IMAGE_DATA"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SYSTEM_CAMERA -> "SYSTEM_CAMERA"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_OFFLINE_PROCESSING -> "OFFLINE_PROCESSING"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_ULTRA_HIGH_RESOLUTION_SENSOR -> "ULTRA_HIGH_RESOLUTION_SENSOR"
            CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_REMOSAIC_REPROCESSING -> "REMOSAIC_REPROCESSING"
            else -> "CAPABILITY_$capability"
        }
    }

    private fun hardwareLevelName(level: Int?): String {
        return when (level) {
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "EXTERNAL"
            null -> "unknown"
            else -> "unknown_$level"
        }
    }

    private fun cameraKeyNamesJson(keys: List<*>?): JSONArray {
        val out = JSONArray()
        val names = keys.orEmpty().mapNotNull { key ->
            try {
                val nonNullKey = key ?: return@mapNotNull null
                nonNullKey.javaClass.getMethod("getName").invoke(nonNullKey)?.toString()
            } catch (_: Throwable) {
                null
            }
        }.sorted()
        for (name in names) {
            out.put(name)
        }
        return out
    }

    private fun vendorInterestingKeyNamesJson(chars: CameraCharacteristics): JSONArray {
        val patterns = listOf("oplus", "mediatek", "multicam", "remosaic", "raw", "pixel", "sensor", "high", "resolution")
        val names = mutableSetOf<String>()
        for (array in listOf(
            cameraKeyNamesJson(chars.availableCaptureRequestKeys),
            cameraKeyNamesJson(chars.availableCaptureResultKeys),
            cameraKeyNamesJson(chars.keys),
        )) {
            for (idx in 0 until array.length()) {
                val name = array.optString(idx)
                val lower = name.lowercase()
                if (patterns.any { lower.contains(it) }) {
                    names.add(name)
                }
            }
        }
        return JSONArray(names.sorted())
    }

    private fun probeErrorJson(scope: String, exc: Throwable): JSONObject {
        return JSONObject()
            .put("scope", scope)
            .put("error", exc.message ?: exc.javaClass.simpleName)
    }

    private fun writeProbeAudit(payload: JSONObject) {
        try {
            val summary = payload.optJSONObject("probe_summary") ?: JSONObject()
            val file = context.filesDir.resolve("camera_probe_audit.json")
            file.writeText(payload.toString(2), Charsets.UTF_8)
            if (!probeAuditLogged) {
                probeAuditLogged = true
                val verdict = summary.optString("public_108mp_verdict", "unknown")
                val probeStatus = summary.optString("probe_status", "unknown")
                val stillSize = formatSizeForLog(summary.optJSONObject("largest_public_still"))
                val anySize = formatSizeForLog(summary.optJSONObject("largest_public_any"))
                val rawPublic = summary.optBoolean("raw_public_supported", false)
                Log.i(
                    "LuvatrixCameraProbe",
                    "verdict=$verdict " +
                        "status=$probeStatus " +
                        "still=$stillSize " +
                        "any=$anySize " +
                        "raw=$rawPublic " +
                        "file=${file.absolutePath}",
                )
            }
        } catch (exc: Throwable) {
            Log.w("LuvatrixCameraProbe", "failed to write camera probe audit", exc)
        }
    }

    private fun formatSizeForLog(size: JSONObject?): String {
        if (size == null) return "none"
        val width = size.optInt("width", 0)
        val height = size.optInt("height", 0)
        if (width <= 0 || height <= 0) return "none"
        return "${width}x${height}"
    }

    private fun outputSizesJson(map: StreamConfigurationMap?, format: Int): JSONArray {
        return sizesJson(map?.getOutputSizes(format)?.toList().orEmpty())
    }

    private fun highResolutionOutputSizesJson(map: StreamConfigurationMap?, format: Int): JSONArray {
        return sizesJson(map?.getHighResolutionOutputSizes(format)?.toList().orEmpty())
    }

    private fun sizesJson(sizes: List<Size>): JSONArray {
        val out = JSONArray()
        for (size in sizes.sortedWith(compareByDescending<Size> { it.width.toLong() * it.height.toLong() }.thenByDescending { it.width })) {
            out.put(sizeJson(size))
        }
        return out
    }

    private fun sizeJson(size: Size?): Any {
        if (size == null) return JSONObject.NULL
        return JSONObject()
            .put("width", size.width)
            .put("height", size.height)
            .put("megapixels", megapixels(size.width, size.height))
    }

    private fun rectJson(rect: Rect?): Any {
        if (rect == null) return JSONObject.NULL
        return JSONObject()
            .put("left", rect.left)
            .put("top", rect.top)
            .put("right", rect.right)
            .put("bottom", rect.bottom)
            .put("width", rect.width())
            .put("height", rect.height())
            .put("megapixels", megapixels(rect.width(), rect.height()))
    }

    private fun megapixels(width: Int, height: Int): Double {
        return Math.round(width.toDouble() * height.toDouble() / 10_000.0) / 100.0
    }

    private fun maxMegapixels(sizes: JSONArray): Double {
        var best = 0.0
        for (idx in 0 until sizes.length()) {
            val item = sizes.optJSONObject(idx) ?: continue
            best = maxOf(best, item.optDouble("megapixels", 0.0))
        }
        return best
    }

    private fun physicalCameraDetailsJson(physicalIds: List<String>): JSONArray {
        val out = JSONArray()
        for (physicalId in physicalIds) {
            try {
                val chars = cameraManager.getCameraCharacteristics(physicalId)
                val caps = chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)?.toSet().orEmpty()
                val focalLengths = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                    ?.map { it.toDouble() }
                    .orEmpty()
                out.put(
                    JSONObject()
                        .put("id", physicalId)
                        .put("camera_id", physicalId)
                        .put("facing", facingName(chars.get(CameraCharacteristics.LENS_FACING)))
                        .put("focal_lengths_mm", JSONArray(focalLengths))
                        .put("sensor_orientation", chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: JSONObject.NULL)
                        .put(
                            "color_filter_arrangement",
                            colorFilterName(chars.get(CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT)),
                        )
                        .put("raw_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW))
                        .put("monochrome_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME))
                        .put("manual_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR))
                )
            } catch (exc: Throwable) {
                out.put(
                    JSONObject()
                        .put("id", physicalId)
                        .put("camera_id", physicalId)
                        .put("status", "unavailable")
                        .put("last_error", exc.message ?: exc.javaClass.simpleName)
                )
            }
        }
        return out
    }

    private fun hiddenCameraProbesJson(): JSONArray {
        val publicIds = cameraManager.cameraIdList.toSet()
        val candidates = listOf("2", "3", "4", "20", "40", "100", "aux", "mono")
        val out = JSONArray()
        for (id in candidates) {
            if (publicIds.contains(id)) {
                continue
            }
            out.put(hiddenCameraProbeJson(id))
        }
        return out
    }

    private fun hiddenCameraProbeJson(id: String): JSONObject {
        val payload = JSONObject()
            .put("camera_id", id)
            .put("listed_publicly", false)
        try {
            val chars = cameraManager.getCameraCharacteristics(id)
            val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val caps = chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)?.toSet().orEmpty()
            val sizes = map?.getOutputSizes(ImageFormat.YUV_420_888)?.map {
                JSONObject().put("width", it.width).put("height", it.height)
            }.orEmpty()
            val physicalIds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                chars.physicalCameraIds.toList()
            } else {
                emptyList()
            }
            payload
                .put("status", "characteristics_ok")
                .put("facing", facingName(chars.get(CameraCharacteristics.LENS_FACING)))
                .put("physical_camera_ids", JSONArray(physicalIds))
                .put("physical_camera_details", physicalCameraDetailsJson(physicalIds))
                .put("is_logical_multi_camera", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA))
                .put("color_filter_arrangement", colorFilterName(chars.get(CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT)))
                .put("yuv_420_888_sizes", JSONArray(sizes))
                .put("raw_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW))
                .put("monochrome_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME))
        } catch (exc: Throwable) {
            payload
                .put("status", "characteristics_failed")
                .put("last_error", exc.message ?: exc.javaClass.simpleName)
        }
        return payload
    }

    private fun facingName(value: Int?): String {
        return when (value) {
            CameraCharacteristics.LENS_FACING_BACK -> "back"
            CameraCharacteristics.LENS_FACING_FRONT -> "front"
            CameraCharacteristics.LENS_FACING_EXTERNAL -> "external"
            else -> "unknown"
        }
    }

    private fun colorFilterName(value: Int?): String {
        return when (value) {
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_RGGB -> "RGGB"
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_GRBG -> "GRBG"
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_GBRG -> "GBRG"
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_BGGR -> "BGGR"
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_RGB -> "RGB"
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_MONO -> "MONO"
            CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_NIR -> "NIR"
            null -> "unknown"
            else -> "unknown_$value"
        }
    }

    private fun aeStateName(value: Int?): String {
        return when (value) {
            CaptureResult.CONTROL_AE_STATE_INACTIVE -> "inactive"
            CaptureResult.CONTROL_AE_STATE_SEARCHING -> "searching"
            CaptureResult.CONTROL_AE_STATE_CONVERGED -> "converged"
            CaptureResult.CONTROL_AE_STATE_LOCKED -> "locked"
            CaptureResult.CONTROL_AE_STATE_FLASH_REQUIRED -> "flash_required"
            CaptureResult.CONTROL_AE_STATE_PRECAPTURE -> "precapture"
            null -> "unknown"
            else -> "unknown_$value"
        }
    }

    private fun afStateName(value: Int?): String {
        return when (value) {
            CaptureResult.CONTROL_AF_STATE_INACTIVE -> "inactive"
            CaptureResult.CONTROL_AF_STATE_PASSIVE_SCAN -> "passive_scan"
            CaptureResult.CONTROL_AF_STATE_PASSIVE_FOCUSED -> "passive_focused"
            CaptureResult.CONTROL_AF_STATE_ACTIVE_SCAN -> "active_scan"
            CaptureResult.CONTROL_AF_STATE_FOCUSED_LOCKED -> "focused_locked"
            CaptureResult.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED -> "not_focused_locked"
            CaptureResult.CONTROL_AF_STATE_PASSIVE_UNFOCUSED -> "passive_unfocused"
            null -> "unknown"
            else -> "unknown_$value"
        }
    }

    private fun awbStateName(value: Int?): String {
        return when (value) {
            CaptureResult.CONTROL_AWB_STATE_INACTIVE -> "inactive"
            CaptureResult.CONTROL_AWB_STATE_SEARCHING -> "searching"
            CaptureResult.CONTROL_AWB_STATE_CONVERGED -> "converged"
            CaptureResult.CONTROL_AWB_STATE_LOCKED -> "locked"
            null -> "unknown"
            else -> "unknown_$value"
        }
    }

    private data class CachedPreviewFrame(
        val y: ByteArray,
        val u: ByteArray,
        val v: ByteArray,
        val width: Int,
        val height: Int,
        val yRowStride: Int,
        val uRowStride: Int,
        val vRowStride: Int,
        val yPixelStride: Int,
        val uPixelStride: Int,
        val vPixelStride: Int,
        val timestampNs: Long,
        val sensorOrientationDegrees: Int,
    ) {
        fun toBitmap(): Bitmap {
            val argb = IntArray(width * height)
            for (row in 0 until height) {
                for (col in 0 until width) {
                    val yValue = y.sample(row * yRowStride + col * yPixelStride, 16)
                    val chromaRow = row / 2
                    val chromaCol = col / 2
                    val uValue = u.sample(chromaRow * uRowStride + chromaCol * uPixelStride, 128) - 128
                    val vValue = v.sample(chromaRow * vRowStride + chromaCol * vPixelStride, 128) - 128
                    val red = (yValue + 1.402f * vValue).roundToInt().coerceIn(0, 255)
                    val green = (yValue - 0.344136f * uValue - 0.714136f * vValue).roundToInt().coerceIn(0, 255)
                    val blue = (yValue + 1.772f * uValue).roundToInt().coerceIn(0, 255)
                    argb[row * width + col] = (0xff shl 24) or (red shl 16) or (green shl 8) or blue
                }
            }
            return Bitmap.createBitmap(argb, width, height, Bitmap.Config.ARGB_8888)
        }

        private fun ByteArray.sample(index: Int, fallback: Int): Int {
            return if (index in indices) this[index].toInt() and 0xff else fallback
        }
    }

    private data class SessionAttempt(
        val privateIndex: Int?,
        val includeYuvCache: Boolean,
        val includeRawSensor: Boolean,
    )

    private inner class CameraStream(
        val slot: String,
        val cameraId: String,
        val yuvCacheSize: Size,
        val privatePreviewCandidates: List<Size>,
        val preferredPreviewMode: String,
    ) {
        private val frameCount = AtomicLong(0)
        private val droppedFrames = AtomicLong(0)
        private val privateFrameCount = AtomicLong(0)
        private val privateDroppedFrames = AtomicLong(0)
        private val privateAcquireNullCount = AtomicLong(0)
        private val privateImagesClosedCount = AtomicLong(0)
        private val privateHardwareBufferCount = AtomicLong(0)
        private val privateNativeAcceptedCount = AtomicLong(0)
        private val privateNativeRejectedCount = AtomicLong(0)
        private val privateLowFpsRestarts = AtomicLong(0)
        private var cameraDevice: CameraDevice? = null
        private var captureSession: CameraCaptureSession? = null
        private var previewRequest: CaptureRequest? = null
        private var streamHandler: Handler? = null
        private var imageReader: ImageReader? = null
        private var privateImageReader: ImageReader? = null
        private var rawImageReader: ImageReader? = null
        private var pendingRawImage: Image? = null
        private var pendingRawResult: TotalCaptureResult? = null
        private var latestPreviewFrame: CachedPreviewFrame? = null
        private val rawCaptureGeneration = AtomicLong(0)
        private val rawSize: Size? = chooseRawSize(cameraId)
        private var startedAtNs: Long = 0L
        private var lastFrameTimestampNs: Long = 0L
        private var lastPrivateFrameTimestampNs: Long = 0L
        private var streamStatus: String = "starting"
        private var streamError: String = ""
        private var activePreviewMode: String = PREVIEW_MODE_CPU_YUV
        private var activeSessionTargets: List<String> = emptyList()
        private val sessionGeneration = AtomicLong(0)
        private var activeSessionAttemptIndex: Int = -1
        private var activeSessionAttemptCount: Int = 0
        private var activeSessionTargetMode: String = PREVIEW_TARGET_AUTO
        private var activePrivateAttemptStartedNs: Long = 0L
        private var activePrivateAttemptStartFrames: Long = 0L
        private var privatePreviewStatus: String = "unavailable"
        private var privatePreviewError: String = ""
        private var privatePreviewSize: Size? = null
        private val privatePreviewFailures = mutableListOf<JSONObject>()
        private val sensorOrientationDegrees: Int =
            cameraManager.getCameraCharacteristics(cameraId).get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0

        fun rawSizeOrNull(): Size? = rawSize

        fun open(handler: Handler) {
            streamHandler = handler
            imageReader = ImageReader.newInstance(yuvCacheSize.width, yuvCacheSize.height, ImageFormat.YUV_420_888, 3).apply {
                setOnImageAvailableListener({ reader ->
                    val image = reader.acquireLatestImage()
                    if (image == null) {
                        droppedFrames.incrementAndGet()
                        return@setOnImageAvailableListener
                    }
                    handleImage(image)
                }, handler)
            }
            if (shouldUsePrivatePreview()) {
                privatePreviewStatus = if (privatePreviewCandidates.isEmpty()) "unavailable" else "starting"
                if (privatePreviewCandidates.isEmpty()) {
                    privatePreviewError = "camera $cameraId exposes no ImageFormat.PRIVATE preview sizes"
                }
            }
            if (slot == "primary" && rawSize != null) {
                updateRawCaptureTelemetry("ready", rawSize)
                rawImageReader = ImageReader.newInstance(rawSize.width, rawSize.height, ImageFormat.RAW_SENSOR, 2).apply {
                    setOnImageAvailableListener({ reader ->
                        val image = reader.acquireNextImage()
                        if (image == null) {
                            updateRawCaptureTelemetry("error", rawSize, "RAW ImageReader returned null image")
                            return@setOnImageAvailableListener
                        }
                        handleRawImage(image)
                    }, handler)
                }
            } else if (slot == "primary") {
                updateRawCaptureTelemetry("unavailable", null, "active camera has no RAW_SENSOR output size")
            }
            try {
                cameraManager.openCamera(cameraId, object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        cameraDevice = camera
                        createSession(camera, handler)
                    }

                    override fun onDisconnected(camera: CameraDevice) {
                        streamStatus = "disconnected"
                        camera.close()
                    }

                    override fun onError(camera: CameraDevice, error: Int) {
                        streamStatus = "error"
                        streamError = "CameraDevice error=$error"
                        status = "error"
                        lastError = "$slot:$streamError"
                        camera.close()
                    }
                }, handler)
            } catch (exc: SecurityException) {
                streamStatus = "permission_denied"
                status = "permission_denied"
                streamError = exc.message ?: "camera permission denied"
                lastError = "$slot:$streamError"
            } catch (exc: Throwable) {
                streamStatus = "error"
                status = "error"
                streamError = exc.message ?: exc.javaClass.simpleName
                lastError = "$slot:$streamError"
            }
        }

        fun close() {
            try {
                captureSession?.close()
                cameraDevice?.close()
                privateImageReader?.close()
                imageReader?.close()
                rawImageReader?.close()
                pendingRawImage?.close()
            } catch (exc: Throwable) {
                Log.w("Luvatrix", "camera stream stop failed slot=$slot camera=$cameraId", exc)
            } finally {
                captureSession = null
                cameraDevice = null
                previewRequest = null
                streamHandler = null
                imageReader = null
                privateImageReader = null
                privatePreviewSize = null
                rawImageReader = null
                pendingRawImage = null
                pendingRawResult = null
                latestPreviewFrame = null
                activePreviewMode = PREVIEW_MODE_CPU_YUV
                activeSessionTargets = emptyList()
                privatePreviewStatus = "stopped"
                rawCaptureGeneration.incrementAndGet()
                streamStatus = "stopped"
                NativeVulkan.clearCameraHardwareBufferSlot(slot)
            }
        }

        fun captureRawStill(handler: Handler) {
            val rawReader = rawImageReader
            val raw = rawSize
            val camera = cameraDevice
            val session = captureSession
            if (rawReader == null || raw == null) {
                updateRawCaptureTelemetry("error", raw, "RAW_SENSOR is not available for active camera")
                return
            }
            if (!activeSessionTargets.contains("raw_sensor")) {
                updateRawCaptureTelemetry("error", raw, "RAW_SENSOR is not part of the active preview session")
                return
            }
            if (camera == null || session == null) {
                updateRawCaptureTelemetry("error", raw, "camera capture session is not ready")
                return
            }
            pendingRawImage?.close()
            pendingRawImage = null
            pendingRawResult = null
            val generation = rawCaptureGeneration.incrementAndGet()
            updateRawCaptureTelemetry("capturing", raw)
            try {
                val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                    addTarget(rawReader.surface)
                    configureRawCaptureRequest(this, cameraId)
                }.build()
                handler.postDelayed({
                    if (rawCaptureGeneration.get() == generation && rawCaptureStatus == "capturing") {
                        rawCaptureGeneration.incrementAndGet()
                        val missing = when {
                            pendingRawImage == null && pendingRawResult == null -> "image and capture result"
                            pendingRawImage == null -> "image"
                            else -> "capture result"
                        }
                        pendingRawImage?.close()
                        pendingRawImage = null
                        pendingRawResult = null
                        updateRawCaptureTelemetry("error", raw, "RAW capture timed out waiting for $missing")
                        resumePreviewRepeating(handler)
                    }
                }, RAW_CAPTURE_TIMEOUT_MS)
                session.stopRepeating()
                session.capture(
                    request,
                    object : CaptureCallback() {
                        override fun onCaptureCompleted(
                            session: CameraCaptureSession,
                            request: CaptureRequest,
                            result: TotalCaptureResult,
                        ) {
                            if (rawCaptureGeneration.get() != generation) return
                            pendingRawResult = result
                            maybeWriteRawCapture(handler, generation)
                        }

                        override fun onCaptureFailed(
                            session: CameraCaptureSession,
                            request: CaptureRequest,
                            failure: CaptureFailure,
                        ) {
                            if (rawCaptureGeneration.get() != generation) return
                            rawCaptureGeneration.incrementAndGet()
                            updateRawCaptureTelemetry("error", raw, "RAW capture failed reason=${failure.reason}")
                            resumePreviewRepeating(handler)
                        }
                    },
                    handler,
                )
            } catch (exc: Throwable) {
                updateRawCaptureTelemetry("error", raw, exc.message ?: exc.javaClass.simpleName)
                resumePreviewRepeating(handler)
            }
        }

        fun telemetryJson(): JSONObject {
            return JSONObject()
                .put("slot", slot)
                .put("camera_id", cameraId)
                .put("status", streamStatus)
                .put("format", if (activePreviewMode == PREVIEW_MODE_GPU_PRIVATE_VULKAN) "PRIVATE" else "YUV_420_888")
                .put("preview_mode", activePreviewMode)
                .put("session_targets", JSONArray(activeSessionTargets))
                .put("width", yuvCacheSize.width)
                .put("height", yuvCacheSize.height)
                .put("frames", frameCount.get())
                .put("dropped_frames", droppedFrames.get())
                .put("fps_estimate", fpsEstimate())
                .put("last_timestamp_ns", lastFrameTimestampNs)
                .put("private_preview", privatePreviewJson())
                .put("sensor_orientation", sensorOrientationDegrees)
                .put("last_error", streamError)
        }

        fun privatePreviewJson(): JSONObject {
            val selected = privatePreviewSize
            return JSONObject()
                .put("status", privatePreviewStatus)
                .put("preset", previewQualityMode)
                .put("width", if (privateImageReader != null && selected != null) selected.width else 0)
                .put("height", if (privateImageReader != null && selected != null) selected.height else 0)
                .put("selected_width", if (privateImageReader != null && selected != null) selected.width else 0)
                .put("selected_height", if (privateImageReader != null && selected != null) selected.height else 0)
                .put("candidate_count", privatePreviewCandidates.size)
                .put("candidate_sizes", sizesJson(privatePreviewCandidates))
                .put("target_mode", previewTargetMode)
                .put("active_target_mode", activeSessionTargetMode)
                .put("attempt_index", activeSessionAttemptIndex)
                .put("attempt_count", activeSessionAttemptCount)
                .put("active_targets", JSONArray(activeSessionTargets))
                .put("last_good_combo", lastGoodComboJson())
                .put("yuv_cache_width", yuvCacheSize.width)
                .put("yuv_cache_height", yuvCacheSize.height)
                .put("failed_attempts", JSONArray(privatePreviewFailures))
                .put("frames", privateFrameCount.get())
                .put("dropped_frames", privateDroppedFrames.get())
                .put("acquire_nulls", privateAcquireNullCount.get())
                .put("images_closed", privateImagesClosedCount.get())
                .put("hardware_buffers", privateHardwareBufferCount.get())
                .put("native_accepted", privateNativeAcceptedCount.get())
                .put("native_rejected", privateNativeRejectedCount.get())
                .put("low_fps_restarts", privateLowFpsRestarts.get())
                .put("fps_estimate", privateFpsEstimate())
                .put("last_timestamp_ns", lastPrivateFrameTimestampNs)
                .put("last_error", privatePreviewError)
        }

        fun sessionTargets(): List<String> = activeSessionTargets

        private fun lastGoodComboJson(): Any {
            val combo = lastGoodPrivateCombo ?: return JSONObject.NULL
            return JSONObject()
                .put("camera_id", combo.cameraId)
                .put("quality", combo.qualityMode)
                .put("width", combo.width)
                .put("height", combo.height)
                .put("include_yuv_cache", combo.includeYuvCache)
                .put("include_raw_sensor", combo.includeRawSensor)
        }

        private fun createSession(camera: CameraDevice, handler: Handler) {
            createSessionAttempt(camera, handler, 0)
        }

        private fun sessionAttempts(): List<SessionAttempt> {
            val attempts = mutableListOf<SessionAttempt>()
            val hasRaw = rawImageReader != null
            fun addAttempt(attempt: SessionAttempt) {
                if (attempts.none {
                        it.privateIndex == attempt.privateIndex &&
                            it.includeYuvCache == attempt.includeYuvCache &&
                            it.includeRawSensor == attempt.includeRawSensor
                    }
                ) {
                    attempts.add(attempt)
                }
            }
            val effectiveTargetMode = if (previewTargetMode == PREVIEW_TARGET_AUTO) PREVIEW_TARGET_RAW else previewTargetMode
            if (previewTargetMode == PREVIEW_TARGET_AUTO) {
                val combo = lastGoodPrivateCombo
                if (combo != null && combo.cameraId == cameraId && combo.qualityMode == previewQualityMode) {
                    val index = privatePreviewCandidates.indexOfFirst { it.width == combo.width && it.height == combo.height }
                    if (index >= 0) {
                        addAttempt(
                            SessionAttempt(
                                privateIndex = index,
                                includeYuvCache = combo.includeYuvCache,
                                includeRawSensor = combo.includeRawSensor && hasRaw,
                            ),
                        )
                    }
                }
            }
            if (shouldUsePrivatePreview()) {
                privatePreviewCandidates.indices.forEach { index ->
                    when (effectiveTargetMode) {
                        PREVIEW_TARGET_FULL -> addAttempt(SessionAttempt(privateIndex = index, includeYuvCache = true, includeRawSensor = hasRaw))
                        PREVIEW_TARGET_RAW -> addAttempt(SessionAttempt(privateIndex = index, includeYuvCache = false, includeRawSensor = hasRaw))
                        PREVIEW_TARGET_SOLO -> addAttempt(SessionAttempt(privateIndex = index, includeYuvCache = false, includeRawSensor = false))
                        else -> {
                            addAttempt(SessionAttempt(privateIndex = index, includeYuvCache = true, includeRawSensor = hasRaw))
                            addAttempt(SessionAttempt(privateIndex = index, includeYuvCache = false, includeRawSensor = hasRaw))
                            addAttempt(SessionAttempt(privateIndex = index, includeYuvCache = false, includeRawSensor = false))
                        }
                    }
                }
            }
            addAttempt(SessionAttempt(privateIndex = null, includeYuvCache = true, includeRawSensor = hasRaw))
            return attempts
        }

        private fun createSessionAttempt(camera: CameraDevice, handler: Handler, attemptIndex: Int) {
            val yuvReader = imageReader
            if (yuvReader == null) return
            val attempts = sessionAttempts()
            val attempt = attempts.getOrNull(attemptIndex)
            if (attempt == null) {
                streamStatus = "error"
                streamError = "camera capture session configure failed"
                status = "error"
                lastError = "$slot:$streamError"
                return
            }
            activeSessionAttemptIndex = attemptIndex
            activeSessionAttemptCount = attempts.size
            activeSessionTargetMode = previewTargetMode
            val privateReader = attempt.privateIndex?.let { index ->
                privatePreviewCandidates.getOrNull(index)?.let { size ->
                    ensurePrivatePreviewReader(handler, size)
                }
            }
            if (attempt.privateIndex != null && privateReader == null) {
                recordPrivatePreviewFailure(
                    attempt,
                    listOf("private_preview"),
                    privatePreviewError.ifEmpty { "PRIVATE ImageReader creation failed" },
                )
                createSessionAttempt(camera, handler, attemptIndex + 1)
                return
            }
            val usePrivate = privateReader != null
            if (!usePrivate && attempt.privateIndex == null) {
                closePrivatePreviewReader()
                if (privatePreviewCandidates.isNotEmpty()) {
                    privatePreviewStatus = "fallback"
                }
            }
            val includeYuvCache = attempt.includeYuvCache
            val previewSurface = if (usePrivate) privateReader!!.surface else yuvReader.surface
            val surfaces = mutableListOf(previewSurface)
            if (includeYuvCache && yuvReader.surface != previewSurface) surfaces.add(yuvReader.surface)
            if (attempt.includeRawSensor) rawImageReader?.surface?.let { surfaces.add(it) }
            val sessionTargets = mutableListOf<String>()
            if (usePrivate) sessionTargets.add("private_preview")
            if (includeYuvCache) sessionTargets.add(if (usePrivate) "yuv_cache" else "yuv_preview")
            if (attempt.includeRawSensor && rawImageReader != null) sessionTargets.add("raw_sensor")
            try {
                val generation = sessionGeneration.incrementAndGet()
                camera.createCaptureSession(
                    surfaces,
                    object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(session: CameraCaptureSession) {
                        captureSession = session
                        val request = camera.createCaptureRequest(previewTemplate()).apply {
                            addTarget(previewSurface)
                            if (includeYuvCache && yuvReader.surface != previewSurface) addTarget(yuvReader.surface)
                            configureRequest(this)
                        }.build()
                        previewRequest = request
                        startedAtNs = System.nanoTime()
                        activePrivateAttemptStartedNs = startedAtNs
                        activePrivateAttemptStartFrames = privateFrameCount.get()
                        activePreviewMode = if (usePrivate) PREVIEW_MODE_GPU_PRIVATE_VULKAN else PREVIEW_MODE_CPU_YUV
                        activeSessionTargets = sessionTargets
                        if (usePrivate) {
                            privatePreviewStatus = "running"
                            privatePreviewError = ""
                            schedulePrivateDeliveryWatchdog(camera, handler, attemptIndex, generation, privateFrameCount.get(), sessionTargets)
                            schedulePrivateGoodComboSampler(handler, generation, attempt, sessionTargets)
                        } else if (privatePreviewCandidates.isNotEmpty()) {
                            privatePreviewStatus = "fallback"
                        }
                        if (slot == "primary" && rawSize != null) {
                            if (attempt.includeRawSensor) {
                                updateRawCaptureTelemetry("ready", rawSize)
                            } else {
                                updateRawCaptureTelemetry("unavailable", rawSize, "RAW_SENSOR is not part of the active preview session")
                            }
                        }
                        streamStatus = "running"
                        if (streams.values.all { it.streamStatus == "running" }) {
                            status = "running"
                        }
                        val previewCallback = object : CaptureCallback() {
                            override fun onCaptureCompleted(
                                session: CameraCaptureSession,
                                request: CaptureRequest,
                                result: TotalCaptureResult,
                            ) {
                                if (slot == "primary") {
                                    updatePreviewResultTelemetry(result)
                                }
                            }
                        }
                        session.setRepeatingRequest(request, previewCallback, handler)
                    }

                    override fun onConfigureFailed(session: CameraCaptureSession) {
                        session.close()
                        if (usePrivate || attemptIndex + 1 < attempts.size) {
                            recordPrivatePreviewFailure(
                                attempt,
                                sessionTargets,
                                "session configure failed for ${sessionTargets.joinToString("+")}",
                            )
                            createSessionAttempt(camera, handler, attemptIndex + 1)
                            return
                        }
                        streamStatus = "error"
                        streamError = "camera capture session configure failed"
                        status = "error"
                        lastError = "$slot:$streamError"
                    }
                    },
                    handler,
                )
            } catch (exc: Throwable) {
                if (usePrivate || attemptIndex + 1 < attempts.size) {
                    recordPrivatePreviewFailure(attempt, sessionTargets, exc.message ?: exc.javaClass.simpleName)
                    createSessionAttempt(camera, handler, attemptIndex + 1)
                    return
                }
                streamStatus = "error"
                streamError = exc.message ?: exc.javaClass.simpleName
                status = "error"
                lastError = "$slot:$streamError"
            }
        }

        private fun recordPrivatePreviewFailure(
            attempt: SessionAttempt,
            sessionTargets: List<String>,
            reason: String,
        ) {
            val candidate = attempt.privateIndex?.let { privatePreviewCandidates.getOrNull(it) }
            if (candidate != null) {
                privatePreviewFailures.add(
                    JSONObject()
                        .put("width", candidate.width)
                        .put("height", candidate.height)
                        .put("targets", JSONArray(sessionTargets))
                        .put("reason", reason),
                )
            }
            privatePreviewStatus = "fallback"
            privatePreviewError = reason
        }

        private fun schedulePrivateDeliveryWatchdog(
            camera: CameraDevice,
            handler: Handler,
            attemptIndex: Int,
            generation: Long,
            startFrames: Long,
            sessionTargets: List<String>,
        ) {
            handler.postDelayed({
                if (sessionGeneration.get() != generation || activePreviewMode != PREVIEW_MODE_GPU_PRIVATE_VULKAN) {
                    return@postDelayed
                }
                val delivered = privateFrameCount.get() - startFrames
                if (delivered >= 3L) return@postDelayed
                val attempts = sessionAttempts()
                if (attemptIndex + 1 >= attempts.size) return@postDelayed
                val currentAttempt = attempts.getOrNull(attemptIndex) ?: return@postDelayed
                privateLowFpsRestarts.incrementAndGet()
                val reason = "PRIVATE delivery starved: $delivered frames in 2500ms for ${sessionTargets.joinToString("+")}"
                recordPrivatePreviewFailure(currentAttempt, sessionTargets, reason)
                try {
                    captureSession?.close()
                } catch (_: Throwable) {
                }
                captureSession = null
                createSessionAttempt(camera, handler, attemptIndex + 1)
            }, 2_500L)
        }

        private fun schedulePrivateGoodComboSampler(
            handler: Handler,
            generation: Long,
            attempt: SessionAttempt,
            sessionTargets: List<String>,
        ) {
            handler.postDelayed({
                if (sessionGeneration.get() != generation || activePreviewMode != PREVIEW_MODE_GPU_PRIVATE_VULKAN) {
                    return@postDelayed
                }
                val selected = privatePreviewSize ?: return@postDelayed
                val elapsedNs = System.nanoTime() - activePrivateAttemptStartedNs
                if (activePrivateAttemptStartedNs <= 0L || elapsedNs <= 0L) return@postDelayed
                val delivered = privateFrameCount.get() - activePrivateAttemptStartFrames
                val fps = delivered.toDouble() * 1_000_000_000.0 / elapsedNs.toDouble()
                if (fps >= 20.0) {
                    lastGoodPrivateCombo = LastGoodPrivateCombo(
                        cameraId = cameraId,
                        qualityMode = previewQualityMode,
                        width = selected.width,
                        height = selected.height,
                        includeYuvCache = attempt.includeYuvCache,
                        includeRawSensor = attempt.includeRawSensor,
                    )
                    privatePreviewError = "last good PRIVATE combo ${selected.width}x${selected.height} ${sessionTargets.joinToString("+")} ${"%.1f".format(fps)}fps"
                }
            }, 4_000L)
        }

        private fun shouldUsePrivatePreview(): Boolean {
            return slot == "primary" &&
                preferredPreviewMode == PREVIEW_MODE_GPU_PRIVATE_VULKAN &&
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        }

        private fun ensurePrivatePreviewReader(handler: Handler, size: Size): ImageReader? {
            val current = privatePreviewSize
            if (privateImageReader != null && current != null && current.width == size.width && current.height == size.height) {
                return privateImageReader
            }
            closePrivatePreviewReader()
            privatePreviewStatus = "starting"
            privatePreviewSize = size
            privateImageReader = createPrivatePreviewReader(handler, size)
            return privateImageReader
        }

        private fun closePrivatePreviewReader() {
            try {
                privateImageReader?.close()
            } catch (_: Throwable) {
            } finally {
                privateImageReader = null
                privatePreviewSize = null
                NativeVulkan.clearCameraHardwareBufferSlot(slot)
            }
        }

        private fun createPrivatePreviewReader(handler: Handler, size: Size): ImageReader? {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return null
            return try {
                ImageReader.newInstance(
                    size.width,
                    size.height,
                    ImageFormat.PRIVATE,
                    3,
                    HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE,
                ).apply {
                    setOnImageAvailableListener({ reader ->
                        val image = reader.acquireLatestImage()
                        if (image == null) {
                            privateDroppedFrames.incrementAndGet()
                            privateAcquireNullCount.incrementAndGet()
                            return@setOnImageAvailableListener
                        }
                        handlePrivateImage(image)
                    }, handler)
                }
            } catch (exc: Throwable) {
                privatePreviewStatus = "unavailable"
                privatePreviewError = exc.message ?: exc.javaClass.simpleName
                null
            }
        }

        private fun handleImage(image: Image) {
            try {
                val planes = image.planes
                if (planes.size < 3) {
                    droppedFrames.incrementAndGet()
                    return
                }
                val y = planeBytes(planes[0].buffer)
                val u = planeBytes(planes[1].buffer)
                val v = planeBytes(planes[2].buffer)
                lastFrameTimestampNs = image.timestamp
                if (slot == "primary") {
                    latestPreviewFrame = CachedPreviewFrame(
                        y = y,
                        u = u,
                        v = v,
                        width = image.width,
                        height = image.height,
                        yRowStride = planes[0].rowStride,
                        uRowStride = planes[1].rowStride,
                        vRowStride = planes[2].rowStride,
                        yPixelStride = planes[0].pixelStride,
                        uPixelStride = planes[1].pixelStride,
                        vPixelStride = planes[2].pixelStride,
                        timestampNs = image.timestamp,
                        sensorOrientationDegrees = sensorOrientationDegrees,
                    )
                }
                NativeVulkan.setCameraFrameYuv420(
                    slot,
                    y,
                    u,
                    v,
                    image.width,
                    image.height,
                    planes[0].rowStride,
                    planes[1].rowStride,
                    planes[2].rowStride,
                    planes[0].pixelStride,
                    planes[1].pixelStride,
                    planes[2].pixelStride,
                    image.timestamp,
                    droppedFrames.get(),
                    sensorOrientationDegrees,
                )
                frameCount.incrementAndGet()
            } catch (exc: Throwable) {
                droppedFrames.incrementAndGet()
                streamError = exc.message ?: exc.javaClass.simpleName
                lastError = "$slot:$streamError"
            } finally {
                image.close()
            }
        }

        private fun handlePrivateImage(image: Image) {
            try {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                    privateDroppedFrames.incrementAndGet()
                    return
                }
                val hardwareBuffer = image.hardwareBuffer
                if (hardwareBuffer == null) {
                    privateDroppedFrames.incrementAndGet()
                    privatePreviewStatus = "fallback"
                    privatePreviewError = "PRIVATE image had no HardwareBuffer"
                    return
                }
                privateHardwareBufferCount.incrementAndGet()
                lastPrivateFrameTimestampNs = image.timestamp
                val accepted = NativeVulkan.setCameraFrameHardwareBuffer(
                    slot,
                    hardwareBuffer,
                    image.width,
                    image.height,
                    image.timestamp,
                    sensorOrientationDegrees,
                )
                privateFrameCount.incrementAndGet()
                if (!accepted) {
                    privateNativeRejectedCount.incrementAndGet()
                    privatePreviewStatus = "fallback"
                    privatePreviewError = "native Vulkan HardwareBuffer import/render is unavailable"
                    if (!activeSessionTargets.contains("yuv_cache")) {
                        val camera = cameraDevice
                        val handler = streamHandler
                        if (camera != null && handler != null) {
                            handler.post {
                                captureSession?.close()
                                captureSession = null
                                val cpuFallbackIndex = sessionAttempts().indexOfFirst { it.privateIndex == null }
                                createSessionAttempt(camera, handler, cpuFallbackIndex.coerceAtLeast(0))
                            }
                        }
                    }
                } else {
                    privateNativeAcceptedCount.incrementAndGet()
                    privatePreviewStatus = "running"
                    privatePreviewError = ""
                }
            } catch (exc: Throwable) {
                privateDroppedFrames.incrementAndGet()
                privatePreviewStatus = "fallback"
                privatePreviewError = exc.message ?: exc.javaClass.simpleName
            } finally {
                image.close()
                privateImagesClosedCount.incrementAndGet()
            }
        }

        private fun handleRawImage(image: Image) {
            if (rawCaptureStatus != "capturing") {
                image.close()
                return
            }
            pendingRawImage?.close()
            pendingRawImage = image
            maybeWriteRawCapture(streamHandler, rawCaptureGeneration.get())
        }

        private fun maybeWriteRawCapture(handler: Handler?, generation: Long) {
            val image = pendingRawImage ?: return
            val result = pendingRawResult ?: return
            val raw = rawSize
            try {
                val timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: image.timestamp
                if (timestamp != image.timestamp) {
                    rawCaptureGeneration.incrementAndGet()
                    updateRawCaptureTelemetry(
                        "error",
                        raw,
                        "RAW image/result timestamp mismatch image=${image.timestamp} result=$timestamp",
                    )
                    return
                }
                val chars = cameraManager.getCameraCharacteristics(cameraId)
                val dir = File(context.filesDir, "raw")
                dir.mkdirs()
                val base = "camera_raw_${System.currentTimeMillis()}_${timestamp}"
                val dng = File(dir, "$base.dng")
                val metadata = rawMetadataJson(chars, result, image, dng)
                val sidecar = File(dir, "$base.json")
                FileOutputStream(dng).use { out ->
                    DngCreator(chars, result).use { dngCreator ->
                        dngCreator.writeImage(out, image)
                    }
                }
                val previewPng = File(dir, "${base}_preview.png")
                addPreviewExportMetadata(metadata, previewPng)
                sidecar.writeText(metadata.toString(2), Charsets.UTF_8)
                rawCaptureGeneration.compareAndSet(generation, generation + 1)
                setRawCaptureSaved(dng.absolutePath, sidecar.absolutePath, metadata)
            } catch (exc: Throwable) {
                rawCaptureGeneration.incrementAndGet()
                updateRawCaptureTelemetry("error", raw, exc.message ?: exc.javaClass.simpleName)
            } finally {
                pendingRawImage?.close()
                pendingRawImage = null
                pendingRawResult = null
                if (handler != null) {
                    resumePreviewRepeating(handler)
                }
            }
        }

        private fun resumePreviewRepeating(handler: Handler) {
            val session = captureSession ?: return
            val request = previewRequest ?: return
            try {
                session.setRepeatingRequest(request, null, handler)
            } catch (exc: Throwable) {
                streamError = exc.message ?: exc.javaClass.simpleName
                lastError = "$slot:$streamError"
            }
        }

        private fun rawMetadataJson(
            chars: CameraCharacteristics,
            result: TotalCaptureResult,
            image: Image,
            dng: File,
        ): JSONObject {
            val black = chars.get(CameraCharacteristics.SENSOR_BLACK_LEVEL_PATTERN)
            val white = chars.get(CameraCharacteristics.SENSOR_INFO_WHITE_LEVEL)
            val cfa = chars.get(CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT)
            val sensorOrientation = chars.get(CameraCharacteristics.SENSOR_ORIENTATION)
            val displayRotation = displayRotationDegrees()
            val rawToDisplayRotation = rawToDisplayRotationDegrees(chars, sensorOrientation, displayRotation)
            return JSONObject()
                .put("camera_id", cameraId)
                .put("format", "RAW_SENSOR")
                .put("width", image.width)
                .put("height", image.height)
                .put("timestamp_ns", image.timestamp)
                .put("dng_path", dng.absolutePath)
                .put("sensor_sensitivity_iso", result.get(CaptureResult.SENSOR_SENSITIVITY) ?: JSONObject.NULL)
                .put("sensor_exposure_time_ns", result.get(CaptureResult.SENSOR_EXPOSURE_TIME) ?: JSONObject.NULL)
                .put("sensor_frame_duration_ns", result.get(CaptureResult.SENSOR_FRAME_DURATION) ?: JSONObject.NULL)
                .put("raw_capture_mode", rawCaptureMode)
                .put("requested_iso", rawControlsJson().opt("requested_iso") ?: JSONObject.NULL)
                .put("requested_shutter_ns", rawControlsJson().opt("requested_shutter_ns") ?: JSONObject.NULL)
                .put("requested_focus_distance_diopters", rawControlsJson().opt("requested_focus_distance_diopters") ?: JSONObject.NULL)
                .put("actual_iso", result.get(CaptureResult.SENSOR_SENSITIVITY) ?: JSONObject.NULL)
                .put("actual_exposure_time_ns", result.get(CaptureResult.SENSOR_EXPOSURE_TIME) ?: JSONObject.NULL)
                .put("actual_focus_distance_diopters", result.get(CaptureResult.LENS_FOCUS_DISTANCE) ?: JSONObject.NULL)
                .put("sensor_orientation_degrees", sensorOrientation ?: JSONObject.NULL)
                .put("display_rotation_degrees", displayRotation)
                .put("raw_to_display_rotation_degrees", rawToDisplayRotation ?: JSONObject.NULL)
                .put("lens_focal_length_mm", result.get(CaptureResult.LENS_FOCAL_LENGTH) ?: JSONObject.NULL)
                .put("lens_focus_distance_diopters", result.get(CaptureResult.LENS_FOCUS_DISTANCE) ?: JSONObject.NULL)
                .put("lens_aperture", result.get(CaptureResult.LENS_APERTURE) ?: JSONObject.NULL)
                .put("ae_state", aeStateName(result.get(CaptureResult.CONTROL_AE_STATE)))
                .put("af_state", afStateName(result.get(CaptureResult.CONTROL_AF_STATE)))
                .put("awb_state", awbStateName(result.get(CaptureResult.CONTROL_AWB_STATE)))
                .put("exposure_compensation", result.get(CaptureResult.CONTROL_AE_EXPOSURE_COMPENSATION) ?: JSONObject.NULL)
                .put(
                    "orientation_note",
                    if (rawToDisplayRotation != null) {
                        "DNG pixels are sensor-native; rotate $rawToDisplayRotation degrees clockwise for upright display."
                    } else {
                        "DNG pixels are sensor-native; display rotation could not be computed from public metadata."
                    },
                )
                .put("color_filter_arrangement", colorFilterName(cfa))
                .put("white_level", white ?: JSONObject.NULL)
                .put(
                    "black_level_pattern",
                    if (black != null) {
                        JSONArray(listOf(black.getOffsetForIndex(0, 0), black.getOffsetForIndex(1, 0), black.getOffsetForIndex(0, 1), black.getOffsetForIndex(1, 1)))
                    } else {
                        JSONObject.NULL
                    },
                )
        }

        private fun addPreviewExportMetadata(metadata: JSONObject, output: File) {
            val frame = latestPreviewFrame
            if (frame == null) {
                metadata
                    .put("preview_export_status", "unavailable")
                    .put("preview_export_error", "no cached primary preview frame")
                return
            }
            try {
                val rotation = if (metadata.has("raw_to_display_rotation_degrees") && !metadata.isNull("raw_to_display_rotation_degrees")) {
                    metadata.optInt("raw_to_display_rotation_degrees", 0)
                } else {
                    frame.sensorOrientationDegrees
                }
                val bitmap = frame.toBitmap()
                val rotated = rotateBitmap(bitmap, rotation)
                output.parentFile?.mkdirs()
                FileOutputStream(output).use { out ->
                    rotated.compress(Bitmap.CompressFormat.PNG, 100, out)
                }
                if (rotated !== bitmap) {
                    bitmap.recycle()
                    rotated.recycle()
                } else {
                    bitmap.recycle()
                }
                metadata
                    .put("preview_png_path", output.absolutePath)
                    .put("preview_width", if (rotation % 180 == 0) frame.width else frame.height)
                    .put("preview_height", if (rotation % 180 == 0) frame.height else frame.width)
                    .put("preview_source_timestamp_ns", frame.timestampNs)
                    .put("preview_export_status", "saved")
                    .put("preview_export_error", "")
            } catch (exc: Throwable) {
                metadata
                    .put("preview_export_status", "error")
                    .put("preview_export_error", exc.message ?: exc.javaClass.simpleName)
            }
        }

        private fun rotateBitmap(bitmap: Bitmap, rotationDegrees: Int): Bitmap {
            val normalized = ((rotationDegrees % 360) + 360) % 360
            if (normalized == 0) return bitmap
            val matrix = Matrix().apply { postRotate(normalized.toFloat()) }
            return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        }

        private fun displayRotationDegrees(): Int {
            val rotation = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                context.display?.rotation
            } else {
                @Suppress("DEPRECATION")
                (context as? Activity)?.windowManager?.defaultDisplay?.rotation
            }
            return when (rotation) {
                Surface.ROTATION_90 -> 90
                Surface.ROTATION_180 -> 180
                Surface.ROTATION_270 -> 270
                else -> 0
            }
        }

        private fun rawToDisplayRotationDegrees(
            chars: CameraCharacteristics,
            sensorOrientation: Int?,
            displayRotation: Int,
        ): Int? {
            val sensor = sensorOrientation ?: return null
            val facing = chars.get(CameraCharacteristics.LENS_FACING)
            return if (facing == CameraCharacteristics.LENS_FACING_FRONT) {
                (sensor + displayRotation) % 360
            } else {
                (sensor - displayRotation + 360) % 360
            }
        }

        private fun fpsEstimate(): Double {
            val elapsedNs = System.nanoTime() - startedAtNs
            if (startedAtNs <= 0L || elapsedNs <= 0L) return 0.0
            return frameCount.get().toDouble() * 1_000_000_000.0 / elapsedNs.toDouble()
        }

        private fun privateFpsEstimate(): Double {
            val elapsedNs = System.nanoTime() - startedAtNs
            if (startedAtNs <= 0L || elapsedNs <= 0L) return 0.0
            return privateFrameCount.get().toDouble() * 1_000_000_000.0 / elapsedNs.toDouble()
        }
    }

    private fun planeBytes(buffer: ByteBuffer): ByteArray {
        val duplicate = buffer.duplicate()
        val bytes = ByteArray(duplicate.remaining())
        duplicate.get(bytes)
        return bytes
    }
}
