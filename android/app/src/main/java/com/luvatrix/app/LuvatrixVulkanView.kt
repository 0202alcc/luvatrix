package com.luvatrix.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.AttributeSet
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
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
    private val inputEvents = ConcurrentLinkedQueue<String>()
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = android.graphics.Typeface.MONOSPACE
    }

    init {
        surfaceView.holder.addCallback(this)
        addView(surfaceView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        addView(overlayView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        isFocusable = true
        isFocusableInTouchMode = true
        requestFocus()
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        NativeVulkan.setSurface(holder.surface)
        setBootstrapFrame(Color.rgb(12, 84, 140))
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        NativeVulkan.setSurface(holder.surface)
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

    fun presentScene(sceneJson: String, revision: Int, logicalWidth: Int, logicalHeight: Int) {
        var nativeBackground = false
        try {
            nativeBackground = NativeVulkan.presentScene(sceneJson, revision, logicalWidth, logicalHeight)
        } catch (exc: Throwable) {
            android.util.Log.w("Luvatrix", "native Vulkan scene presenter unavailable; using Canvas fallback", exc)
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
                        fillPaint.color = fullSuiteBackgroundColor(t, rotation, scrollY)
                    } else {
                        fillPaint.color = colorFromArray(node.getJSONArray("color"))
                    }
                    fillPaint.style = Paint.Style.FILL
                    drawRectNode(canvas, node, scaleX, scaleY, fillPaint)
                }
                "rect" -> {
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

    private fun fullSuiteBackgroundColor(t: Double, rotation: Double, scrollY: Double): Int {
        val ti = t.toInt()
        val baseR = (ti * 3 + 35) % 255
        val baseG = (ti * 2 + 70) % 255
        val baseB = (ti * 4 + 20) % 255
        val rotateBoost = (rotation * 2.0).coerceIn(-30.0, 30.0).toInt()
        val scrollBoost = (scrollY * 0.5).coerceIn(-40.0, 40.0).toInt()
        return Color.argb(
            255,
            (baseR + rotateBoost).coerceIn(0, 255),
            (baseG + scrollBoost).coerceIn(0, 255),
            baseB.coerceIn(0, 255),
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
