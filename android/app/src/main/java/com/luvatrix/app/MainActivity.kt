package com.luvatrix.app

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class MainActivity : Activity() {
    private lateinit var luvatrixView: LuvatrixVulkanView
    private var pythonModule: PyObject? = null
    private val startupRunner = BackgroundStartupRunner()
    @Volatile private var destroyed = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AndroidLaunchTelemetry.mark("activity_on_create")
        luvatrixView = LuvatrixVulkanView(this)
        setContentView(luvatrixView)
        AndroidLaunchTelemetry.mark("view_attached")
        luvatrixView.requestFocus()
        val presentFps = 60
        luvatrixView.applyLowLatencyMode(presentFps * 2, presentFps)
        val importProbe = intent.getBooleanExtra("luvatrix_import_probe", false)
        startupRunner.start(
            task = {
                AndroidLaunchTelemetry.mark("python_start_begin")
                Log.i(TAG, "starting Python runtime")
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(this))
                }
                AndroidLaunchTelemetry.mark("python_start_end")
                Log.i(TAG, "loading luvatrix_android_boot")
                val module = Python.getInstance().getModule("luvatrix_android_boot")
                pythonModule = module
                pythonBridge = PythonBridge(module)
                AndroidLaunchTelemetry.mark("boot_module_loaded")
                if (destroyed) return@start
                Log.i(TAG, "starting Luvatrix visual runtime importProbe=$importProbe")
                AndroidLaunchTelemetry.mark("runtime_call_begin")
                if (importProbe) {
                    module.callAttr("import_probe")
                } else {
                    module.callAttr("run_app_vulkan", luvatrixView)
                }
                Log.i(TAG, "Luvatrix visual runtime returned")
            },
            onFailure = { exc ->
                Log.e(TAG, "luvatrix python runtime failed", exc)
                if (!destroyed) {
                    luvatrixView.showRuntimeError("${exc.javaClass.simpleName}: ${exc.message ?: "unknown error"}")
                }
            },
        )
    }

    override fun onDestroy() {
        destroyed = true
        val module = pythonModule
        if (module != null && ::luvatrixView.isInitialized) {
            try {
                module.callAttr("detach_android_view", luvatrixView)
            } catch (exc: Throwable) {
                Log.w(TAG, "could not detach destroyed Android view", exc)
            }
        }
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == LuvatrixVulkanView.CAMERA_PERMISSION_REQUEST) {
            luvatrixView.onCameraPermissionResult(grantResults.firstOrNull() == android.content.pm.PackageManager.PERMISSION_GRANTED)
        }
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
