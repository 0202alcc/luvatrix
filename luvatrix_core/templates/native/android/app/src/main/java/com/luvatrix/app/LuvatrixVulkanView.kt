package com.luvatrix.app

import android.app.Activity
import android.content.Context
import android.graphics.Canvas
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.os.Build
import android.os.Looper
import android.util.AttributeSet
import android.util.Log
import android.util.Base64
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.net.URL
import java.util.concurrent.ConcurrentLinkedQueue
import kotlin.math.abs

class LuvatrixVulkanView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : FrameLayout(context, attrs), SurfaceHolder.Callback {
    var framesPresented: Int = 0
        private set
    var lastInputCount: Int = 0
        private set
    private val surfaceView = SurfaceView(context)
    private val overlayView = SceneOverlayView(context)
    private var frameBitmap: android.graphics.Bitmap? = null
    private var frameBitmapWidth: Int = 0
    private var frameBitmapHeight: Int = 0
    private var overlaySceneJson: String? = null
    private var overlayLogicalWidth: Int = 1
    private var overlayLogicalHeight: Int = 1
    private var overlayNativeBackground: Boolean = false
    private var overlayMode: OverlayMode = OverlayMode.Scene
    private var bootstrapMessage: String? = null
    private var lowLatencyMode: Boolean = false
    private var lowLatencyPresentFps: Int? = null
    private var requestedRefreshHz: Float = 0.0f
    private var surfaceFrameRateHintHz: Float = 0.0f
    private var selectedDisplayModeId: Int = 0
    private var selectedDisplayModeHz: Float = 0.0f
    private var refreshHintMode: String = "60"
    private var refreshLastError: String = ""
    private var refreshProbeLogged: Boolean = false
    private val cameraBridge = CameraBridge(context)
    private val inputEvents = ConcurrentLinkedQueue<String>()
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = android.graphics.Typeface.MONOSPACE
    }
    private val matrixPaint = Paint().apply {
        isFilterBitmap = false
        isDither = false
    }

    init {
        loadBitmapGlyphTable()
        surfaceView.holder.addCallback(this)
        addView(surfaceView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        addView(overlayView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        isFocusable = true
        isFocusableInTouchMode = true
        requestFocus()
    }

    fun writeSecureSecret(key: String, value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secureStorageKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        val encoded = Base64.encodeToString(cipher.iv + encrypted, Base64.NO_WRAP)
        context.getSharedPreferences(SECURE_PREFS, Context.MODE_PRIVATE).edit().putString(key, encoded).apply()
    }

    fun readSecureSecret(key: String): String? {
        val encoded = context.getSharedPreferences(SECURE_PREFS, Context.MODE_PRIVATE).getString(key, null) ?: return null
        return try {
            val payload = Base64.decode(encoded, Base64.NO_WRAP)
            val iv = payload.copyOfRange(0, GCM_IV_BYTES)
            val encrypted = payload.copyOfRange(GCM_IV_BYTES, payload.size)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, secureStorageKey(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(encrypted), Charsets.UTF_8)
        } catch (exc: Throwable) {
            Log.e("Luvatrix", "Could not decrypt secure app secret", exc)
            null
        }
    }

    fun downloadImageRgba(url: String, size: Int): String? {
        require(size in 1..512) { "image size must be between 1 and 512" }
        val parsedUrl = URL(url)
        require(parsedUrl.protocol.equals("https", ignoreCase = true)) { "image URL must use HTTPS" }
        return try {
            val connection = parsedUrl.openConnection().apply {
                connectTimeout = 10_000
                readTimeout = 10_000
                setRequestProperty("User-Agent", "Luvatrix/Android")
            }
            val decoded = connection.getInputStream().use(BitmapFactory::decodeStream) ?: return null
            val scaled = Bitmap.createScaledBitmap(decoded, size, size, true)
            val pixels = IntArray(size * size)
            scaled.getPixels(pixels, 0, size, 0, 0, size, size)
            val rgba = ByteArray(size * size * 4)
            pixels.forEachIndexed { index, color ->
                val offset = index * 4
                rgba[offset] = Color.red(color).toByte()
                rgba[offset + 1] = Color.green(color).toByte()
                rgba[offset + 2] = Color.blue(color).toByte()
                rgba[offset + 3] = Color.alpha(color).toByte()
            }
            if (scaled !== decoded) scaled.recycle()
            decoded.recycle()
            android.util.Base64.encodeToString(rgba, android.util.Base64.NO_WRAP)
        } catch (exc: Throwable) {
            Log.e("Luvatrix", "Could not download image as RGBA", exc)
            null
        }
    }

    fun deleteSecureSecret(key: String) {
        context.getSharedPreferences(SECURE_PREFS, Context.MODE_PRIVATE).edit().remove(key).apply()
    }

    private fun secureStorageKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(SECURE_KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    SECURE_KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build()
            )
            generateKey()
        }
    }
    private fun loadBitmapGlyphTable() {
        try {
            val table = context.assets.open("luvatrix_bitmap_font.txt").bufferedReader().use { it.readText() }
            if (!NativeVulkan.setBitmapGlyphTable(table)) {
                Log.w("Luvatrix", "Android bitmap glyph table rejected; using built-in glyphs")
            }
        } catch (exc: Throwable) {
            Log.w("Luvatrix", "Android bitmap glyph table unavailable; using built-in glyphs", exc)
        }
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        NativeVulkan.setSurface(holder.surface)
        applyFrameRateHint()
        setBootstrapFrame(Color.rgb(12, 84, 140))
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        NativeVulkan.setSurface(holder.surface)
        applyFrameRateHint()
        setBootstrapFrame(Color.rgb(22, 98, 160))
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        cameraBridge.stopPreview()
        NativeVulkan.setSurface(null)
    }

    fun startCameraPreview() {
        startCameraPreview(null)
    }

    fun startCameraPreview(cameraId: String?) {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            post { startCameraPreview(cameraId) }
            return
        }
        (context as? Activity)?.let { activity ->
            if (!cameraBridge.requestPermissionIfNeeded(activity, CAMERA_PERMISSION_REQUEST)) {
                return
            }
        }
        cameraBridge.startPreview(cameraId)
        applyFrameRateHint()
    }

    fun startDualCameraPreview(primaryCameraId: String, secondaryCameraId: String) {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            post { startDualCameraPreview(primaryCameraId, secondaryCameraId) }
            return
        }
        (context as? Activity)?.let { activity ->
            if (!cameraBridge.requestPermissionIfNeeded(activity, CAMERA_PERMISSION_REQUEST)) {
                return
            }
        }
        cameraBridge.startDualPreview(primaryCameraId, secondaryCameraId)
        applyFrameRateHint()
    }

    fun stopCameraPreview() {
        cameraBridge.stopPreview()
    }

    fun setPrimaryCamera(cameraId: String) {
        cameraBridge.setPrimaryCamera(cameraId)
    }

    fun setDualPreviewEnabled(enabled: Boolean) {
        cameraBridge.setDualPreviewEnabled(enabled)
    }

    fun setCameraCoverMode(mode: String) {
        cameraBridge.setCoverMode(mode)
    }

    fun cameraInventoryJson(): String {
        return cameraBridge.inventoryJson()
    }

    fun cameraTelemetryJson(): String {
        return cameraBridge.telemetryJson()
    }

    fun cameraProbeAuditJson(): String {
        return cameraBridge.cameraProbeAuditJson()
    }

    fun captureRawStill(): String {
        return cameraBridge.captureRawStill()
    }

    fun setRawCaptureMode(mode: String): String {
        return cameraBridge.setRawCaptureMode(mode)
    }

    fun setPreviewManualMode(mode: String): String {
        return cameraBridge.setPreviewManualMode(mode)
    }

    fun adjustRawIso(deltaSteps: Int): String {
        return cameraBridge.adjustRawIso(deltaSteps)
    }

    fun adjustRawShutter(deltaSteps: Int): String {
        return cameraBridge.adjustRawShutter(deltaSteps)
    }

    fun adjustRawFocus(deltaSteps: Int): String {
        return cameraBridge.adjustRawFocus(deltaSteps)
    }

    fun resetRawCaptureControls(): String {
        return cameraBridge.resetRawCaptureControls()
    }

    fun setPreviewQualityMode(mode: String): String {
        return cameraBridge.setPreviewQualityMode(mode)
    }

    fun setPreviewTargetMode(mode: String): String {
        return cameraBridge.setPreviewTargetMode(mode)
    }

    fun setPreviewSharpnessMode(mode: String): String {
        return if (NativeVulkan.setCameraDownsampleMode(mode)) "ok" else "unsupported sharpness mode: $mode"
    }

    fun setPreviewConvolutionLayers(layers: Int): String {
        return if (NativeVulkan.setCameraConvolutionLayers(layers)) "ok" else "unsupported convolution layers: $layers"
    }

    fun setPreviewWhiteBalanceMode(mode: String): String {
        return if (NativeVulkan.setCameraColorMode(mode)) "ok" else "unsupported white balance mode: $mode"
    }

    fun setPreviewPipelineMode(mode: String): String {
        return cameraBridge.setPreviewPipelineMode(mode)
    }

    fun setRefreshHintMode(mode: String): String {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            post { setRefreshHintMode(mode) }
            return "posted"
        }
        val normalized = mode.trim().lowercase()
        val requested = when (normalized) {
            "default" -> 0.0f
            "60" -> 60.0f
            "90" -> 90.0f
            "120" -> 120.0f
            "highest" -> highestDisplayRefreshHz()
            else -> return "unsupported refresh hint mode: $mode"
        }
        refreshHintMode = normalized
        if (requested > 0.0f) {
            requestPreferredDisplayMode(requested)
            applyFrameRateHint()
        } else {
            clearPreferredDisplayMode()
        }
        refreshProbeLogged = false
        logRefreshProbeOnce()
        return "ok"
    }

    fun onCameraPermissionResult(granted: Boolean) {
        cameraBridge.onPermissionResult(granted)
    }

    fun presentRgba(rgba: ByteArray, revision: Int, width: Int, height: Int) {
        AndroidLaunchTelemetry.mark("first_app_frame_submitted")
        overlayView.post {
            bootstrapMessage = null
            if (frameBitmap == null || frameBitmapWidth != width || frameBitmapHeight != height) {
                frameBitmap = android.graphics.Bitmap.createBitmap(width, height, android.graphics.Bitmap.Config.ARGB_8888)
                frameBitmapWidth = width
                frameBitmapHeight = height
            }
            val bitmap = frameBitmap ?: return@post
            bitmap.copyPixelsFromBuffer(ByteBuffer.wrap(rgba))
            overlayMode = OverlayMode.Bitmap
            overlaySceneJson = null
            overlayView.setBackgroundColor(Color.TRANSPARENT)
            overlayView.invalidate()
            framesPresented += 1
        }
    }

    fun displayRefreshRateHz(): Float {
        val rate = surfaceView.display?.refreshRate ?: display?.refreshRate ?: 0.0f
        return if (rate > 0.0f) rate else 60.0f
    }

    fun displayRefreshTelemetryJson(): String {
        val actual = displayRefreshRateHz()
        val requested = requestedRefreshHz.takeIf { it > 0.0f } ?: (lowLatencyPresentFps?.toFloat() ?: actual)
        val actualMode = currentDisplayMode()
        return JSONObject()
            .put("supported_modes", displayModesJson())
            .put("requested_refresh_hz", requested.toDouble())
            .put("selected_mode_id", selectedDisplayModeId)
            .put("selected_mode_hz", selectedDisplayModeHz.toDouble())
            .put("actual_mode_id", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) actualMode?.modeId ?: 0 else 0)
            .put("actual_mode_hz", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) actualMode?.refreshRate?.toDouble() ?: actual.toDouble() else actual.toDouble())
            .put("actual_refresh_hz", actual.toDouble())
            .put("surface_frame_rate_hz", surfaceFrameRateHintHz.toDouble())
            .put("refresh_hint_mode", refreshHintMode)
            .put("preferred_display_mode_id", (context as? Activity)?.window?.attributes?.preferredDisplayModeId ?: 0)
            .put("honored", requested > 0.0f && abs(actual - requested) <= 2.0f)
            .put("camera_active", cameraBridge.isPreviewActive())
            .put("last_error", refreshLastError)
            .toString()
    }

    fun applyLowLatencyMode(targetFps: Int, presentFps: Int) {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            post { applyLowLatencyMode(targetFps, presentFps) }
            return
        }
        lowLatencyMode = true
        lowLatencyPresentFps = presentFps
        refreshHintMode = if (presentFps >= 120) "120" else presentFps.toString()
        keepScreenOn = true
        surfaceView.keepScreenOn = true
        (context as? Activity)?.window?.let { window ->
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        requestPreferredDisplayMode(presentFps.coerceAtLeast(1).toFloat())
        applyFrameRateHint()
        Log.i("Luvatrix", "Android low-latency mode enabled targetFps=$targetFps presentFps=$presentFps")
    }

    private fun requestPreferredDisplayMode(requestedHz: Float) {
        requestedRefreshHz = requestedHz
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            refreshLastError = "display modes require API 23"
            return
        }
        val activity = context as? Activity ?: return
        val selected = selectDisplayMode(requestedHz)
        if (selected == null) {
            refreshLastError = "no supported display modes"
            return
        }
        try {
            val attrs = activity.window.attributes
            attrs.preferredDisplayModeId = selected.modeId
            activity.window.attributes = attrs
            selectedDisplayModeId = selected.modeId
            selectedDisplayModeHz = selected.refreshRate
            refreshLastError = ""
            logRefreshProbeOnce()
        } catch (exc: Throwable) {
            refreshLastError = exc.message ?: exc.javaClass.simpleName
            Log.w("LuvatrixRefreshProbe", "preferred display mode unavailable", exc)
        }
    }

    private fun clearPreferredDisplayMode() {
        requestedRefreshHz = 0.0f
        surfaceFrameRateHintHz = 0.0f
        selectedDisplayModeId = 0
        selectedDisplayModeHz = 0.0f
        val activity = context as? Activity ?: return
        try {
            val attrs = activity.window.attributes
            attrs.preferredDisplayModeId = 0
            activity.window.attributes = attrs
            refreshLastError = ""
        } catch (exc: Throwable) {
            refreshLastError = exc.message ?: exc.javaClass.simpleName
            Log.w("LuvatrixRefreshProbe", "preferred display mode reset unavailable", exc)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val surface = surfaceView.holder.surface
            if (surface?.isValid == true) {
                try {
                    surface.setFrameRate(
                        0.0f,
                        Surface.FRAME_RATE_COMPATIBILITY_DEFAULT,
                        Surface.CHANGE_FRAME_RATE_ALWAYS,
                    )
                } catch (exc: Throwable) {
                    refreshLastError = exc.message ?: exc.javaClass.simpleName
                    Log.w("LuvatrixRefreshProbe", "frame-rate hint reset unavailable", exc)
                }
            }
        }
    }

    private fun selectDisplayMode(requestedHz: Float): android.view.Display.Mode? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        val modes = surfaceView.display?.supportedModes?.toList() ?: display?.supportedModes?.toList() ?: emptyList()
        if (modes.isEmpty()) return null
        val current = surfaceView.display?.mode ?: display?.mode
        val sameResolution = if (current != null) {
            modes.filter { it.physicalWidth == current.physicalWidth && it.physicalHeight == current.physicalHeight }
        } else {
            emptyList()
        }
        val candidates = sameResolution.ifEmpty { modes }
        return candidates.minWithOrNull(
            compareBy<android.view.Display.Mode> { if (it.refreshRate >= requestedHz) 0 else 1 }
                .thenBy { abs(it.refreshRate - requestedHz) }
                .thenByDescending { it.refreshRate }
                .thenByDescending { it.physicalWidth.toLong() * it.physicalHeight.toLong() },
        )
    }

    private fun applyFrameRateHint() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return
        }
        val presentFps = requestedRefreshHz.takeIf { it > 0.0f } ?: lowLatencyPresentFps?.toFloat() ?: return
        val surface = surfaceView.holder.surface ?: return
        if (!surface.isValid) {
            return
        }
        try {
            surface.setFrameRate(
                presentFps.coerceAtLeast(1.0f),
                Surface.FRAME_RATE_COMPATIBILITY_FIXED_SOURCE,
                Surface.CHANGE_FRAME_RATE_ALWAYS,
            )
            surfaceFrameRateHintHz = presentFps.coerceAtLeast(1.0f)
            logRefreshProbeOnce()
        } catch (exc: Throwable) {
            refreshLastError = exc.message ?: exc.javaClass.simpleName
            Log.w("Luvatrix", "Android frame-rate hint unavailable", exc)
        }
    }

    private fun currentDisplayMode(): android.view.Display.Mode? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        return surfaceView.display?.mode ?: display?.mode
    }

    private fun highestDisplayRefreshHz(): Float {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return 120.0f
        val modes = surfaceView.display?.supportedModes?.toList() ?: display?.supportedModes?.toList() ?: emptyList()
        return modes.maxOfOrNull { it.refreshRate } ?: 120.0f
    }

    private fun displayModesJson(): JSONArray {
        val out = JSONArray()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return out
        val modes = surfaceView.display?.supportedModes?.toList() ?: display?.supportedModes?.toList() ?: emptyList()
        for (mode in modes.sortedWith(compareBy<android.view.Display.Mode> { it.refreshRate }.thenBy { it.modeId })) {
            out.put(
                JSONObject()
                    .put("mode_id", mode.modeId)
                    .put("width", mode.physicalWidth)
                    .put("height", mode.physicalHeight)
                    .put("refresh_hz", mode.refreshRate.toDouble()),
            )
        }
        return out
    }

    private fun logRefreshProbeOnce() {
        if (refreshProbeLogged) return
        refreshProbeLogged = true
        Log.i(
            "LuvatrixRefreshProbe",
            "requested=${requestedRefreshHz} actual=${displayRefreshRateHz()} " +
                "surfaceHint=${surfaceFrameRateHintHz} selectedMode=$selectedDisplayModeId " +
                "selectedHz=$selectedDisplayModeHz actualMode=${currentDisplayMode()?.modeId ?: 0} " +
                "hintMode=$refreshHintMode",
        )
    }

    fun presentScene(sceneJson: String, revision: Int, logicalWidth: Int, logicalHeight: Int, presentationMode: String = "") {
        AndroidLaunchTelemetry.mark("first_app_frame_submitted")
        var nativeBackground = false
        try {
            nativeBackground = NativeVulkan.presentScene(sceneJson, revision, logicalWidth, logicalHeight, presentationMode)
        } catch (exc: Throwable) {
            Log.w("Luvatrix", "native Vulkan scene presenter unavailable; using Canvas fallback", exc)
        }
        overlayView.post {
            bootstrapMessage = null
            overlayMode = OverlayMode.Scene
            overlaySceneJson = if (nativeBackground) null else sceneJson
            overlayLogicalWidth = logicalWidth
            overlayLogicalHeight = logicalHeight
            overlayNativeBackground = nativeBackground
            overlayView.setBackgroundColor(Color.TRANSPARENT)
            overlayView.invalidate()
            framesPresented += 1
        }
    }

    private fun drawSceneCanvas(canvas: Canvas, sceneJson: String, logicalWidth: Int, logicalHeight: Int, nativeBackground: Boolean) {
        val nodes = JSONArray(sceneJson)
        val scaleX = canvas.width.toFloat() / logicalWidth.coerceAtLeast(1).toFloat()
        val scaleY = canvas.height.toFloat() / logicalHeight.coerceAtLeast(1).toFloat()
        var contentOffsetX = 0.0
        var contentOffsetY = 0.0
        for (idx in 0 until nodes.length()) {
            val node = nodes.getJSONObject(idx)
            if (node.optString("type") == "meta") {
                contentOffsetX = node.optDouble("content_offset_x", contentOffsetX)
                contentOffsetY = node.optDouble("content_offset_y", contentOffsetY)
            }
        }
        for (idx in 0 until nodes.length()) {
            val node = nodes.getJSONObject(idx)
            when (node.optString("type")) {
                "clear" -> if (!nativeBackground) canvas.drawColor(colorFromArray(node.getJSONArray("color")))
                "shader_rect" -> {
                    if (nativeBackground && node.optString("shader") == "full_suite_background") {
                        continue
                    }
                    if (node.optString("shader") == "full_suite_background") {
                        val uniforms = node.optJSONArray("uniforms")
                        val t = uniforms?.optDouble(0, 0.0) ?: 0.0
                        val rotation = uniforms?.optDouble(1, 0.0) ?: 0.0
                        val scrollY = uniforms?.optDouble(2, 0.0) ?: 0.0
                        fillPaint.shader = fullSuiteBackgroundGradient(canvas, t, rotation, scrollY)
                    } else {
                        fillPaint.shader = null
                        fillPaint.color = colorFromArray(node.getJSONArray("color"))
                    }
                    fillPaint.style = Paint.Style.FILL
                    val applyContentOffset = node.optString("shader") != "full_suite_background"
                    drawRectNode(canvas, node, scaleX, scaleY, fillPaint, if (applyContentOffset) contentOffsetX else 0.0, if (applyContentOffset) contentOffsetY else 0.0)
                    fillPaint.shader = null
                }
                "rect" -> {
                    fillPaint.shader = null
                    fillPaint.color = colorFromArray(node.getJSONArray("color"))
                    fillPaint.style = Paint.Style.FILL
                    drawRectNode(canvas, node, scaleX, scaleY, fillPaint, contentOffsetX, contentOffsetY)
                }
                "circle" -> {
                    fillPaint.color = colorFromArray(node.getJSONArray("fill"))
                    fillPaint.style = Paint.Style.FILL
                    canvas.drawCircle(
                        ((node.optDouble("cx", 0.0) - contentOffsetX) * scaleX).toFloat(),
                        ((node.optDouble("cy", 0.0) - contentOffsetY) * scaleY).toFloat(),
                        (node.optDouble("r", 0.0) * kotlin.math.min(scaleX, scaleY)).toFloat(),
                        fillPaint,
                    )
                    val strokeWidth = node.optDouble("stroke_width", 0.0)
                    if (strokeWidth > 0.0) {
                        strokePaint.color = colorFromArray(node.getJSONArray("stroke"))
                        strokePaint.strokeWidth = (strokeWidth * kotlin.math.min(scaleX, scaleY)).toFloat()
                        canvas.drawCircle(
                            ((node.optDouble("cx", 0.0) - contentOffsetX) * scaleX).toFloat(),
                            ((node.optDouble("cy", 0.0) - contentOffsetY) * scaleY).toFloat(),
                            (node.optDouble("r", 0.0) * kotlin.math.min(scaleX, scaleY)).toFloat(),
                            strokePaint,
                        )
                    }
                }
                "text" -> {
                    textPaint.color = colorFromArray(node.getJSONArray("color"))
                    textPaint.textSize = (node.optDouble("size", 12.0) * kotlin.math.min(scaleX, scaleY)).toFloat()
                    canvas.drawText(
                        node.optString("text", ""),
                        ((node.optDouble("x", 0.0) - contentOffsetX) * scaleX).toFloat(),
                        ((node.optDouble("y", 0.0) - contentOffsetY) * scaleY + textPaint.textSize).toFloat(),
                        textPaint,
                    )
                }
            }
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (lowLatencyMode) {
            requestUnbufferedDispatch(event)
        }
        lastInputCount += 1
        enqueueTouch(event)
        return true
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        lastInputCount += 1
        enqueueKey(event, "down")
        return true
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
        lastInputCount += 1
        enqueueKey(event, "up")
        return true
    }

    fun drainInputEventsJson(): Array<String> {
        val out = ArrayList<String>()
        while (true) {
            val event = inputEvents.poll() ?: break
            out.add(event)
        }
        return out.toTypedArray()
    }

    private fun enqueueTouch(event: MotionEvent) {
        val action = event.actionMasked
        val pointerIndex = event.actionIndex.coerceAtLeast(0)
        val phase = when (action) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> "down"
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> "up"
            MotionEvent.ACTION_CANCEL -> "cancel"
            else -> "move"
        }
        for (idx in 0 until event.pointerCount) {
            if ((action == MotionEvent.ACTION_POINTER_DOWN || action == MotionEvent.ACTION_POINTER_UP) && idx != pointerIndex) {
                continue
            }
            inputEvents.add(
                JSONObject()
                    .put("device", "touch")
                    .put("touch_id", event.getPointerId(idx))
                    .put("phase", phase)
                    .put("x", event.getX(idx).toDouble())
                    .put("y", event.getY(idx).toDouble())
                    .put("force", event.getPressure(idx).toDouble())
                    .put("major_radius", event.getTouchMajor(idx).toDouble())
                    .put("tool_type", event.getToolType(idx).toString())
                    .toString()
            )
        }
    }

    private fun enqueueKey(event: KeyEvent, phase: String) {
        inputEvents.add(
            JSONObject()
                .put("device", "keyboard")
                .put("key", KeyEvent.keyCodeToString(event.keyCode))
                .put("phase", phase)
                .put("scan_code", event.scanCode)
                .toString()
        )
    }

    private fun setBootstrapFrame(color: Int) {
        overlayView.post {
            overlayMode = OverlayMode.Bootstrap
            overlaySceneJson = null
            overlayView.setBackgroundColor(color)
            overlayView.invalidate()
            framesPresented += 1
        }
    }

    fun launchTelemetryJson(): String {
        val payload = JSONObject()
        for ((name, elapsedNs) in AndroidLaunchTelemetry.snapshot()) {
            payload.put(name, elapsedNs)
        }
        return payload.toString()
    }

    fun showRuntimeError(message: String) {
        overlayView.post {
            bootstrapMessage = message.take(320)
            overlayMode = OverlayMode.Bootstrap
            overlaySceneJson = null
            overlayView.setBackgroundColor(Color.rgb(72, 18, 30))
            overlayView.invalidate()
        }
    }

    private fun drawRectNode(canvas: android.graphics.Canvas, node: org.json.JSONObject, scaleX: Float, scaleY: Float, paint: Paint, contentOffsetX: Double = 0.0, contentOffsetY: Double = 0.0) {
        val left = ((node.optDouble("x", 0.0) - contentOffsetX) * scaleX).toFloat()
        val top = ((node.optDouble("y", 0.0) - contentOffsetY) * scaleY).toFloat()
        val right = ((node.optDouble("x", 0.0) + node.optDouble("w", 0.0) - contentOffsetX) * scaleX).toFloat()
        val bottom = ((node.optDouble("y", 0.0) + node.optDouble("h", 0.0) - contentOffsetY) * scaleY).toFloat()
        canvas.drawRect(left, top, right, bottom, paint)
    }

    private fun colorFromArray(values: JSONArray): Int {
        return Color.argb(
            values.optInt(3, 255).coerceIn(0, 255),
            values.optInt(0, 0).coerceIn(0, 255),
            values.optInt(1, 0).coerceIn(0, 255),
            values.optInt(2, 0).coerceIn(0, 255),
        )
    }

    private fun fullSuiteBackgroundGradient(canvas: Canvas, t: Double, rotation: Double, scrollY: Double): Shader {
        val phase = ((t * 0.0025 + rotation * 0.01 + scrollY * 0.002) % 1.0).toFloat()
        val colors = intArrayOf(
            Color.HSVToColor(floatArrayOf(((phase + 0.00f) % 1.0f) * 360.0f, 0.82f, 0.88f)),
            Color.HSVToColor(floatArrayOf(((phase + 0.18f) % 1.0f) * 360.0f, 0.82f, 0.92f)),
            Color.HSVToColor(floatArrayOf(((phase + 0.36f) % 1.0f) * 360.0f, 0.82f, 0.82f)),
            Color.HSVToColor(floatArrayOf(((phase + 0.62f) % 1.0f) * 360.0f, 0.82f, 0.92f)),
            Color.HSVToColor(floatArrayOf(((phase + 0.82f) % 1.0f) * 360.0f, 0.82f, 0.86f)),
        )
        return LinearGradient(
            0.0f,
            0.0f,
            canvas.width.toFloat(),
            canvas.height.toFloat(),
            colors,
            null,
            Shader.TileMode.MIRROR,
        )
    }

    private enum class OverlayMode {
        Bootstrap,
        Bitmap,
        Scene,
    }

    companion object {
        const val CAMERA_PERMISSION_REQUEST = 4201
        private const val SECURE_PREFS = "luvatrix_secure_app_storage"
        private const val SECURE_KEY_ALIAS = "luvatrix_app_secrets"
        private const val GCM_IV_BYTES = 12
    }

    private inner class SceneOverlayView(context: Context) : View(context) {
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            if (overlayMode == OverlayMode.Bootstrap) {
                AndroidLaunchTelemetry.mark("bootstrap_frame_drawn")
            } else {
                AndroidLaunchTelemetry.mark("first_app_frame_drawn")
            }
            when (overlayMode) {
                OverlayMode.Bootstrap -> {
                    val message = bootstrapMessage ?: return
                    textPaint.color = Color.WHITE
                    textPaint.textSize = 30.0f
                    val margin = 36.0f
                    canvas.drawText("Luvatrix runtime error", margin, margin + 34.0f, textPaint)
                    textPaint.textSize = 22.0f
                    var y = margin + 76.0f
                    for (line in message.chunked(42).take(7)) {
                        canvas.drawText(line, margin, y, textPaint)
                        y += 30.0f
                    }
                }
                OverlayMode.Bitmap -> frameBitmap?.let { canvas.drawBitmap(it, null, canvas.clipBounds, matrixPaint) }
                OverlayMode.Scene -> {
                    val scene = overlaySceneJson ?: return
                    drawSceneCanvas(canvas, scene, overlayLogicalWidth, overlayLogicalHeight, overlayNativeBackground)
                }
            }
        }
    }
}
