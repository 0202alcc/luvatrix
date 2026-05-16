package com.luvatrix.app

import android.app.Activity
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.os.Build
import android.os.Looper
import android.util.AttributeSet
import android.util.Log
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
import java.util.concurrent.ConcurrentLinkedQueue

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
    private var lowLatencyMode: Boolean = false
    private var lowLatencyPresentFps: Int? = null
    private val inputEvents = ConcurrentLinkedQueue<String>()
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = android.graphics.Typeface.MONOSPACE
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
        NativeVulkan.setSurface(null)
    }

    fun presentRgba(rgba: ByteArray, revision: Int, width: Int, height: Int) {
        overlayView.post {
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

    fun applyLowLatencyMode(targetFps: Int, presentFps: Int) {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            post { applyLowLatencyMode(targetFps, presentFps) }
            return
        }
        lowLatencyMode = true
        lowLatencyPresentFps = presentFps
        keepScreenOn = true
        surfaceView.keepScreenOn = true
        (context as? Activity)?.window?.let { window ->
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                try {
                    window.setSustainedPerformanceMode(true)
                } catch (exc: Throwable) {
                    Log.w("Luvatrix", "Android sustained performance mode unavailable", exc)
                }
            }
        }
        applyFrameRateHint()
        Log.i("Luvatrix", "Android low-latency mode enabled targetFps=$targetFps presentFps=$presentFps")
    }

    private fun applyFrameRateHint() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return
        }
        val presentFps = lowLatencyPresentFps ?: return
        val surface = surfaceView.holder.surface ?: return
        if (!surface.isValid) {
            return
        }
        try {
            surface.setFrameRate(
                presentFps.coerceAtLeast(1).toFloat(),
                Surface.FRAME_RATE_COMPATIBILITY_FIXED_SOURCE,
                Surface.CHANGE_FRAME_RATE_ALWAYS,
            )
        } catch (exc: Throwable) {
            Log.w("Luvatrix", "Android frame-rate hint unavailable", exc)
        }
    }

    fun presentScene(sceneJson: String, revision: Int, logicalWidth: Int, logicalHeight: Int) {
        var nativeBackground = false
        try {
            nativeBackground = NativeVulkan.presentScene(sceneJson, revision, logicalWidth, logicalHeight)
        } catch (exc: Throwable) {
            Log.w("Luvatrix", "native Vulkan scene presenter unavailable; using Canvas fallback", exc)
        }
        overlayView.post {
            overlayMode = OverlayMode.Scene
            overlaySceneJson = sceneJson
            overlayLogicalWidth = logicalWidth
            overlayLogicalHeight = logicalHeight
            overlayNativeBackground = nativeBackground
            overlayView.setBackgroundColor(Color.TRANSPARENT)
            overlayView.invalidate()
            framesPresented += 1
        }
    }

    private fun drawSceneCanvas(canvas: Canvas, sceneJson: String, logicalWidth: Int, logicalHeight: Int, nativeBackground: Boolean) {
        if (nativeBackground) return
        val nodes = JSONArray(sceneJson)
        val scaleX = canvas.width.toFloat() / logicalWidth.coerceAtLeast(1).toFloat()
        val scaleY = canvas.height.toFloat() / logicalHeight.coerceAtLeast(1).toFloat()
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
                    drawRectNode(canvas, node, scaleX, scaleY, fillPaint)
                    fillPaint.shader = null
                }
                "rect" -> {
                    fillPaint.shader = null
                    fillPaint.color = colorFromArray(node.getJSONArray("color"))
                    fillPaint.style = Paint.Style.FILL
                    drawRectNode(canvas, node, scaleX, scaleY, fillPaint)
                }
                "circle" -> {
                    fillPaint.color = colorFromArray(node.getJSONArray("fill"))
                    fillPaint.style = Paint.Style.FILL
                    canvas.drawCircle(
                        (node.optDouble("cx", 0.0) * scaleX).toFloat(),
                        (node.optDouble("cy", 0.0) * scaleY).toFloat(),
                        (node.optDouble("r", 0.0) * kotlin.math.min(scaleX, scaleY)).toFloat(),
                        fillPaint,
                    )
                    val strokeWidth = node.optDouble("stroke_width", 0.0)
                    if (strokeWidth > 0.0) {
                        strokePaint.color = colorFromArray(node.getJSONArray("stroke"))
                        strokePaint.strokeWidth = (strokeWidth * kotlin.math.min(scaleX, scaleY)).toFloat()
                        canvas.drawCircle(
                            (node.optDouble("cx", 0.0) * scaleX).toFloat(),
                            (node.optDouble("cy", 0.0) * scaleY).toFloat(),
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
                        (node.optDouble("x", 0.0) * scaleX).toFloat(),
                        (node.optDouble("y", 0.0) * scaleY + textPaint.textSize).toFloat(),
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

    private fun drawRectNode(canvas: android.graphics.Canvas, node: org.json.JSONObject, scaleX: Float, scaleY: Float, paint: Paint) {
        val left = (node.optDouble("x", 0.0) * scaleX).toFloat()
        val top = (node.optDouble("y", 0.0) * scaleY).toFloat()
        val right = ((node.optDouble("x", 0.0) + node.optDouble("w", 0.0)) * scaleX).toFloat()
        val bottom = ((node.optDouble("y", 0.0) + node.optDouble("h", 0.0)) * scaleY).toFloat()
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

    private inner class SceneOverlayView(context: Context) : View(context) {
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            when (overlayMode) {
                OverlayMode.Bootstrap -> Unit
                OverlayMode.Bitmap -> frameBitmap?.let { canvas.drawBitmap(it, null, canvas.clipBounds, null) }
                OverlayMode.Scene -> {
                    val scene = overlaySceneJson ?: return
                    drawSceneCanvas(canvas, scene, overlayLogicalWidth, overlayLogicalHeight, overlayNativeBackground)
                }
            }
        }
    }
}
