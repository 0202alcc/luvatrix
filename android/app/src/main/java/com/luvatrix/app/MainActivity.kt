package com.luvatrix.app

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlin.math.roundToInt

class MainActivity : Activity() {
    private lateinit var luvatrixView: LuvatrixVulkanView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        luvatrixView = LuvatrixVulkanView(this)
        setContentView(luvatrixView)
        luvatrixView.requestFocus()
        val presentFps = luvatrixView.displayRefreshRateHz().roundToInt().coerceAtLeast(60)
        luvatrixView.applyLowLatencyMode(presentFps * 2, presentFps)
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        val module = Python.getInstance().getModule("luvatrix_android_boot")
        pythonBridge = PythonBridge(module)

        val importProbe = intent.getBooleanExtra("luvatrix_import_probe", false)
        Thread {
            try {
                if (importProbe) {
                    module.callAttr("import_probe")
                } else {
                    module.callAttr("run_app_vulkan", luvatrixView)
                }
            } catch (exc: Throwable) {
                Log.e(TAG, "luvatrix python runtime failed", exc)
            }
        }.start()
    }

    class PythonBridge(private val module: PyObject) {
        fun enqueueTouch(event: MotionEvent) {
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
                module.callAttr(
                    "enqueue_touch",
                    event.getPointerId(idx),
                    phase,
                    event.getX(idx).toDouble(),
                    event.getY(idx).toDouble(),
                    event.getPressure(idx).toDouble(),
                    event.getTouchMajor(idx).toDouble(),
                    event.getToolType(idx).toString(),
                )
            }
        }

        fun enqueueKey(event: KeyEvent, phase: String) {
            module.callAttr("enqueue_key", KeyEvent.keyCodeToString(event.keyCode), phase, event.scanCode)
        }
    }

    companion object {
        const val TAG = "Luvatrix"
        @JvmStatic var pythonBridge: PythonBridge? = null
    }
}
