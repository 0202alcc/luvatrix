package com.luvatrix.app

import android.Manifest
import android.app.Activity
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.net.Uri
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
import android.hardware.camera2.params.LensShadingMap
import android.hardware.camera2.params.RggbChannelVector
import android.hardware.camera2.params.StreamConfigurationMap
import android.media.Image
import android.media.ImageReader
import android.media.ExifInterface
import android.provider.MediaStore
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
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.roundToInt
import java.util.concurrent.atomic.AtomicLong

class CameraBridge(private val context: Context) {
    private companion object {
        const val RAW_CAPTURE_TIMEOUT_MS = 12_000L
        const val YUV_BURST_TIMEOUT_MS = 5_000L
        const val RAW_IMAGE_READER_MAX_IMAGES = 8
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
        const val RAW_QUALITY_FAST_1600 = "fast_1600"
        const val RAW_QUALITY_BALANCED_2400 = "balanced_2400"
        const val RAW_QUALITY_FULL_RES = "full_res"
        const val RAW_DEMOSAIC_BILINEAR_FAST = "bilinear_fast"
        const val RAW_DEMOSAIC_MALVAR_APPROX = "malvar_approx"
        const val RAW_MERGE_SINGLE_FRAME = "raw_single_frame"
        const val RAW_MERGE_AVERAGE_NO_ALIGNMENT = "raw_average_no_alignment"
        const val RAW_MERGE_AVERAGE_GLOBAL_ALIGNED = "raw_average_global_aligned"
        const val RAW_MERGE_AVERAGE_MOTION_AWARE = "raw_average_motion_aware"
        const val RAW_MERGE_AVERAGE_TILE_MOTION_AWARE = "raw_average_tile_motion_aware"
        const val RAW_STYLE_NEUTRAL = "Neutral"
        const val RAW_STYLE_GOOGLE = "Google"
        const val RAW_STYLE_APPLE = "Apple"
        const val RAW_STYLE_SAMSUNG = "Samsung"
        const val RAW_STYLE_XIAOMI = "Xiaomi"
        const val RAW_FINAL_JPEG_QUALITY = 96
        const val PROCESSED_PREVIEW_JPEG_QUALITY = 88
        const val PROCESSED_PREVIEW_ENABLED = false
        const val PROCESSED_PREVIEW_MAX_EDGE = 960
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

    private val cameraManagerDelegate = lazy {
        context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    }
    private val cameraManager by cameraManagerDelegate
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
    private var burstStatus: String = "idle"
    private var burstLastError: String = ""
    private var burstLastId: String = ""
    private var burstLastPath: String = ""
    private var burstRequestedFrames: Int = 0
    private var burstCapturedFrames: Int = 0
    private var burstLastManifestPath: String = ""
    private var burstWriteMode: String = "camera_handler_sync"
    private var burstLastWriteMs: Double = 0.0
    private var processingStatus: String = "idle"
    private var processingBurstId: String = ""
    private var processingCurrentStage: String = ""
    private var processingLastOutputPath: String = ""
    private var processingLastPreviewPath: String = ""
    private var processingLastGalleryUri: String = ""
    private var processingReferenceFrame: Int? = null
    private var processingUsedFrames: Int? = null
    private var processingRejectedFrames: Int? = null
    private var processingSourceFormat: String = ""
    private var processingRenderMode: String = ""
    private var processingToneMapExposure: Double? = null
    private var processingToneMapP50: Double? = null
    private var processingToneMapP95: Double? = null
    private var processingToneMapP99: Double? = null
    private var processingToneMapHighlightRolloff: Double? = null
    private var processingToneMapShadowLift: Double? = null
    private var processingRawColorGainsUsable: Boolean? = null
    private var processingRawColorTransformUsable: Boolean? = null
    private var processingRawColorMatrixMode: String = ""
    private var processingRawColorGainMode: String = ""
    private var processingRawLensShadingMode: String = ""
    private var processingRawLensShadingMapUsed: Boolean? = null
    private var processingRawRequestedMergeMode: String = ""
    private var processingRawQualityVerdict: String = ""
    private var processingRawQualityFallback: String = ""
    private var processingRawRequestedShadowPurpleRatioAfter: Double? = null
    private var processingRawArtifactGuard: String = ""
    private var processingRawShadowPurpleRatioBefore: Double? = null
    private var processingRawShadowPurpleRatioAfter: Double? = null
    private var processingRawShadowPurpleSuppressedPixels: Long? = null
    private var processingNativeTiming: JSONObject? = null
    private var processingMergeCount: Int? = null
    private var processingMergeRejected: Int? = null
    private var processingSharpnessRejected: Int? = null
    private var processingExposureRejected: Int? = null
    private var processingAlignmentFailures: Int? = null
    private var processingMotionRejectedSamples: Long? = null
    private var processingMotionTotalSamples: Long? = null
    private var processingComparisonCount: Int? = null
    private var processingComparisonLabels: String = ""
    private var processingExposureConsistent: Boolean? = null
    private var processingLastError: String = ""
    private var lastYuvBurstId: String = ""
    private var lastYuvBurstManifestPath: String = ""
    private var lastRawBurstId: String = ""
    private var lastRawBurstManifestPath: String = ""
    private var rawCaptureMode: String = "auto"
    private var rawProcessingQualityMode: RawProcessingQuality = RawProcessingQuality.Balanced2400
    private var rawDemosaicMode: RawDemosaicMode = RawDemosaicMode.MalvarApprox
    private var rawMergeMode: RawMergeMode = RawMergeMode.AverageMotionAware
    private var rawRenderStyle: RawRenderStyle = RawRenderStyle.Google
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
    private val capabilityProfiles = LinkedHashMap<String, CameraCapabilityProfile>()
    private val processingExecutorDelegate = lazy { Executors.newSingleThreadExecutor() }
    private val processingExecutor by processingExecutorDelegate

    internal fun isCameraManagerInitializedForTest(): Boolean = cameraManagerDelegate.isInitialized()

    internal fun isProcessingExecutorInitializedForTest(): Boolean = processingExecutorDelegate.isInitialized()

    private data class LastGoodPrivateCombo(
        val cameraId: String,
        val qualityMode: String,
        val width: Int,
        val height: Int,
        val includeYuvCache: Boolean,
        val includeRawSensor: Boolean,
    )

    private data class ProcessedBurstResult(
        val burstId: String,
        val outputPath: String,
        val previewPath: String,
        val galleryUri: String,
        val referenceFrame: Int,
        val usedFrames: Int,
        val rejectedFrames: Int,
    )

    private data class ManualControlValues(
        val iso: Int,
        val shutterNs: Long,
        val frameDurationNs: Long,
        val focusDistanceDiopters: Float,
    )

    private enum class RawProcessingQuality(val wireName: String, val renderMaxEdge: Int) {
        Fast1600("fast_1600", 1600),
        Balanced2400("balanced_2400", 2400),
        FullRes("full_res", 0);

        companion object {
            fun fromWireName(value: String): RawProcessingQuality {
                return when (value.lowercase()) {
                    RAW_QUALITY_BALANCED_2400, "balanced", "2400" -> Balanced2400
                    RAW_QUALITY_FULL_RES, "full", "max" -> FullRes
                    else -> Fast1600
                }
            }
        }
    }

    private enum class RawDemosaicMode(val wireName: String) {
        BilinearFast("bilinear_fast"),
        MalvarApprox("malvar_approx");

        companion object {
            fun fromWireName(value: String): RawDemosaicMode {
                return when (value.lowercase()) {
                    RAW_DEMOSAIC_MALVAR_APPROX, "malvar", "quality" -> MalvarApprox
                    else -> BilinearFast
                }
            }
        }
    }

    private enum class RawMergeMode(val wireName: String) {
        SingleFrame("raw_single_frame"),
        AverageNoAlignment("raw_average_no_alignment"),
        AverageGlobalAligned("raw_average_global_aligned"),
        AverageMotionAware("raw_average_motion_aware"),
        AverageTileMotionAware("raw_average_tile_motion_aware");

        companion object {
            fun fromWireName(value: String): RawMergeMode {
                return when (value.lowercase()) {
                    RAW_MERGE_AVERAGE_TILE_MOTION_AWARE, "tile", "tile_motion", "tile_motion_aware" -> AverageTileMotionAware
                    RAW_MERGE_AVERAGE_MOTION_AWARE, "motion", "motion_aware" -> AverageMotionAware
                    RAW_MERGE_AVERAGE_GLOBAL_ALIGNED, "aligned", "align" -> AverageGlobalAligned
                    RAW_MERGE_AVERAGE_NO_ALIGNMENT, "average", "avg" -> AverageNoAlignment
                    else -> SingleFrame
                }
            }
        }
    }

    private enum class RawRenderStyle(val wireName: String) {
        Neutral("Neutral"),
        Google("Google"),
        Apple("Apple"),
        Samsung("Samsung"),
        Xiaomi("Xiaomi");

        companion object {
            fun fromWireName(value: String): RawRenderStyle {
                return when (value.lowercase()) {
                    "google" -> Google
                    "apple" -> Apple
                    "samsung", "samsung_pop" -> Samsung
                    "xiaomi", "xiaomi_vibrant" -> Xiaomi
                    else -> Neutral
                }
            }
        }
    }

    private data class CameraCapabilityProfile(
        val cameraId: String,
        val hardwareLevel: String,
        val supportsRaw: Boolean,
        val supportsYuvReprocess: Boolean,
        val supportsPrivatePreview: Boolean,
        val rawSizes: List<Size>,
        val yuvSizes: List<Size>,
        val privateSizes: List<Size>,
        val maxBurstTargets: Int,
        val streamCombinations: List<StreamCombo>,
        val sensorInfo: SensorInfo,
        val lensInfo: LensInfo,
        val colorInfo: ColorInfo,
    )

    private data class StreamCombo(
        val name: String,
        val outputs: List<StreamOutput>,
        val purpose: String,
    )

    private data class StreamOutput(
        val format: String,
        val width: Int,
        val height: Int,
    )

    private data class SensorInfo(
        val activeArray: Rect?,
        val pixelArraySize: Size?,
        val orientationDegrees: Int?,
        val timestampSource: Int?,
    )

    private data class LensInfo(
        val facing: String,
        val focalLengthsMm: List<Double>,
        val apertures: List<Double>,
        val minimumFocusDistanceDiopters: Float?,
    )

    private data class ColorInfo(
        val colorFilterArrangement: String,
        val whiteLevel: Int?,
        val blackLevelPattern: List<Int>?,
    )

    private data class BurstFrameRecord(
        val index: Int,
        val framePath: String,
        val metadataPath: String,
        val timestampNs: Long,
        val format: String,
        val width: Int,
        val height: Int,
        val raw16Path: String = "",
        val artifactRole: String = "",
        val sensorSensitivityIso: Int? = null,
        val sensorExposureTimeNs: Long? = null,
        val sensorFrameDurationNs: Long? = null,
    )

    private data class BurstManifest(
        val burstId: String,
        val cameraId: String,
        val format: String,
        val frameCount: Int,
        val requestedFrameCount: Int,
        val exposureStrategy: String,
        val iso: Int?,
        val exposureTimeNs: Long?,
        val awbLocked: Boolean,
        val aeLocked: Boolean,
        val afLocked: Boolean,
        val gyroAvailable: Boolean,
        val frames: List<BurstFrameRecord>,
    )

    private data class PendingYuvBurst(
        val burstId: String,
        val writer: BurstPackageWriter,
        val requestedFrames: Int,
        val startedAtNs: Long,
        val records: MutableList<BurstFrameRecord>,
    )

    private data class PendingRawBurst(
        val burstId: String,
        val writer: BurstPackageWriter,
        val requestedFrames: Int,
        val startedAtNs: Long,
        val processingMode: String,
        val records: MutableList<BurstFrameRecord>,
        val pendingRawImagesByTimestamp: MutableMap<Long, Image>,
        val pendingRawResultsByTimestamp: MutableMap<Long, TotalCaptureResult>,
    )

    private data class RawComparisonVariant(
        val label: String,
        val mergeMode: RawMergeMode,
        val renderStyle: RawRenderStyle? = null,
        val lensShadingMode: String = "auto",
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

    fun captureYuvBurst(frameCount: Int): String {
        if (!hasCameraPermission()) {
            updateBurstTelemetry("error", "CAMERA runtime permission is not granted")
            return burstTelemetryJson().toString()
        }
        val stream = streams["primary"]
        if (stream == null) {
            updateBurstTelemetry("error", "primary camera preview is not running")
            return burstTelemetryJson().toString()
        }
        val h = handler
        if (h == null) {
            updateBurstTelemetry("error", "camera handler is unavailable")
            return burstTelemetryJson().toString()
        }
        val profile = profileFor(stream.cameraId)
        val limit = minOf(maxOf(profile.maxBurstTargets, 1), 10)
        val requested = frameCount.coerceIn(1, limit)
        val burstId = "burst_${System.currentTimeMillis()}"
        val root = File(context.filesDir, "computational_camera/bursts")
        val writer = BurstPackageWriter(
            rootDir = root,
            burstId = burstId,
            cameraId = stream.cameraId,
            format = "YUV_420_888",
            requestedFrameCount = requested,
        )
        updateBurstTelemetry("capturing", requestedFrames = requested, burstId = burstId, path = writer.burstDir().absolutePath)
        stream.captureYuvBurst(h, requested, burstId, writer)
        return burstTelemetryJson().toString()
    }

    fun captureRawBurst(frameCount: Int): String {
        return captureRawBurstForProcessing(frameCount, "normal")
    }

    fun captureRawComparisonBurst(frameCount: Int): String {
        return captureRawBurstForProcessing(frameCount, "comparison")
    }

    private fun captureRawBurstForProcessing(frameCount: Int, processingMode: String): String {
        if (!hasCameraPermission()) {
            updateBurstTelemetry("error", "CAMERA runtime permission is not granted")
            return burstTelemetryJson().toString()
        }
        val stream = streams["primary"]
        if (stream == null) {
            updateBurstTelemetry("error", "primary camera preview is not running")
            return burstTelemetryJson().toString()
        }
        val h = handler
        if (h == null) {
            updateBurstTelemetry("error", "camera handler is unavailable")
            return burstTelemetryJson().toString()
        }
        val profile = profileFor(stream.cameraId)
        if (!profile.supportsRaw) {
            updateBurstTelemetry("error", "RAW_SENSOR is not available for active camera")
            return burstTelemetryJson().toString()
        }
        val limit = minOf(maxOf(profile.maxBurstTargets, 1), 10)
        val requested = frameCount.coerceIn(1, limit)
        val burstId = "raw_burst_${System.currentTimeMillis()}"
        val root = File(context.filesDir, "computational_camera/bursts")
        val writer = BurstPackageWriter(
            rootDir = root,
            burstId = burstId,
            cameraId = stream.cameraId,
            format = "RAW_SENSOR",
            requestedFrameCount = requested,
        )
        updateBurstTelemetry("capturing", requestedFrames = requested, burstId = burstId, path = writer.burstDir().absolutePath)
        stream.captureRawBurst(h, requested, burstId, writer, processingMode)
        return burstTelemetryJson().toString()
    }

    fun registerProcessedOutput(outputPath: String, previewPath: String): String {
        if (outputPath.isBlank()) {
            updateProcessingTelemetry(
                status = "error",
                stage = "registered",
                outputPath = "",
                previewPath = "",
                error = "processed output path is empty",
            )
            return processingTelemetryJson().toString()
        }
        updateProcessingTelemetry(
            status = "done",
            stage = "registered",
            outputPath = outputPath,
            previewPath = previewPath,
            error = "",
        )
        return processingTelemetryJson().toString()
    }

    fun processLastYuvBurst(): String {
        val burstId = lastYuvBurstId
        val manifestPath = lastYuvBurstManifestPath
        if (burstId.isBlank() || manifestPath.isBlank()) {
            updateProcessingTelemetry(
                status = "error",
                stage = "sharpest_native",
                error = "no saved YUV burst is available to process",
            )
            return processingTelemetryJson().toString()
        }
        processYuvBurstPackageAsync(burstId, manifestPath)
        return processingTelemetryJson().toString()
    }

    fun processLastRawBurst(): String {
        val burstId = lastRawBurstId
        val manifestPath = lastRawBurstManifestPath
        if (burstId.isBlank() || manifestPath.isBlank()) {
            updateProcessingTelemetry(
                status = "error",
                stage = "raw_single_frame",
                sourceFormat = "RAW_SENSOR",
                renderMode = "raw_single_frame",
                error = "no saved RAW burst is available to process",
            )
            return processingTelemetryJson().toString()
        }
        processRawBurstPackageAsync(burstId, manifestPath)
        return processingTelemetryJson().toString()
    }

    fun processLastRawComparison(): String {
        val burstId = lastRawBurstId
        val manifestPath = lastRawBurstManifestPath
        if (burstId.isBlank() || manifestPath.isBlank()) {
            updateProcessingTelemetry(
                status = "error",
                stage = "raw_comparison",
                sourceFormat = "RAW_SENSOR",
                renderMode = "raw_comparison",
                error = "no saved RAW burst is available to compare",
            )
            return processingTelemetryJson().toString()
        }
        processRawComparisonPackageAsync(burstId, manifestPath)
        return processingTelemetryJson().toString()
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

    fun setRawQualityMode(mode: String): String {
        rawProcessingQualityMode = RawProcessingQuality.fromWireName(mode)
        return rawControlsJson().toString()
    }

    fun setRawDemosaicMode(mode: String): String {
        rawDemosaicMode = RawDemosaicMode.fromWireName(mode)
        return rawControlsJson().toString()
    }

    fun setRawMergeMode(mode: String): String {
        rawMergeMode = RawMergeMode.fromWireName(mode)
        return rawControlsJson().toString()
    }

    fun setRawRenderStyle(style: String): String {
        rawRenderStyle = RawRenderStyle.fromWireName(style)
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
            val activeProfile = primaryCameraId?.let { profileFor(it) }
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
                .put("active_capability_profile", activeProfile?.let { capabilityProfileJson(it) } ?: JSONObject.NULL)
                .put("camera.capabilities.raw", activeProfile?.supportsRaw ?: false)
                .put("camera.capabilities.private_preview", activeProfile?.supportsPrivatePreview ?: false)
                .put("camera.capabilities.max_burst", activeProfile?.maxBurstTargets ?: 0)
                .put("camera.capabilities.hardware_level", activeProfile?.hardwareLevel ?: "UNKNOWN")
                .put("streams", perCamera)
                .put("native", nativeTelemetry)
                .put("raw_capture", rawCaptureTelemetryJson())
                .put("burst_capture", burstTelemetryJson())
                .put("processing", processingTelemetryJson())
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
        streams["primary"]?.rawDiagnosticsJson()?.let { out.put("diagnostics", it) }
        for (key in rawCaptureMetadata.keys()) {
            out.put(key, rawCaptureMetadata.opt(key))
        }
        return out
    }

    private fun burstTelemetryJson(): JSONObject {
        return JSONObject()
            .put("status", burstStatus)
            .put("last_error", burstLastError)
            .put("last_burst_id", burstLastId)
            .put("last_path", burstLastPath)
            .put("requested_frames", burstRequestedFrames)
            .put("captured_frames", burstCapturedFrames)
            .put("manifest_path", burstLastManifestPath)
            .put("write_mode", burstWriteMode)
            .put("last_write_ms", burstLastWriteMs)
    }

    private fun processingTelemetryJson(): JSONObject {
        return JSONObject()
            .put("status", processingStatus)
            .put("burst_id", processingBurstId)
            .put("stage", processingCurrentStage)
            .put("last_output_path", processingLastOutputPath)
            .put("last_preview_path", processingLastPreviewPath)
            .put("last_gallery_uri", processingLastGalleryUri)
            .put("reference_frame", processingReferenceFrame ?: JSONObject.NULL)
            .put("used_frames", processingUsedFrames ?: JSONObject.NULL)
            .put("rejected_frames", processingRejectedFrames ?: JSONObject.NULL)
            .put("source_format", processingSourceFormat)
            .put("render_mode", processingRenderMode)
            .put("raw_quality_mode", rawProcessingQualityMode.wireName)
            .put("raw_demosaic_mode", rawDemosaicMode.wireName)
            .put("raw_merge_mode", rawMergeMode.wireName)
            .put("style_profile", rawRenderStyle.wireName)
            .put("tone_map_exposure", processingToneMapExposure ?: JSONObject.NULL)
            .put("tone_map_p50", processingToneMapP50 ?: JSONObject.NULL)
            .put("tone_map_p95", processingToneMapP95 ?: JSONObject.NULL)
            .put("tone_map_p99", processingToneMapP99 ?: JSONObject.NULL)
            .put("tone_map_highlight_rolloff", processingToneMapHighlightRolloff ?: JSONObject.NULL)
            .put("tone_map_shadow_lift", processingToneMapShadowLift ?: JSONObject.NULL)
            .put("raw_color_gains_usable", processingRawColorGainsUsable ?: JSONObject.NULL)
            .put("raw_color_transform_usable", processingRawColorTransformUsable ?: JSONObject.NULL)
            .put("raw_color_matrix_mode", processingRawColorMatrixMode)
            .put("raw_color_gain_mode", processingRawColorGainMode)
            .put("raw_lens_shading_mode", processingRawLensShadingMode)
            .put("raw_lens_shading_map_used", processingRawLensShadingMapUsed ?: JSONObject.NULL)
            .put("raw_requested_merge_mode", processingRawRequestedMergeMode)
            .put("raw_quality_verdict", processingRawQualityVerdict)
            .put("raw_quality_fallback", processingRawQualityFallback)
            .put("raw_requested_shadow_purple_ratio_after", processingRawRequestedShadowPurpleRatioAfter ?: JSONObject.NULL)
            .put("raw_artifact_guard", processingRawArtifactGuard)
            .put("raw_shadow_purple_ratio_before", processingRawShadowPurpleRatioBefore ?: JSONObject.NULL)
            .put("raw_shadow_purple_ratio_after", processingRawShadowPurpleRatioAfter ?: JSONObject.NULL)
            .put("raw_shadow_purple_suppressed_pixels", processingRawShadowPurpleSuppressedPixels ?: JSONObject.NULL)
            .put("native_timing_ms", processingNativeTiming ?: JSONObject.NULL)
            .put("merge_count", processingMergeCount ?: JSONObject.NULL)
            .put("merge_rejected", processingMergeRejected ?: JSONObject.NULL)
            .put("sharpness_rejected", processingSharpnessRejected ?: JSONObject.NULL)
            .put("exposure_rejected", processingExposureRejected ?: JSONObject.NULL)
            .put("alignment_failures", processingAlignmentFailures ?: JSONObject.NULL)
            .put("motion_rejected_samples", processingMotionRejectedSamples ?: JSONObject.NULL)
            .put("motion_total_samples", processingMotionTotalSamples ?: JSONObject.NULL)
            .put("comparison_count", processingComparisonCount ?: JSONObject.NULL)
            .put("comparison_labels", processingComparisonLabels)
            .put("exposure_consistent", processingExposureConsistent ?: JSONObject.NULL)
            .put("last_error", processingLastError)
    }

    private fun updateProcessingTelemetry(
        status: String,
        stage: String,
        burstId: String = processingBurstId,
        outputPath: String = processingLastOutputPath,
        previewPath: String = processingLastPreviewPath,
        galleryUri: String = processingLastGalleryUri,
        referenceFrame: Int? = processingReferenceFrame,
        usedFrames: Int? = processingUsedFrames,
        rejectedFrames: Int? = processingRejectedFrames,
        sourceFormat: String = processingSourceFormat,
        renderMode: String = processingRenderMode,
        toneMapExposure: Double? = processingToneMapExposure,
        toneMapP50: Double? = processingToneMapP50,
        toneMapP95: Double? = processingToneMapP95,
        toneMapP99: Double? = processingToneMapP99,
        toneMapHighlightRolloff: Double? = processingToneMapHighlightRolloff,
        toneMapShadowLift: Double? = processingToneMapShadowLift,
        rawColorGainsUsable: Boolean? = processingRawColorGainsUsable,
        rawColorTransformUsable: Boolean? = processingRawColorTransformUsable,
        rawColorMatrixMode: String = processingRawColorMatrixMode,
        rawColorGainMode: String = processingRawColorGainMode,
        rawLensShadingMode: String = processingRawLensShadingMode,
        rawLensShadingMapUsed: Boolean? = processingRawLensShadingMapUsed,
        rawRequestedMergeMode: String = processingRawRequestedMergeMode,
        rawQualityVerdict: String = processingRawQualityVerdict,
        rawQualityFallback: String = processingRawQualityFallback,
        rawRequestedShadowPurpleRatioAfter: Double? = processingRawRequestedShadowPurpleRatioAfter,
        rawArtifactGuard: String = processingRawArtifactGuard,
        rawShadowPurpleRatioBefore: Double? = processingRawShadowPurpleRatioBefore,
        rawShadowPurpleRatioAfter: Double? = processingRawShadowPurpleRatioAfter,
        rawShadowPurpleSuppressedPixels: Long? = processingRawShadowPurpleSuppressedPixels,
        nativeTiming: JSONObject? = processingNativeTiming,
        mergeCount: Int? = processingMergeCount,
        mergeRejected: Int? = processingMergeRejected,
        sharpnessRejected: Int? = processingSharpnessRejected,
        exposureRejected: Int? = processingExposureRejected,
        alignmentFailures: Int? = processingAlignmentFailures,
        motionRejectedSamples: Long? = processingMotionRejectedSamples,
        motionTotalSamples: Long? = processingMotionTotalSamples,
        comparisonCount: Int? = processingComparisonCount,
        comparisonLabels: String = processingComparisonLabels,
        exposureConsistent: Boolean? = processingExposureConsistent,
        error: String = processingLastError,
    ) {
        synchronized(telemetryLock) {
            val isNewBurst = burstId.isNotEmpty() && burstId != processingBurstId
            processingStatus = status
            processingCurrentStage = stage
            processingBurstId = burstId
            processingLastOutputPath = outputPath
            processingLastPreviewPath = previewPath
            processingLastGalleryUri = galleryUri
            processingReferenceFrame = referenceFrame
            processingUsedFrames = usedFrames
            processingRejectedFrames = rejectedFrames
            processingSourceFormat = sourceFormat
            processingRenderMode = renderMode
            processingToneMapExposure = if (isNewBurst) null else toneMapExposure
            processingToneMapP50 = if (isNewBurst) null else toneMapP50
            processingToneMapP95 = if (isNewBurst) null else toneMapP95
            processingToneMapP99 = if (isNewBurst) null else toneMapP99
            processingToneMapHighlightRolloff = if (isNewBurst) null else toneMapHighlightRolloff
            processingToneMapShadowLift = if (isNewBurst) null else toneMapShadowLift
            processingRawColorGainsUsable = if (isNewBurst) null else rawColorGainsUsable
            processingRawColorTransformUsable = if (isNewBurst) null else rawColorTransformUsable
            processingRawColorMatrixMode = if (isNewBurst) "" else rawColorMatrixMode
            processingRawColorGainMode = if (isNewBurst) "" else rawColorGainMode
            processingRawLensShadingMode = if (isNewBurst) "" else rawLensShadingMode
            processingRawLensShadingMapUsed = if (isNewBurst) null else rawLensShadingMapUsed
            processingRawRequestedMergeMode = if (isNewBurst) "" else rawRequestedMergeMode
            processingRawQualityVerdict = if (isNewBurst) "" else rawQualityVerdict
            processingRawQualityFallback = if (isNewBurst) "" else rawQualityFallback
            processingRawRequestedShadowPurpleRatioAfter = if (isNewBurst) null else rawRequestedShadowPurpleRatioAfter
            processingRawArtifactGuard = if (isNewBurst) "" else rawArtifactGuard
            processingRawShadowPurpleRatioBefore = if (isNewBurst) null else rawShadowPurpleRatioBefore
            processingRawShadowPurpleRatioAfter = if (isNewBurst) null else rawShadowPurpleRatioAfter
            processingRawShadowPurpleSuppressedPixels = if (isNewBurst) null else rawShadowPurpleSuppressedPixels
            processingNativeTiming = if (isNewBurst) null else nativeTiming
            processingMergeCount = if (isNewBurst) null else mergeCount
            processingMergeRejected = if (isNewBurst) null else mergeRejected
            processingSharpnessRejected = if (isNewBurst) null else sharpnessRejected
            processingExposureRejected = if (isNewBurst) null else exposureRejected
            processingAlignmentFailures = if (isNewBurst) null else alignmentFailures
            processingMotionRejectedSamples = if (isNewBurst) null else motionRejectedSamples
            processingMotionTotalSamples = if (isNewBurst) null else motionTotalSamples
            processingComparisonCount = if (isNewBurst) null else comparisonCount
            processingComparisonLabels = if (isNewBurst) "" else comparisonLabels
            processingExposureConsistent = if (isNewBurst) null else exposureConsistent
            processingLastError = error
        }
    }

    private fun processYuvBurstPackageAsync(burstId: String, manifestPath: String) {
        updateProcessingTelemetry(
            status = "queued",
            stage = "sharpest_native",
            burstId = burstId,
            outputPath = "",
            previewPath = "",
            galleryUri = "",
            referenceFrame = null,
            usedFrames = null,
            rejectedFrames = null,
            error = "",
        )
        processingExecutor.execute {
            try {
                val manifestFile = File(manifestPath)
                if (!manifestFile.exists()) {
                    updateProcessingTelemetry("error", "sharpest_native", burstId = burstId, error = "missing burst manifest")
                    return@execute
                }
                val outputDir = File(context.filesDir, "computational_camera/processed/$burstId").apply { mkdirs() }
                val outputRgba = File(outputDir, "native_output.rgba")
                val previewRgba = File(outputDir, "native_preview.rgba")
                val outputJpeg = File(outputDir, "IMG_$burstId.jpg")
                val previewJpeg = File(outputDir, "IMG_${burstId}_preview.jpg")
                updateProcessingTelemetry("processing", "sharpest_native", burstId = burstId, error = "")
                val nativePayload = JSONObject(
                    NativeCameraProcessor.processYuvBurst(
                        manifestFile.absolutePath,
                        outputRgba.absolutePath,
                        previewRgba.absolutePath,
                        if (PROCESSED_PREVIEW_ENABLED) PROCESSED_PREVIEW_MAX_EDGE else 0,
                    )
                )
                if (nativePayload.optString("status") != "ok") {
                    updateProcessingTelemetry(
                        status = "error",
                        stage = "sharpest_native",
                        burstId = burstId,
                        error = nativePayload.optString("error", "native status=error"),
                    )
                    writeProcessingManifest(outputDir, nativePayload)
                    return@execute
                }
                val width = nativePayload.optInt("width", 0)
                val height = nativePayload.optInt("height", 0)
                val previewWidth = nativePayload.optInt("preview_width", 0)
                val previewHeight = nativePayload.optInt("preview_height", 0)
                if (width <= 0 || height <= 0) {
                    updateProcessingTelemetry("error", "jpeg_export", burstId = burstId, error = "RGBA dimensions missing")
                    return@execute
                }
                updateProcessingTelemetry("exporting", "jpeg_export", burstId = burstId, error = "")
                val outputRotationDegrees = processedJpegRotationDegrees()
                val exifMetadata = processedExifMetadata(manifestPath)
                compressRgbaToJpeg(outputRgba, width, height, outputJpeg, RAW_FINAL_JPEG_QUALITY, outputRotationDegrees, exifMetadata)
                if (PROCESSED_PREVIEW_ENABLED && previewWidth > 0 && previewHeight > 0) {
                    compressRgbaToJpeg(previewRgba, previewWidth, previewHeight, previewJpeg, PROCESSED_PREVIEW_JPEG_QUALITY)
                }
                updateProcessingTelemetry("exporting", "gallery_export", burstId = burstId, error = "")
                val galleryUri = publishJpegToGallery(outputJpeg, outputJpeg.name).toString()
                val result = ProcessedBurstResult(
                    burstId = burstId,
                    outputPath = outputJpeg.absolutePath,
                    previewPath = if (PROCESSED_PREVIEW_ENABLED) previewJpeg.absolutePath else "",
                    galleryUri = galleryUri,
                    referenceFrame = nativePayload.optInt("raw_reference_frame", nativePayload.optInt("reference_frame", -1)),
                    usedFrames = nativePayload.optInt("used_frames", 0),
                    rejectedFrames = nativePayload.optInt("rejected_frames", 0),
                )
                writeProcessingManifest(
                    outputDir,
                    JSONObject(nativePayload.toString())
                        .put("output_path", result.outputPath)
                        .put("preview_path", result.previewPath)
                        .put("gallery_uri", result.galleryUri)
                        .put("output_orientation_degrees", outputRotationDegrees)
                        .put("raw_quality_mode", nativePayload.optString("raw_quality_mode", rawProcessingQualityMode.wireName)),
                )
                updateProcessingTelemetry(
                    status = "done",
                    stage = "gallery_export",
                    burstId = result.burstId,
                    outputPath = result.outputPath,
                    previewPath = result.previewPath,
                    galleryUri = result.galleryUri,
                    referenceFrame = result.referenceFrame,
                    usedFrames = result.usedFrames,
                    rejectedFrames = result.rejectedFrames,
                    error = "",
                )
            } catch (exc: Throwable) {
                updateProcessingTelemetry(
                    status = "error",
                    stage = if (processingCurrentStage.isBlank()) "sharpest_native" else processingCurrentStage,
                    burstId = burstId,
                    error = exc.message ?: exc.javaClass.simpleName,
                )
            }
        }
    }

    private fun processRawBurstPackageAsync(burstId: String, manifestPath: String) {
        val qualityMode = rawProcessingQualityMode
        val demosaicMode = rawDemosaicMode
        val mergeMode = RawMergeMode.AverageMotionAware
        val renderStyle = rawRenderStyle
        updateProcessingTelemetry(
            status = "queued",
            stage = "raw_single_frame",
            burstId = burstId,
            outputPath = "",
            previewPath = "",
            galleryUri = "",
            referenceFrame = null,
            usedFrames = null,
            rejectedFrames = null,
            sourceFormat = "RAW_SENSOR",
            renderMode = mergeMode.wireName,
            error = "",
        )
        processingExecutor.execute {
            try {
                val manifestFile = File(manifestPath)
                if (!manifestFile.exists()) {
                    updateProcessingTelemetry(
                        "error",
                        "raw_single_frame",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = mergeMode.wireName,
                        error = "missing burst manifest",
                    )
                    return@execute
                }
                val outputDir = File(context.filesDir, "computational_camera/processed/$burstId").apply { mkdirs() }
                val outputRgba = File(outputDir, "native_output.rgba")
                val previewRgba = File(outputDir, "native_preview.rgba")
                val outputJpeg = File(outputDir, "IMG_$burstId.jpg")
                val previewJpeg = File(outputDir, "IMG_${burstId}_preview.jpg")
                updateProcessingTelemetry(
                    "processing",
                    "raw_single_frame",
                    burstId = burstId,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = mergeMode.wireName,
                    error = "",
                )
                val nativePayload = JSONObject(
                    NativeCameraProcessor.processRawBurst(
                        manifestFile.absolutePath,
                        outputRgba.absolutePath,
                        previewRgba.absolutePath,
                        if (PROCESSED_PREVIEW_ENABLED) PROCESSED_PREVIEW_MAX_EDGE else 0,
                        qualityMode.wireName,
                            demosaicMode.wireName,
                            mergeMode.wireName,
                            renderStyle.wireName,
                            "auto",
                        )
                    )
                if (nativePayload.optString("status") != "ok") {
                    updateProcessingTelemetry(
                        status = "error",
                        stage = "raw_single_frame",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = mergeMode.wireName,
                        error = nativePayload.optString("error", "native status=error"),
                    )
                    writeProcessingManifest(outputDir, nativePayload)
                    return@execute
                }
                val width = nativePayload.optInt("width", 0)
                val height = nativePayload.optInt("height", 0)
                val previewWidth = nativePayload.optInt("preview_width", 0)
                val previewHeight = nativePayload.optInt("preview_height", 0)
                if (width <= 0 || height <= 0) {
                    updateProcessingTelemetry(
                        "error",
                        "raw_jpeg_export",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = mergeMode.wireName,
                        error = "RGBA dimensions missing",
                    )
                    return@execute
                }
                updateProcessingTelemetry(
                    "exporting",
                    "raw_jpeg_export",
                    burstId = burstId,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = mergeMode.wireName,
                    error = "",
                )
                val outputRotationDegrees = processedJpegRotationDegrees()
                compressRgbaToJpeg(outputRgba, width, height, outputJpeg, 94, outputRotationDegrees, null)
                if (PROCESSED_PREVIEW_ENABLED && previewWidth > 0 && previewHeight > 0) {
                    compressRgbaToJpeg(previewRgba, previewWidth, previewHeight, previewJpeg, PROCESSED_PREVIEW_JPEG_QUALITY)
                }
                updateProcessingTelemetry(
                    "exporting",
                    "raw_gallery_export",
                    burstId = burstId,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = mergeMode.wireName,
                    error = "",
                )
                val galleryUri = publishJpegToGallery(outputJpeg, outputJpeg.name).toString()
                val result = ProcessedBurstResult(
                    burstId = burstId,
                    outputPath = outputJpeg.absolutePath,
                    previewPath = if (PROCESSED_PREVIEW_ENABLED) previewJpeg.absolutePath else "",
                    galleryUri = galleryUri,
                    referenceFrame = nativePayload.optInt("reference_frame", -1),
                    usedFrames = nativePayload.optInt("used_frames", 0),
                    rejectedFrames = nativePayload.optInt("rejected_frames", 0),
                )
                writeProcessingManifest(
                    outputDir,
                    JSONObject(nativePayload.toString())
                        .put("output_path", result.outputPath)
                        .put("preview_path", result.previewPath)
                        .put("gallery_uri", result.galleryUri)
                        .put("output_orientation_degrees", outputRotationDegrees)
                        .put("raw_quality_mode", nativePayload.optString("raw_quality_mode", qualityMode.wireName))
                        .put("raw_demosaic_mode", nativePayload.optString("raw_demosaic_mode", demosaicMode.wireName))
                        .put("raw_merge_mode", nativePayload.optString("raw_merge_mode", mergeMode.wireName))
                        .put("style_profile", nativePayload.optString("style_profile", renderStyle.wireName)),
                )
                updateProcessingTelemetry(
                    status = "done",
                    stage = "raw_gallery_export",
                    burstId = result.burstId,
                    outputPath = result.outputPath,
                    previewPath = result.previewPath,
                    galleryUri = result.galleryUri,
                    referenceFrame = result.referenceFrame,
                    usedFrames = result.usedFrames,
                    rejectedFrames = result.rejectedFrames,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = nativePayload.optString("render_mode", mergeMode.wireName),
                    toneMapExposure = nativePayload.optFiniteDouble("tone_map_exposure"),
                    toneMapP50 = nativePayload.optFiniteDouble("tone_map_p50"),
                    toneMapP95 = nativePayload.optFiniteDouble("tone_map_p95"),
                    toneMapP99 = nativePayload.optFiniteDouble("tone_map_p99"),
                    toneMapHighlightRolloff = nativePayload.optFiniteDouble("tone_map_highlight_rolloff"),
                    toneMapShadowLift = nativePayload.optFiniteDouble("tone_map_shadow_lift"),
                    rawColorGainsUsable = nativePayload.optNullableBoolean("raw_color_gains_usable"),
                    rawColorTransformUsable = nativePayload.optNullableBoolean("raw_color_transform_usable"),
                    rawColorMatrixMode = nativePayload.optString("raw_color_matrix_mode", ""),
                    rawColorGainMode = nativePayload.optString("raw_color_gain_mode", ""),
                    rawLensShadingMode = nativePayload.optString("raw_lens_shading_mode", ""),
                    rawLensShadingMapUsed = nativePayload.optNullableBoolean("raw_lens_shading_map_used"),
                    rawRequestedMergeMode = nativePayload.optString("raw_requested_merge_mode", ""),
                    rawQualityVerdict = nativePayload.optString("raw_quality_verdict", ""),
                    rawQualityFallback = nativePayload.optString("raw_quality_fallback", ""),
                    rawRequestedShadowPurpleRatioAfter = nativePayload.optFiniteDouble("raw_requested_shadow_purple_ratio_after"),
                    rawArtifactGuard = nativePayload.optString("raw_artifact_guard", ""),
                    rawShadowPurpleRatioBefore = nativePayload.optFiniteDouble("raw_shadow_purple_ratio_before"),
                    rawShadowPurpleRatioAfter = nativePayload.optFiniteDouble("raw_shadow_purple_ratio_after"),
                    rawShadowPurpleSuppressedPixels = if (nativePayload.has("raw_shadow_purple_suppressed_pixels")) nativePayload.optLong("raw_shadow_purple_suppressed_pixels") else null,
                    nativeTiming = nativePayload.optJSONObject("native_timing_ms"),
                    mergeCount = nativePayload.optNullableInt("merge_count"),
                    mergeRejected = nativePayload.optNullableInt("merge_rejected"),
                    sharpnessRejected = nativePayload.optNullableInt("sharpness_rejected"),
                    exposureRejected = nativePayload.optNullableInt("exposure_rejected"),
                    alignmentFailures = nativePayload.optNullableInt("alignment_failures"),
                    motionRejectedSamples = if (nativePayload.has("motion_rejected_samples")) nativePayload.optLong("motion_rejected_samples") else null,
                    motionTotalSamples = if (nativePayload.has("motion_total_samples")) nativePayload.optLong("motion_total_samples") else null,
                    exposureConsistent = nativePayload.optNullableBoolean("exposure_consistent"),
                    error = "",
                )
            } catch (exc: Throwable) {
                updateProcessingTelemetry(
                    status = "error",
                    stage = if (processingCurrentStage.isBlank()) "raw_single_frame" else processingCurrentStage,
                    burstId = burstId,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = mergeMode.wireName,
                    error = exc.message ?: exc.javaClass.simpleName,
                )
            }
        }
    }

    private fun processRawComparisonPackageAsync(burstId: String, manifestPath: String) {
        val qualityMode = rawProcessingQualityMode
        val demosaicMode = rawDemosaicMode
        val renderStyle = rawRenderStyle
        val variants = listOf(
            RawComparisonVariant("single", RawMergeMode.SingleFrame),
            RawComparisonVariant("aligned", RawMergeMode.AverageGlobalAligned),
            RawComparisonVariant("motion", RawMergeMode.AverageMotionAware),
            RawComparisonVariant("unshaded", RawMergeMode.AverageMotionAware, lensShadingMode = "off"),
            RawComparisonVariant("radial", RawMergeMode.AverageMotionAware, lensShadingMode = "radial"),
            RawComparisonVariant("tile", RawMergeMode.AverageTileMotionAware),
            RawComparisonVariant("neutral", RawMergeMode.AverageTileMotionAware, RawRenderStyle.Neutral),
        )
        val labelText = variants.joinToString(",") { it.label }
        updateProcessingTelemetry(
            status = "queued",
            stage = "raw_comparison",
            burstId = burstId,
            outputPath = "",
            previewPath = "",
            galleryUri = "",
            referenceFrame = null,
            usedFrames = null,
            rejectedFrames = null,
            sourceFormat = "RAW_SENSOR",
            renderMode = "raw_comparison",
            comparisonCount = variants.size,
            comparisonLabels = labelText,
            error = "",
        )
        processingExecutor.execute {
            try {
                val manifestFile = File(manifestPath)
                if (!manifestFile.exists()) {
                    updateProcessingTelemetry(
                        "error",
                        "raw_comparison",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = "raw_comparison",
                        comparisonCount = variants.size,
                        comparisonLabels = labelText,
                        error = "missing burst manifest",
                    )
                    return@execute
                }
                val outputDir = File(context.filesDir, "computational_camera/processed/${burstId}_comparison").apply { mkdirs() }
                val variantPayloads = JSONArray()
                var finalPayload: JSONObject? = null
                var finalResult: ProcessedBurstResult? = null
                for (variant in variants) {
                    val outputRgba = File(outputDir, "native_${variant.label}.rgba")
                    val previewRgba = File(outputDir, "native_${variant.label}_preview.rgba")
                    val outputJpeg = File(outputDir, "IMG_${burstId}_compare_${variant.label}.jpg")
                    val previewJpeg = File(outputDir, "IMG_${burstId}_compare_${variant.label}_preview.jpg")
                    updateProcessingTelemetry(
                        "processing",
                        "raw_compare_${variant.label}",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = variant.mergeMode.wireName,
                        comparisonCount = variants.size,
                        comparisonLabels = labelText,
                        error = "",
                    )
                    val nativePayload = JSONObject(
                        NativeCameraProcessor.processRawBurst(
                            manifestFile.absolutePath,
                            outputRgba.absolutePath,
                            previewRgba.absolutePath,
                            if (PROCESSED_PREVIEW_ENABLED) PROCESSED_PREVIEW_MAX_EDGE else 0,
                            qualityMode.wireName,
                            demosaicMode.wireName,
                            variant.mergeMode.wireName,
                            (variant.renderStyle ?: renderStyle).wireName,
                            variant.lensShadingMode,
                        )
                    )
                    nativePayload.put("comparison_label", variant.label)
                    if (nativePayload.optString("status") != "ok") {
                        nativePayload.put("output_path", outputJpeg.absolutePath)
                        variantPayloads.put(nativePayload)
                        continue
                    }
                    val width = nativePayload.optInt("width", 0)
                    val height = nativePayload.optInt("height", 0)
                    val previewWidth = nativePayload.optInt("preview_width", 0)
                    val previewHeight = nativePayload.optInt("preview_height", 0)
                    if (width <= 0 || height <= 0) {
                        nativePayload.put("status", "error")
                        nativePayload.put("error", "RGBA dimensions missing")
                        variantPayloads.put(nativePayload)
                        continue
                    }
                    updateProcessingTelemetry(
                        "exporting",
                        "raw_compare_${variant.label}_jpeg_export",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = variant.mergeMode.wireName,
                        comparisonCount = variants.size,
                        comparisonLabels = labelText,
                        error = "",
                    )
                    val outputRotationDegrees = processedJpegRotationDegrees()
                    val exifMetadata = processedExifMetadata(manifestPath)
                    compressRgbaToJpeg(outputRgba, width, height, outputJpeg, RAW_FINAL_JPEG_QUALITY, outputRotationDegrees, exifMetadata)
                    if (PROCESSED_PREVIEW_ENABLED && previewWidth > 0 && previewHeight > 0) {
                        compressRgbaToJpeg(previewRgba, previewWidth, previewHeight, previewJpeg, PROCESSED_PREVIEW_JPEG_QUALITY)
                    }
                    updateProcessingTelemetry(
                        "exporting",
                        "raw_compare_${variant.label}_gallery_export",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = variant.mergeMode.wireName,
                        comparisonCount = variants.size,
                        comparisonLabels = labelText,
                        error = "",
                    )
                    val galleryUri = publishJpegToGallery(outputJpeg, outputJpeg.name).toString()
                    val result = ProcessedBurstResult(
                        burstId = burstId,
                        outputPath = outputJpeg.absolutePath,
                        previewPath = if (PROCESSED_PREVIEW_ENABLED) previewJpeg.absolutePath else "",
                        galleryUri = galleryUri,
                        referenceFrame = nativePayload.optInt("reference_frame", -1),
                        usedFrames = nativePayload.optInt("used_frames", 0),
                        rejectedFrames = nativePayload.optInt("rejected_frames", 0),
                    )
                    nativePayload
                        .put("output_path", result.outputPath)
                        .put("preview_path", result.previewPath)
                        .put("gallery_uri", result.galleryUri)
                        .put("output_orientation_degrees", outputRotationDegrees)
                        .put("raw_quality_mode", nativePayload.optString("raw_quality_mode", qualityMode.wireName))
                        .put("raw_demosaic_mode", nativePayload.optString("raw_demosaic_mode", demosaicMode.wireName))
                        .put("raw_merge_mode", nativePayload.optString("raw_merge_mode", variant.mergeMode.wireName))
                        .put("style_profile", nativePayload.optString("style_profile", (variant.renderStyle ?: renderStyle).wireName))
                    variantPayloads.put(nativePayload)
                    if (variant.label == "neutral") {
                        finalPayload = nativePayload
                        finalResult = result
                    }
                }
                val okCount = (0 until variantPayloads.length()).count {
                    variantPayloads.optJSONObject(it)?.optString("status") == "ok"
                }
                val summaryPayload = JSONObject()
                    .put("status", if (okCount > 0) "ok" else "error")
                    .put("mode", "raw_comparison")
                    .put("burst_id", burstId)
                    .put("comparison_count", variants.size)
                    .put("comparison_ok_count", okCount)
                    .put("comparison_labels", labelText)
                    .put("raw_quality_mode", qualityMode.wireName)
                    .put("raw_demosaic_mode", demosaicMode.wireName)
                    .put("style_profile", renderStyle.wireName)
                    .put("variants", variantPayloads)
                writeProcessingManifest(outputDir, summaryPayload)
                if (okCount <= 0 || finalPayload == null || finalResult == null) {
                    updateProcessingTelemetry(
                        status = "error",
                        stage = "raw_comparison",
                        burstId = burstId,
                        sourceFormat = "RAW_SENSOR",
                        renderMode = "raw_comparison",
                        comparisonCount = variants.size,
                        comparisonLabels = labelText,
                        error = "all RAW comparison variants failed",
                    )
                    return@execute
                }
                val payload = finalPayload
                val result = finalResult
                updateProcessingTelemetry(
                    status = "done",
                    stage = "raw_comparison_export",
                    burstId = result.burstId,
                    outputPath = result.outputPath,
                    previewPath = result.previewPath,
                    galleryUri = result.galleryUri,
                    referenceFrame = result.referenceFrame,
                    usedFrames = result.usedFrames,
                    rejectedFrames = result.rejectedFrames,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = "raw_comparison",
                    toneMapExposure = payload.optFiniteDouble("tone_map_exposure"),
                    toneMapP50 = payload.optFiniteDouble("tone_map_p50"),
                    toneMapP95 = payload.optFiniteDouble("tone_map_p95"),
                    toneMapP99 = payload.optFiniteDouble("tone_map_p99"),
                    toneMapHighlightRolloff = payload.optFiniteDouble("tone_map_highlight_rolloff"),
                    toneMapShadowLift = payload.optFiniteDouble("tone_map_shadow_lift"),
                    rawColorGainsUsable = payload.optNullableBoolean("raw_color_gains_usable"),
                    rawColorTransformUsable = payload.optNullableBoolean("raw_color_transform_usable"),
                    rawColorMatrixMode = payload.optString("raw_color_matrix_mode", ""),
                    rawColorGainMode = payload.optString("raw_color_gain_mode", ""),
                    rawLensShadingMode = payload.optString("raw_lens_shading_mode", ""),
                    rawLensShadingMapUsed = payload.optNullableBoolean("raw_lens_shading_map_used"),
                    rawRequestedMergeMode = payload.optString("raw_requested_merge_mode", ""),
                    rawQualityVerdict = payload.optString("raw_quality_verdict", ""),
                    rawQualityFallback = payload.optString("raw_quality_fallback", ""),
                    rawRequestedShadowPurpleRatioAfter = payload.optFiniteDouble("raw_requested_shadow_purple_ratio_after"),
                    rawArtifactGuard = payload.optString("raw_artifact_guard", ""),
                    rawShadowPurpleRatioBefore = payload.optFiniteDouble("raw_shadow_purple_ratio_before"),
                    rawShadowPurpleRatioAfter = payload.optFiniteDouble("raw_shadow_purple_ratio_after"),
                    rawShadowPurpleSuppressedPixels = if (payload.has("raw_shadow_purple_suppressed_pixels")) payload.optLong("raw_shadow_purple_suppressed_pixels") else null,
                    nativeTiming = payload.optJSONObject("native_timing_ms"),
                    mergeCount = payload.optNullableInt("merge_count"),
                    mergeRejected = payload.optNullableInt("merge_rejected"),
                    sharpnessRejected = payload.optNullableInt("sharpness_rejected"),
                    exposureRejected = payload.optNullableInt("exposure_rejected"),
                    alignmentFailures = payload.optNullableInt("alignment_failures"),
                    motionRejectedSamples = if (payload.has("motion_rejected_samples")) payload.optLong("motion_rejected_samples") else null,
                    motionTotalSamples = if (payload.has("motion_total_samples")) payload.optLong("motion_total_samples") else null,
                    comparisonCount = variants.size,
                    comparisonLabels = labelText,
                    exposureConsistent = payload.optNullableBoolean("exposure_consistent"),
                    error = "",
                )
            } catch (exc: Throwable) {
                updateProcessingTelemetry(
                    status = "error",
                    stage = if (processingCurrentStage.isBlank()) "raw_comparison" else processingCurrentStage,
                    burstId = burstId,
                    sourceFormat = "RAW_SENSOR",
                    renderMode = "raw_comparison",
                    comparisonCount = variants.size,
                    comparisonLabels = labelText,
                    error = exc.message ?: exc.javaClass.simpleName,
                )
            }
        }
    }

    private fun compressRgbaToJpeg(
        rgbaPath: File,
        width: Int,
        height: Int,
        jpegPath: File,
        quality: Int,
        rotationDegrees: Int = 0,
        exifMetadata: JSONObject? = null,
    ) {
        val expectedBytes = width * height * 4
        val bytes = rgbaPath.readBytes()
        if (bytes.size < expectedBytes) {
            throw IllegalStateException("JPEG compression failure: RGBA file is too small")
        }
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        bitmap.copyPixelsFromBuffer(ByteBuffer.wrap(bytes, 0, expectedBytes))
        val rotated = rotateBitmapForJpeg(bitmap, rotationDegrees)
        try {
            FileOutputStream(jpegPath).use { out ->
                if (!rotated.compress(Bitmap.CompressFormat.JPEG, quality.coerceIn(1, 100), out)) {
                    throw IllegalStateException("JPEG compression failure")
                }
            }
            writeProcessedJpegExif(jpegPath, rotated.width, rotated.height, exifMetadata)
        } finally {
            if (rotated !== bitmap) {
                rotated.recycle()
            }
            bitmap.recycle()
        }
    }

    private fun processedExifMetadata(manifestPath: String): JSONObject? {
        return try {
            val manifest = JSONObject(File(manifestPath).readText(Charsets.UTF_8))
            val frames = manifest.optJSONArray("frames") ?: return null
            if (frames.length() <= 0) return null
            val first = frames.optJSONObject(0) ?: return null
            val metadataPath = first.optString("metadata_path", "")
            if (metadataPath.isBlank()) return null
            JSONObject(File(metadataPath).readText(Charsets.UTF_8))
        } catch (_: Throwable) {
            null
        }
    }

    private fun writeProcessedJpegExif(jpegPath: File, width: Int, height: Int, metadata: JSONObject? = null) {
        try {
            val now = SimpleDateFormat("yyyy:MM:dd HH:mm:ss", Locale.US).format(Date())
            ExifInterface(jpegPath.absolutePath).apply {
                setAttribute(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL.toString())
                setAttribute(ExifInterface.TAG_DATETIME, now)
                setAttribute(ExifInterface.TAG_DATETIME_ORIGINAL, now)
                setAttribute(ExifInterface.TAG_MAKE, Build.MANUFACTURER ?: "Android")
                setAttribute(ExifInterface.TAG_MODEL, Build.MODEL ?: "Android")
                setAttribute(ExifInterface.TAG_SOFTWARE, "Luvatrix Camera RAW pipeline")
                setAttribute(ExifInterface.TAG_IMAGE_WIDTH, width.toString())
                setAttribute(ExifInterface.TAG_IMAGE_LENGTH, height.toString())
                applyCaptureExifMetadata(this, metadata)
                saveAttributes()
            }
        } catch (exc: Throwable) {
            Log.w("LuvatrixCamera", "processed JPEG EXIF write failed: ${exc.message ?: exc.javaClass.simpleName}")
        }
    }

    private fun applyCaptureExifMetadata(exif: ExifInterface, metadata: JSONObject?) {
        if (metadata == null) return
        val iso = metadata.optInt("sensor_sensitivity_iso", metadata.optInt("actual_iso", 0))
        if (iso > 0) {
            exif.setAttribute(ExifInterface.TAG_ISO_SPEED_RATINGS, iso.toString())
        }
        val exposureNs = metadata.optLong("sensor_exposure_time_ns", metadata.optLong("actual_exposure_time_ns", 0L))
        if (exposureNs > 0L) {
            exif.setAttribute(ExifInterface.TAG_EXPOSURE_TIME, "%.9f".format(Locale.US, exposureNs.toDouble() / 1_000_000_000.0))
        }
        val aperture = metadata.optDouble("lens_aperture", Double.NaN)
        if (java.lang.Double.isFinite(aperture) && aperture > 0.0) {
            exif.setAttribute(ExifInterface.TAG_F_NUMBER, "%.2f".format(Locale.US, aperture))
        }
        val focal = metadata.optDouble("lens_focal_length_mm", Double.NaN)
        if (java.lang.Double.isFinite(focal) && focal > 0.0) {
            exif.setAttribute(ExifInterface.TAG_FOCAL_LENGTH, exifRational(focal))
        }
    }

    private fun exifRational(value: Double): String {
        val denominator = 1000
        val numerator = (value * denominator.toDouble()).roundToInt().coerceAtLeast(1)
        return "$numerator/$denominator"
    }

    private fun rotateBitmapForJpeg(bitmap: Bitmap, rotationDegrees: Int): Bitmap {
        val normalized = ((rotationDegrees % 360) + 360) % 360
        if (normalized == 0) return bitmap
        val matrix = Matrix().apply { postRotate(normalized.toFloat()) }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    }

    private fun processedJpegRotationDegrees(): Int {
        val cameraId = primaryCameraId ?: return 0
        return try {
            val chars = cameraManager.getCameraCharacteristics(cameraId)
            rawToDisplayRotationDegrees(
                chars,
                chars.get(CameraCharacteristics.SENSOR_ORIENTATION),
                displayRotationDegrees(),
            ) ?: 0
        } catch (_: Throwable) {
            0
        }
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

    private fun publishJpegToGallery(jpegPath: File, displayName: String): Uri {
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/Luvatrix Camera")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("MediaStore insert failure")
        try {
            resolver.openOutputStream(uri)?.use { out ->
                FileInputStream(jpegPath).use { input -> input.copyTo(out) }
            } ?: throw IllegalStateException("MediaStore copy failure")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val done = ContentValues().apply {
                    put(MediaStore.Images.Media.IS_PENDING, 0)
                }
                resolver.update(uri, done, null, null)
            }
            return uri
        } catch (exc: Throwable) {
            resolver.delete(uri, null, null)
            throw exc
        }
    }

    private fun writeProcessingManifest(outputDir: File, payload: JSONObject) {
        outputDir.mkdirs()
        File(outputDir, "processing_manifest.json").writeText(payload.toString(2), Charsets.UTF_8)
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
            .put("raw_quality_mode", rawProcessingQualityMode.wireName)
            .put("render_max_edge", rawProcessingQualityMode.renderMaxEdge)
            .put("raw_demosaic_mode", rawDemosaicMode.wireName)
            .put("raw_merge_mode", rawMergeMode.wireName)
            .put("style_profile", rawRenderStyle.wireName)
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

    private fun updateBurstTelemetry(
        status: String,
        error: String = "",
        burstId: String = burstLastId,
        path: String = burstLastPath,
        requestedFrames: Int = burstRequestedFrames,
        capturedFrames: Int = burstCapturedFrames,
        manifestPath: String = burstLastManifestPath,
        writeMs: Double = burstLastWriteMs,
    ) {
        burstStatus = status
        burstLastError = error
        burstLastId = burstId
        burstLastPath = path
        burstRequestedFrames = requestedFrames
        burstCapturedFrames = capturedFrames
        burstLastManifestPath = manifestPath
        burstLastWriteMs = writeMs
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
            try {
                builder.set(CaptureRequest.STATISTICS_LENS_SHADING_MAP_MODE, CaptureRequest.STATISTICS_LENS_SHADING_MAP_MODE_ON)
            } catch (_: Throwable) {
                // Optional device metadata; RAW processing falls back when unavailable.
            }
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
        try {
            builder.set(CaptureRequest.STATISTICS_LENS_SHADING_MAP_MODE, CaptureRequest.STATISTICS_LENS_SHADING_MAP_MODE_ON)
        } catch (_: Throwable) {
            // Optional device metadata; RAW processing falls back when unavailable.
        }
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
        val profile = profileFor(id)
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
            .put("capability_profile", capabilityProfileJson(profile))
            .put(
                "capabilities",
                JSONObject()
                    .put("raw", profile.supportsRaw)
                    .put("private_preview", profile.supportsPrivatePreview)
                    .put("max_burst", profile.maxBurstTargets)
                    .put("hardware_level", profile.hardwareLevel),
            )
            .put("resolution_probe", resolutionProbeJson(id, facingName(chars.get(CameraCharacteristics.LENS_FACING)), chars, map, caps))
            .put("raw_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW))
            .put("monochrome_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME))
            .put("manual_sensor_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR))
            .put("manual_post_processing_supported", caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING))
    }

    private fun profileFor(cameraId: String): CameraCapabilityProfile {
        return capabilityProfiles.getOrPut(cameraId) { buildCapabilityProfile(cameraId) }
    }

    private fun buildCapabilityProfile(cameraId: String): CameraCapabilityProfile {
        val chars = cameraManager.getCameraCharacteristics(cameraId)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val caps = chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)?.toSet().orEmpty()
        val rawSizes = map?.getOutputSizes(ImageFormat.RAW_SENSOR)?.toList().orEmpty()
        val yuvSizes = map?.getOutputSizes(ImageFormat.YUV_420_888)?.toList().orEmpty()
        val privateSizes = map?.getOutputSizes(ImageFormat.PRIVATE)?.toList().orEmpty()
        val black = chars.get(CameraCharacteristics.SENSOR_BLACK_LEVEL_PATTERN)
        val blackPattern = black?.let {
            listOf(
                it.getOffsetForIndex(0, 0),
                it.getOffsetForIndex(1, 0),
                it.getOffsetForIndex(0, 1),
                it.getOffsetForIndex(1, 1),
            )
        }
        val supportsRaw = caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW) && rawSizes.isNotEmpty()
        val supportsYuvReprocess = caps.contains(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING)
        val supportsPrivatePreview = privateSizes.isNotEmpty()
        val streamCombos = streamCombinationsFor(supportsRaw, supportsYuvReprocess, supportsPrivatePreview, rawSizes, yuvSizes, privateSizes)
        return CameraCapabilityProfile(
            cameraId = cameraId,
            hardwareLevel = hardwareLevelName(chars.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)),
            supportsRaw = supportsRaw,
            supportsYuvReprocess = supportsYuvReprocess,
            supportsPrivatePreview = supportsPrivatePreview,
            rawSizes = rawSizes,
            yuvSizes = yuvSizes,
            privateSizes = privateSizes,
            maxBurstTargets = maxBurstTargets(chars),
            streamCombinations = streamCombos,
            sensorInfo = SensorInfo(
                activeArray = chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE),
                pixelArraySize = chars.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE),
                orientationDegrees = chars.get(CameraCharacteristics.SENSOR_ORIENTATION),
                timestampSource = chars.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE),
            ),
            lensInfo = LensInfo(
                facing = facingName(chars.get(CameraCharacteristics.LENS_FACING)),
                focalLengthsMm = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                    ?.map { it.toDouble() }
                    .orEmpty(),
                apertures = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_APERTURES)
                    ?.map { it.toDouble() }
                    .orEmpty(),
                minimumFocusDistanceDiopters = chars.get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE),
            ),
            colorInfo = ColorInfo(
                colorFilterArrangement = colorFilterName(chars.get(CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT)),
                whiteLevel = chars.get(CameraCharacteristics.SENSOR_INFO_WHITE_LEVEL),
                blackLevelPattern = blackPattern,
            ),
        )
    }

    private fun streamCombinationsFor(
        supportsRaw: Boolean,
        supportsYuvReprocess: Boolean,
        supportsPrivatePreview: Boolean,
        rawSizes: List<Size>,
        yuvSizes: List<Size>,
        privateSizes: List<Size>,
    ): List<StreamCombo> {
        val combos = mutableListOf<StreamCombo>()
        largestSize(privateSizes)?.let { size ->
            if (supportsPrivatePreview) {
                combos.add(StreamCombo("preview_private", listOf(StreamOutput("PRIVATE", size.width, size.height)), "live_preview"))
            }
        }
        largestSize(yuvSizes)?.let { size ->
            combos.add(StreamCombo("preview_yuv", listOf(StreamOutput("YUV_420_888", size.width, size.height)), "preview_fallback"))
        }
        largestSize(rawSizes)?.let { size ->
            if (supportsRaw) {
                combos.add(StreamCombo("still_raw", listOf(StreamOutput("RAW_SENSOR", size.width, size.height)), "still_capture"))
            }
        }
        if (supportsYuvReprocess) {
            largestSize(yuvSizes)?.let { size ->
                combos.add(StreamCombo("still_yuv_reprocess", listOf(StreamOutput("YUV_420_888", size.width, size.height)), "still_capture"))
            }
        }
        return combos
    }

    private fun largestSize(sizes: List<Size>): Size? {
        return sizes.maxWithOrNull(compareBy<Size> { it.width.toLong() * it.height.toLong() }.thenBy { it.width })
    }

    private fun maxBurstTargets(chars: CameraCharacteristics): Int {
        // Camera2 documents this capability family as REQUEST_MAX_NUM_OUTPUT_STREAMS,
        // while the public SDK exposes the usable values as the RAW/PROC/STALLING keys below.
        val raw = chars.get(CameraCharacteristics.REQUEST_MAX_NUM_OUTPUT_RAW) ?: 0
        val processed = chars.get(CameraCharacteristics.REQUEST_MAX_NUM_OUTPUT_PROC) ?: 0
        val processedStalling = chars.get(CameraCharacteristics.REQUEST_MAX_NUM_OUTPUT_PROC_STALLING) ?: 0
        return maxOf(raw + processed + processedStalling, 1)
    }

    private fun capabilityProfileJson(profile: CameraCapabilityProfile): JSONObject {
        return JSONObject()
            .put("camera_id", profile.cameraId)
            .put("hardware_level", profile.hardwareLevel)
            .put("supports_raw", profile.supportsRaw)
            .put("supports_yuv_reprocess", profile.supportsYuvReprocess)
            .put("supports_private_preview", profile.supportsPrivatePreview)
            .put("raw_sizes", sizesJson(profile.rawSizes))
            .put("yuv_sizes", sizesJson(profile.yuvSizes))
            .put("private_sizes", sizesJson(profile.privateSizes))
            .put("max_burst_targets", profile.maxBurstTargets)
            .put("stream_combinations", streamCombinationsJson(profile.streamCombinations))
            .put("sensor_info", sensorInfoJson(profile.sensorInfo))
            .put("lens_info", lensInfoJson(profile.lensInfo))
            .put("color_info", colorInfoJson(profile.colorInfo))
    }

    private fun streamCombinationsJson(combos: List<StreamCombo>): JSONArray {
        val out = JSONArray()
        for (combo in combos) {
            val outputs = JSONArray()
            for (output in combo.outputs) {
                outputs.put(
                    JSONObject()
                        .put("format", output.format)
                        .put("width", output.width)
                        .put("height", output.height)
                        .put("megapixels", megapixels(output.width, output.height)),
                )
            }
            out.put(
                JSONObject()
                    .put("name", combo.name)
                    .put("purpose", combo.purpose)
                    .put("outputs", outputs),
            )
        }
        return out
    }

    private fun sensorInfoJson(info: SensorInfo): JSONObject {
        return JSONObject()
            .put("active_array", rectJson(info.activeArray))
            .put("pixel_array_size", sizeJson(info.pixelArraySize))
            .put("orientation_degrees", info.orientationDegrees ?: JSONObject.NULL)
            .put("timestamp_source", info.timestampSource ?: JSONObject.NULL)
    }

    private fun lensInfoJson(info: LensInfo): JSONObject {
        return JSONObject()
            .put("facing", info.facing)
            .put("focal_lengths_mm", JSONArray(info.focalLengthsMm))
            .put("apertures", JSONArray(info.apertures))
            .put("minimum_focus_distance_diopters", info.minimumFocusDistanceDiopters ?: JSONObject.NULL)
    }

    private fun colorInfoJson(info: ColorInfo): JSONObject {
        return JSONObject()
            .put("color_filter_arrangement", info.colorFilterArrangement)
            .put("white_level", info.whiteLevel ?: JSONObject.NULL)
            .put("black_level_pattern", info.blackLevelPattern?.let { JSONArray(it) } ?: JSONObject.NULL)
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

    private class BurstPackageWriter(
        private val rootDir: File,
        private val burstId: String,
        private val cameraId: String,
        private val format: String,
        private val requestedFrameCount: Int,
    ) {
        fun burstDir(): File {
            return File(rootDir, burstId).apply { mkdirs() }
        }

        fun writeYuvFrame(index: Int, image: Image, metadata: JSONObject): BurstFrameRecord {
            val dir = burstDir()
            val frame = File(dir, "frame_${indexName(index)}.yuv")
            val sidecar = File(dir, "metadata_${indexName(index)}.json")
            val planes = JSONArray()
            FileOutputStream(frame).use { out ->
                val names = listOf("Y", "U", "V")
                for ((planeIndex, plane) in image.planes.withIndex()) {
                    val bytes = planeBytes(plane.buffer)
                    out.write(bytes)
                    planes.put(
                        JSONObject()
                            .put("name", names.getOrElse(planeIndex) { "P$planeIndex" })
                            .put("row_stride", plane.rowStride)
                            .put("pixel_stride", plane.pixelStride)
                            .put("byte_count", bytes.size),
                    )
                }
            }
            val fullMetadata = JSONObject(metadata.toString())
                .put("burst_id", burstId)
                .put("camera_id", cameraId)
                .put("format", "YUV_420_888")
                .put("width", image.width)
                .put("height", image.height)
                .put("timestamp_ns", image.timestamp)
                .put("planes", planes)
            sidecar.writeText(fullMetadata.toString(2), Charsets.UTF_8)
            return BurstFrameRecord(index, frame.absolutePath, sidecar.absolutePath, image.timestamp, "YUV_420_888", image.width, image.height)
        }

        fun writeRawFrame(
            index: Int,
            image: Image,
            result: TotalCaptureResult,
            chars: CameraCharacteristics,
        ): BurstFrameRecord {
            val dir = burstDir()
            val frame = File(dir, "frame_${indexName(index)}.dng")
            val raw16 = File(dir, "frame_${indexName(index)}.raw16")
            val sidecar = File(dir, "metadata_${indexName(index)}.json")
            val plane = image.planes.firstOrNull()
            val rawBytes = if (plane != null) planeBytes(plane.buffer) else ByteArray(0)
            FileOutputStream(raw16).use { out ->
                out.write(rawBytes)
            }
            FileOutputStream(frame).use { out ->
                DngCreator(chars, result).use { dngCreator ->
                    dngCreator.writeImage(out, image)
                }
            }
            val cfa = chars.get(CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT)
            val cfaName = rawColorFilterName(cfa)
            val rawSharpnessScore = rawGreenSharpnessScore(
                rawBytes,
                image.width,
                image.height,
                plane?.rowStride ?: image.width * 2,
                plane?.pixelStride ?: 2,
                cfaName,
            )
            val gains = result.get(CaptureResult.COLOR_CORRECTION_GAINS)
            val transform = result.get(CaptureResult.COLOR_CORRECTION_TRANSFORM)
            val lensShadingMap = result.get(CaptureResult.STATISTICS_LENS_SHADING_CORRECTION_MAP)
            val sensitivityIso = result.get(CaptureResult.SENSOR_SENSITIVITY)
            val exposureTimeNs = result.get(CaptureResult.SENSOR_EXPOSURE_TIME)
            val frameDurationNs = result.get(CaptureResult.SENSOR_FRAME_DURATION)
            val aeState = result.get(CaptureResult.CONTROL_AE_STATE)
            val awbState = result.get(CaptureResult.CONTROL_AWB_STATE)
            val afState = result.get(CaptureResult.CONTROL_AF_STATE)
            val metadata = JSONObject()
                .put("burst_id", burstId)
                .put("camera_id", cameraId)
                .put("format", "RAW_SENSOR")
                .put("dng_path", frame.absolutePath)
                .put("raw16_path", raw16.absolutePath)
                .put("raw16_byte_count", rawBytes.size)
                .put("raw_sharpness_score", rawSharpnessScore)
                .put("raw_sharpness_method", "green_proxy_sparse_64")
                .put("row_stride", plane?.rowStride ?: JSONObject.NULL)
                .put("pixel_stride", plane?.pixelStride ?: JSONObject.NULL)
                .put("bits_per_sample", 16)
                .put("width", image.width)
                .put("height", image.height)
                .put("timestamp_ns", image.timestamp)
                .put("sensor_sensitivity_iso", sensitivityIso ?: JSONObject.NULL)
                .put("sensor_exposure_time_ns", exposureTimeNs ?: JSONObject.NULL)
                .put("sensor_frame_duration_ns", frameDurationNs ?: JSONObject.NULL)
                .put("ae_state", aeState ?: JSONObject.NULL)
                .put("awb_state", awbState ?: JSONObject.NULL)
                .put("af_state", afState ?: JSONObject.NULL)
                .put("ae_locked_result", aeState == CaptureResult.CONTROL_AE_STATE_LOCKED)
                .put("awb_locked_result", awbState == CaptureResult.CONTROL_AWB_STATE_LOCKED)
                .put(
                    "af_locked_result",
                    afState == CaptureResult.CONTROL_AF_STATE_FOCUSED_LOCKED ||
                        afState == CaptureResult.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED,
                )
                .put("black_level_pattern", blackLevelPatternJson(chars))
                .put("white_level", chars.get(CameraCharacteristics.SENSOR_INFO_WHITE_LEVEL) ?: JSONObject.NULL)
                .put("color_filter_arrangement", cfaName)
                .put("color_correction_gains", colorCorrectionGainsJson(gains))
                .put("color_correction_transform", colorCorrectionTransformJson(transform))
                .put("lens_shading_available", lensShadingMap != null)
                .put("lens_shading_map", lensShadingMapJson(lensShadingMap))
            sidecar.writeText(metadata.toString(2), Charsets.UTF_8)
            return BurstFrameRecord(
                index,
                frame.absolutePath,
                sidecar.absolutePath,
                image.timestamp,
                "RAW_SENSOR",
                image.width,
                image.height,
                raw16.absolutePath,
                "raw_capture",
                sensitivityIso,
                exposureTimeNs,
                frameDurationNs,
            )
        }

        fun writeManifest(manifest: BurstManifest): File {
            val out = File(burstDir(), "burst_manifest.json")
            out.writeText(manifestJson(manifest).toString(2), Charsets.UTF_8)
            return out
        }

        private fun manifestJson(manifest: BurstManifest): JSONObject {
            val frames = JSONArray()
            for (frame in manifest.frames) {
                frames.put(
                    JSONObject()
                        .put("index", frame.index)
                        .put("frame_path", frame.framePath)
                        .put("metadata_path", frame.metadataPath)
                        .put("timestamp_ns", frame.timestampNs)
                        .put("format", frame.format)
                        .put("width", frame.width)
                        .put("height", frame.height)
                        .put("raw16_path", frame.raw16Path)
                        .put("artifact_role", frame.artifactRole)
                        .put("sensor_sensitivity_iso", frame.sensorSensitivityIso ?: JSONObject.NULL)
                        .put("sensor_exposure_time_ns", frame.sensorExposureTimeNs ?: JSONObject.NULL)
                        .put("sensor_frame_duration_ns", frame.sensorFrameDurationNs ?: JSONObject.NULL),
                )
            }
            val isoValues = manifest.frames.mapNotNull { it.sensorSensitivityIso }
            val exposureValues = manifest.frames.mapNotNull { it.sensorExposureTimeNs }
            return JSONObject()
                .put("burst_id", manifest.burstId)
                .put("camera_id", manifest.cameraId)
                .put("format", manifest.format)
                .put("frame_count", manifest.frameCount)
                .put("requested_frame_count", manifest.requestedFrameCount)
                .put("exposure_strategy", manifest.exposureStrategy)
                .put("iso", manifest.iso ?: JSONObject.NULL)
                .put("exposure_time_ns", manifest.exposureTimeNs ?: JSONObject.NULL)
                .put("awb_locked", manifest.awbLocked)
                .put("ae_locked", manifest.aeLocked)
                .put("af_locked", manifest.afLocked)
                .put("gyro_available", manifest.gyroAvailable)
                .put("exposure_consistency", exposureConsistencyJson(isoValues, exposureValues))
                .put("writer_format", format)
                .put("writer_requested_frame_count", requestedFrameCount)
                .put("frames", frames)
        }

        private fun exposureConsistencyJson(isoValues: List<Int>, exposureValues: List<Long>): JSONObject {
            val isoMin = isoValues.minOrNull()
            val isoMax = isoValues.maxOrNull()
            val exposureMin = exposureValues.minOrNull()
            val exposureMax = exposureValues.maxOrNull()
            val isoStable = isoMin != null && isoMax != null && isoMin == isoMax
            val exposureStable = exposureMin != null && exposureMax != null && exposureMin == exposureMax
            return JSONObject()
                .put("iso_sample_count", isoValues.size)
                .put("exposure_sample_count", exposureValues.size)
                .put("iso_min", isoMin ?: JSONObject.NULL)
                .put("iso_max", isoMax ?: JSONObject.NULL)
                .put("exposure_time_min_ns", exposureMin ?: JSONObject.NULL)
                .put("exposure_time_max_ns", exposureMax ?: JSONObject.NULL)
                .put("iso_stable", isoStable)
                .put("exposure_time_stable", exposureStable)
                .put("stable", isoStable && exposureStable)
        }

        private fun indexName(index: Int): String {
            return index.toString().padStart(3, '0')
        }

        private fun blackLevelPatternJson(chars: CameraCharacteristics): JSONArray {
            val pattern = chars.get(CameraCharacteristics.SENSOR_BLACK_LEVEL_PATTERN) ?: return JSONArray()
            val values = IntArray(4)
            return try {
                pattern.copyTo(values, 0)
                JSONArray(values.toList())
            } catch (_: Throwable) {
                JSONArray()
            }
        }

        private fun rawColorFilterName(value: Int?): String {
            return when (value) {
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_RGGB -> "RGGB"
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_GRBG -> "GRBG"
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_GBRG -> "GBRG"
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_BGGR -> "BGGR"
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_RGB -> "RGB"
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_MONO -> "MONO"
                CameraCharacteristics.SENSOR_INFO_COLOR_FILTER_ARRANGEMENT_NIR -> "NIR"
                null -> "UNKNOWN"
                else -> "UNKNOWN_$value"
            }
        }

        private fun colorCorrectionGainsJson(gains: android.hardware.camera2.params.RggbChannelVector?): JSONArray {
            if (gains == null) return JSONArray()
            return JSONArray(
                listOf(
                    gains.red.toDouble(),
                    gains.greenEven.toDouble(),
                    gains.greenOdd.toDouble(),
                    gains.blue.toDouble(),
                )
            )
        }

        private fun colorCorrectionTransformJson(transform: android.hardware.camera2.params.ColorSpaceTransform?): JSONArray {
            if (transform == null) return JSONArray()
            val out = JSONArray()
            return try {
                for (row in 0 until 3) {
                    for (col in 0 until 3) {
                        val value = transform.getElement(col, row)
                        out.put(value.numerator.toDouble() / value.denominator.toDouble())
                    }
                }
                out
            } catch (_: Throwable) {
                JSONArray()
            }
        }

        private fun lensShadingMapJson(map: LensShadingMap?): JSONObject {
            if (map == null) {
                return JSONObject()
                    .put("available", false)
                    .put("columns", 0)
                    .put("rows", 0)
                    .put("channel_order", "R,GE,GO,B")
                    .put("values", JSONArray())
            }
            return try {
                val values = JSONArray()
                for (row in 0 until map.rowCount) {
                    for (col in 0 until map.columnCount) {
                        values.put(map.getGainFactor(RggbChannelVector.RED, col, row).toDouble())
                        values.put(map.getGainFactor(RggbChannelVector.GREEN_EVEN, col, row).toDouble())
                        values.put(map.getGainFactor(RggbChannelVector.GREEN_ODD, col, row).toDouble())
                        values.put(map.getGainFactor(RggbChannelVector.BLUE, col, row).toDouble())
                    }
                }
                JSONObject()
                    .put("available", true)
                    .put("columns", map.columnCount)
                    .put("rows", map.rowCount)
                    .put("channel_order", "R,GE,GO,B")
                    .put("values", values)
            } catch (_: Throwable) {
                JSONObject()
                    .put("available", false)
                    .put("columns", 0)
                    .put("rows", 0)
                    .put("channel_order", "R,GE,GO,B")
                    .put("values", JSONArray())
            }
        }

        private fun rawGreenSharpnessScore(
            bytes: ByteArray,
            width: Int,
            height: Int,
            rowStride: Int,
            pixelStride: Int,
            cfa: String,
        ): Double {
            if (bytes.isEmpty() || width <= 1 || height <= 1 || rowStride <= 0 || pixelStride <= 0) return 0.0
            val stepX = maxOf(1, width / 64)
            val stepY = maxOf(1, height / 64)
            var total = 0.0
            var count = 0
            var row = 0
            while (row < height - stepY) {
                var col = 0
                while (col < width - stepX) {
                    val center = rawGreenProxy(bytes, width, height, rowStride, pixelStride, cfa, row, col)
                    total += kotlin.math.abs(center - rawGreenProxy(bytes, width, height, rowStride, pixelStride, cfa, row, col + stepX))
                    total += kotlin.math.abs(center - rawGreenProxy(bytes, width, height, rowStride, pixelStride, cfa, row + stepY, col))
                    count += 2
                    col += stepX
                }
                row += stepY
            }
            return if (count > 0) total / count.toDouble() else 0.0
        }

        private fun rawGreenProxy(
            bytes: ByteArray,
            width: Int,
            height: Int,
            rowStride: Int,
            pixelStride: Int,
            cfa: String,
            row: Int,
            col: Int,
        ): Double {
            if (rawColorAt(cfa, row, col) == 'G') return raw16NormalizedProxy(bytes, width, height, rowStride, pixelStride, row, col)
            var total = 0.0
            var count = 0
            val offsets = intArrayOf(0, -1, 0, 1, -1, 0, 1, 0)
            var i = 0
            while (i < offsets.size) {
                val yy = row + offsets[i]
                val xx = col + offsets[i + 1]
                if (rawColorAt(cfa, yy, xx) == 'G') {
                    total += raw16NormalizedProxy(bytes, width, height, rowStride, pixelStride, yy, xx)
                    count += 1
                }
                i += 2
            }
            return if (count > 0) total / count.toDouble() else raw16NormalizedProxy(bytes, width, height, rowStride, pixelStride, row, col)
        }

        private fun rawColorAt(cfa: String, row: Int, col: Int): Char {
            val evenRow = (row and 1) == 0
            val evenCol = (col and 1) == 0
            return when (cfa) {
                "RGGB" -> if (evenRow) { if (evenCol) 'R' else 'G' } else { if (evenCol) 'G' else 'B' }
                "GRBG" -> if (evenRow) { if (evenCol) 'G' else 'R' } else { if (evenCol) 'B' else 'G' }
                "GBRG" -> if (evenRow) { if (evenCol) 'G' else 'B' } else { if (evenCol) 'R' else 'G' }
                "BGGR" -> if (evenRow) { if (evenCol) 'B' else 'G' } else { if (evenCol) 'G' else 'R' }
                else -> '?'
            }
        }

        private fun raw16NormalizedProxy(
            bytes: ByteArray,
            width: Int,
            height: Int,
            rowStride: Int,
            pixelStride: Int,
            row: Int,
            col: Int,
        ): Double {
            val yy = row.coerceIn(0, height - 1)
            val xx = col.coerceIn(0, width - 1)
            val offset = yy * rowStride + xx * pixelStride
            if (offset < 0 || offset + 1 >= bytes.size) return 0.0
            val value = (bytes[offset].toInt() and 0xff) or ((bytes[offset + 1].toInt() and 0xff) shl 8)
            return value.toDouble() / 65535.0
        }

        private fun planeBytes(buffer: ByteBuffer): ByteArray {
            val duplicate = buffer.duplicate()
            val bytes = ByteArray(duplicate.remaining())
            duplicate.get(bytes)
            return bytes
        }
    }

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
        private var pendingYuvBurst: PendingYuvBurst? = null
        private var pendingRawBurst: PendingRawBurst? = null
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
                rawImageReader = ImageReader.newInstance(
                    rawSize.width,
                    rawSize.height,
                    ImageFormat.RAW_SENSOR,
                    RAW_IMAGE_READER_MAX_IMAGES,
                ).apply {
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
                pendingYuvBurst = null
                closePendingRawBurst()
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

        fun captureYuvBurst(handler: Handler, requestedFrames: Int, burstId: String, writer: BurstPackageWriter) {
            if (imageReader == null) {
                updateBurstTelemetry("error", "YUV ImageReader is not available", burstId = burstId, requestedFrames = requestedFrames)
                return
            }
            if (pendingYuvBurst != null) {
                updateBurstTelemetry("error", "YUV burst is already capturing", burstId = burstId, requestedFrames = requestedFrames)
                return
            }
            val pending = PendingYuvBurst(
                burstId = burstId,
                writer = writer,
                requestedFrames = requestedFrames,
                startedAtNs = System.nanoTime(),
                records = mutableListOf(),
            )
            pendingYuvBurst = pending
            ensureYuvBurstSession(handler)
            updateBurstTelemetry(
                "capturing",
                burstId = burstId,
                path = writer.burstDir().absolutePath,
                requestedFrames = requestedFrames,
                capturedFrames = 0,
                manifestPath = "",
            )
            handler.postDelayed({
                val active = pendingYuvBurst
                if (active != null && active.burstId == burstId) {
                    finishYuvBurst(
                        active,
                        if (active.records.isEmpty()) "error" else "partial",
                        "YUV burst timed out after ${YUV_BURST_TIMEOUT_MS}ms captured=${active.records.size}/$requestedFrames",
                    )
                }
            }, YUV_BURST_TIMEOUT_MS)
        }

        fun captureRawBurst(
            handler: Handler,
            requestedFrames: Int,
            burstId: String,
            writer: BurstPackageWriter,
            processingMode: String,
        ) {
            val rawReader = rawImageReader
            val camera = cameraDevice
            val session = captureSession
            if (rawReader == null || rawSize == null) {
                updateBurstTelemetry("error", "RAW_SENSOR is not available for active camera", burstId = burstId, requestedFrames = requestedFrames)
                return
            }
            if (!activeSessionTargets.contains("raw_sensor")) {
                updateBurstTelemetry("error", "RAW_SENSOR is not part of the active preview session", burstId = burstId, requestedFrames = requestedFrames)
                return
            }
            if (camera == null || session == null) {
                updateBurstTelemetry("error", "camera capture session is not ready", burstId = burstId, requestedFrames = requestedFrames)
                return
            }
            if (pendingRawBurst != null) {
                updateBurstTelemetry("error", "RAW burst is already capturing", burstId = burstId, requestedFrames = requestedFrames)
                return
            }
            val pending = PendingRawBurst(
                burstId = burstId,
                writer = writer,
                requestedFrames = requestedFrames,
                startedAtNs = System.nanoTime(),
                processingMode = processingMode,
                records = mutableListOf(),
                pendingRawImagesByTimestamp = LinkedHashMap(),
                pendingRawResultsByTimestamp = LinkedHashMap(),
            )
            pendingRawBurst = pending
            updateBurstTelemetry(
                "capturing",
                burstId = burstId,
                path = writer.burstDir().absolutePath,
                requestedFrames = requestedFrames,
                capturedFrames = 0,
                manifestPath = "",
            )
            try {
                val requests = (0 until requestedFrames).map {
                    camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                        addTarget(rawReader.surface)
                        configureRawCaptureRequest(this, cameraId)
                        set(CaptureRequest.CONTROL_AE_LOCK, true)
                        set(CaptureRequest.CONTROL_AWB_LOCK, true)
                    }.build()
                }
                handler.postDelayed({
                    val active = pendingRawBurst
                    if (active != null && active.burstId == burstId) {
                        finishRawBurst(
                            active,
                            if (active.records.isEmpty()) "error" else "partial",
                            "RAW burst timed out after ${RAW_CAPTURE_TIMEOUT_MS}ms captured=${active.records.size}/$requestedFrames",
                        )
                    }
                }, RAW_CAPTURE_TIMEOUT_MS)
                session.captureBurst(
                    requests,
                    object : CaptureCallback() {
                        override fun onCaptureCompleted(
                            session: CameraCaptureSession,
                            request: CaptureRequest,
                            result: TotalCaptureResult,
                        ) {
                            val timestamp = result.get(CaptureResult.SENSOR_TIMESTAMP) ?: return
                            val active = pendingRawBurst ?: return
                            if (active.burstId != burstId) return
                            active.pendingRawResultsByTimestamp[timestamp] = result
                            maybeWriteRawBurstFrame(active, timestamp)
                        }

                        override fun onCaptureFailed(
                            session: CameraCaptureSession,
                            request: CaptureRequest,
                            failure: CaptureFailure,
                        ) {
                            val active = pendingRawBurst ?: return
                            if (active.burstId == burstId) {
                                finishRawBurst(active, "error", "RAW burst capture failed reason=${failure.reason}")
                            }
                        }
                    },
                    handler,
                )
            } catch (exc: Throwable) {
                finishRawBurst(pending, "error", exc.message ?: exc.javaClass.simpleName)
            }
        }

        private fun ensureYuvBurstSession(handler: Handler) {
            if (activeSessionTargets.contains("yuv_cache") || activePreviewMode == PREVIEW_MODE_CPU_YUV) return
            val camera = cameraDevice ?: return
            val attemptIndex = sessionAttempts().indexOfFirst { it.includeYuvCache }
            if (attemptIndex < 0) return
            try {
                captureSession?.close()
                captureSession = null
                createSessionAttempt(camera, handler, attemptIndex)
            } catch (exc: Throwable) {
                val pending = pendingYuvBurst
                if (pending != null) {
                    finishYuvBurst(pending, "error", exc.message ?: exc.javaClass.simpleName)
                }
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
                .put("raw_diagnostics", rawDiagnosticsJson())
                .put("sensor_orientation", sensorOrientationDegrees)
                .put("last_error", streamError)
        }

        fun rawDiagnosticsJson(): JSONObject {
            val raw = rawSize
            return JSONObject()
                .put("raw_size_available", raw != null)
                .put("raw_reader_active", rawImageReader != null)
                .put("raw_in_active_session", activeSessionTargets.contains("raw_sensor"))
                .put("raw_width", raw?.width ?: 0)
                .put("raw_height", raw?.height ?: 0)
                .put("active_targets", JSONArray(activeSessionTargets))
                .put("preview_target_mode", previewTargetMode)
                .put("active_target_mode", activeSessionTargetMode)
                .put("raw_capture_status", rawCaptureStatus)
                .put("raw_capture_last_error", rawCaptureLastError)
                .put("pending_raw_burst", pendingRawBurst != null)
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
                if (slot == "primary") {
                    collectPendingYuvBurst(image)
                }
            } catch (exc: Throwable) {
                droppedFrames.incrementAndGet()
                streamError = exc.message ?: exc.javaClass.simpleName
                lastError = "$slot:$streamError"
            } finally {
                image.close()
            }
        }

        private fun collectPendingYuvBurst(image: Image) {
            val pending = pendingYuvBurst ?: return
            if (pending.records.size >= pending.requestedFrames) return
            try {
                val index = pending.records.size
                val started = System.nanoTime()
                val record = pending.writer.writeYuvFrame(
                    index,
                    image,
                    JSONObject()
                        .put("source", "preview_yuv_cache")
                        .put("sensor_orientation_degrees", sensorOrientationDegrees)
                        .put("collected_index", index)
                        .put("requested_frames", pending.requestedFrames),
                )
                val writeMs = (System.nanoTime() - started).toDouble() / 1_000_000.0
                pending.records.add(record)
                updateBurstTelemetry(
                    "capturing",
                    burstId = pending.burstId,
                    path = pending.writer.burstDir().absolutePath,
                    requestedFrames = pending.requestedFrames,
                    capturedFrames = pending.records.size,
                    writeMs = writeMs,
                )
                if (pending.records.size >= pending.requestedFrames) {
                    finishYuvBurst(pending, "saved", "")
                }
            } catch (exc: Throwable) {
                finishYuvBurst(pending, "error", exc.message ?: exc.javaClass.simpleName)
            }
        }

        private fun finishYuvBurst(pending: PendingYuvBurst, finalStatus: String, error: String) {
            if (pendingYuvBurst?.burstId != pending.burstId) return
            val manifest = BurstManifest(
                burstId = pending.burstId,
                cameraId = cameraId,
                format = "YUV_420_888",
                frameCount = pending.records.size,
                requestedFrameCount = pending.requestedFrames,
                exposureStrategy = "preview_yuv_cache",
                iso = previewResultMetadata.optInt("actual_iso", 0).takeIf { it > 0 },
                exposureTimeNs = previewResultMetadata.optLong("actual_exposure_time_ns", 0L).takeIf { it > 0L },
                awbLocked = false,
                aeLocked = false,
                afLocked = false,
                gyroAvailable = false,
                frames = pending.records.toList(),
            )
            var manifestPath = ""
            var finalError = error
            var writeMs = burstLastWriteMs
            try {
                val started = System.nanoTime()
                val manifestFile = pending.writer.writeManifest(manifest)
                writeMs = (System.nanoTime() - started).toDouble() / 1_000_000.0
                manifestPath = manifestFile.absolutePath
                lastYuvBurstId = pending.burstId
                lastYuvBurstManifestPath = manifestPath
            } catch (exc: Throwable) {
                finalError = exc.message ?: exc.javaClass.simpleName
            } finally {
                pendingYuvBurst = null
            }
            val status = if (finalError.isNotEmpty()) {
                if (pending.records.isEmpty()) "error" else "partial"
            } else {
                finalStatus
            }
            updateBurstTelemetry(
                status,
                error = finalError,
                burstId = pending.burstId,
                path = pending.writer.burstDir().absolutePath,
                requestedFrames = pending.requestedFrames,
                capturedFrames = pending.records.size,
                manifestPath = manifestPath,
                writeMs = writeMs,
            )
            if (finalError.isEmpty() && status == "saved" && manifestPath.isNotBlank()) {
                processYuvBurstPackageAsync(
                    burstId = manifest.burstId,
                    manifestPath = manifestPath,
                )
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
            val rawBurst = pendingRawBurst
            if (rawBurst != null) {
                rawBurst.pendingRawImagesByTimestamp[image.timestamp] = image
                maybeWriteRawBurstFrame(rawBurst, image.timestamp)
                return
            }
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

        private fun maybeWriteRawBurstFrame(pending: PendingRawBurst, timestamp: Long) {
            if (pendingRawBurst?.burstId != pending.burstId) return
            val image = pending.pendingRawImagesByTimestamp.remove(timestamp) ?: return
            val result = pending.pendingRawResultsByTimestamp.remove(timestamp) ?: run {
                pending.pendingRawImagesByTimestamp[timestamp] = image
                return
            }
            try {
                val chars = cameraManager.getCameraCharacteristics(cameraId)
                val started = System.nanoTime()
                val record = pending.writer.writeRawFrame(pending.records.size, image, result, chars)
                val writeMs = (System.nanoTime() - started).toDouble() / 1_000_000.0
                pending.records.add(record)
                updateBurstTelemetry(
                    "capturing",
                    burstId = pending.burstId,
                    path = pending.writer.burstDir().absolutePath,
                    requestedFrames = pending.requestedFrames,
                    capturedFrames = pending.records.size,
                    writeMs = writeMs,
                )
                if (pending.records.size >= pending.requestedFrames) {
                    finishRawBurst(pending, "saved", "")
                }
            } catch (exc: Throwable) {
                finishRawBurst(pending, "error", exc.message ?: exc.javaClass.simpleName)
            } finally {
                image.close()
            }
        }

        private fun finishRawBurst(pending: PendingRawBurst, finalStatus: String, error: String) {
            if (pendingRawBurst?.burstId != pending.burstId) return
            val manifest = BurstManifest(
                burstId = pending.burstId,
                cameraId = cameraId,
                format = "RAW_SENSOR",
                frameCount = pending.records.size,
                requestedFrameCount = pending.requestedFrames,
                exposureStrategy = if (rawCaptureMode == "manual") "manual_raw_burst" else "auto_raw_burst",
                iso = previewResultMetadata.optInt("actual_iso", 0).takeIf { it > 0 },
                exposureTimeNs = previewResultMetadata.optLong("actual_exposure_time_ns", 0L).takeIf { it > 0L },
                awbLocked = true,
                aeLocked = true,
                afLocked = false,
                gyroAvailable = false,
                frames = pending.records.toList(),
            )
            var manifestPath = ""
            var finalError = error
            var writeMs = burstLastWriteMs
            try {
                val started = System.nanoTime()
                val manifestFile = pending.writer.writeManifest(manifest)
                writeMs = (System.nanoTime() - started).toDouble() / 1_000_000.0
                manifestPath = manifestFile.absolutePath
                lastRawBurstId = pending.burstId
                lastRawBurstManifestPath = manifestPath
            } catch (exc: Throwable) {
                finalError = exc.message ?: exc.javaClass.simpleName
            } finally {
                pendingRawBurst = null
                closeRawBurstBuffers(pending)
            }
            val status = if (finalError.isNotEmpty()) {
                if (pending.records.isEmpty()) "error" else "partial"
            } else {
                finalStatus
            }
            updateBurstTelemetry(
                status,
                error = finalError,
                burstId = pending.burstId,
                path = pending.writer.burstDir().absolutePath,
                requestedFrames = pending.requestedFrames,
                capturedFrames = pending.records.size,
                manifestPath = manifestPath,
                writeMs = writeMs,
            )
            val hasRaw16Frames = pending.records.any { it.raw16Path.isNotBlank() }
            if ((status == "saved" || status == "partial") && manifestPath.isNotBlank() && hasRaw16Frames) {
                if (pending.processingMode == "comparison") {
                    processRawComparisonPackageAsync(
                        burstId = manifest.burstId,
                        manifestPath = manifestPath,
                    )
                } else {
                    processRawBurstPackageAsync(
                        burstId = manifest.burstId,
                        manifestPath = manifestPath,
                    )
                }
            }
            streamHandler?.let { resumePreviewRepeating(it) }
        }

        private fun closePendingRawBurst() {
            val pending = pendingRawBurst ?: return
            pendingRawBurst = null
            closeRawBurstBuffers(pending)
        }

        private fun closeRawBurstBuffers(pending: PendingRawBurst) {
            for (image in pending.pendingRawImagesByTimestamp.values) {
                image.close()
            }
            pending.pendingRawImagesByTimestamp.clear()
            pending.pendingRawResultsByTimestamp.clear()
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
            val lensShadingMap = result.get(CaptureResult.STATISTICS_LENS_SHADING_CORRECTION_MAP)
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
                .put("lens_shading_available", lensShadingMap != null)
                .put("lens_shading_map", lensShadingMapJsonForMetadata(lensShadingMap))
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

        private fun lensShadingMapJsonForMetadata(map: LensShadingMap?): JSONObject {
            if (map == null) {
                return JSONObject()
                    .put("available", false)
                    .put("columns", 0)
                    .put("rows", 0)
                    .put("channel_order", "R,GE,GO,B")
                    .put("values", JSONArray())
            }
            return try {
                val values = JSONArray()
                for (row in 0 until map.rowCount) {
                    for (col in 0 until map.columnCount) {
                        values.put(map.getGainFactor(RggbChannelVector.RED, col, row).toDouble())
                        values.put(map.getGainFactor(RggbChannelVector.GREEN_EVEN, col, row).toDouble())
                        values.put(map.getGainFactor(RggbChannelVector.GREEN_ODD, col, row).toDouble())
                        values.put(map.getGainFactor(RggbChannelVector.BLUE, col, row).toDouble())
                    }
                }
                JSONObject()
                    .put("available", true)
                    .put("columns", map.columnCount)
                    .put("rows", map.rowCount)
                    .put("channel_order", "R,GE,GO,B")
                    .put("values", values)
            } catch (_: Throwable) {
                JSONObject()
                    .put("available", false)
                    .put("columns", 0)
                    .put("rows", 0)
                    .put("channel_order", "R,GE,GO,B")
                    .put("values", JSONArray())
            }
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

    private fun JSONObject.optFiniteDouble(key: String): Double? {
        val value = optDouble(key, Double.NaN)
        return if (java.lang.Double.isFinite(value)) value else null
    }

    private fun JSONObject.optNullableBoolean(key: String): Boolean? {
        return if (has(key) && !isNull(key)) optBoolean(key) else null
    }

    private fun JSONObject.optNullableInt(key: String): Int? {
        return if (has(key) && !isNull(key)) optInt(key) else null
    }
}
