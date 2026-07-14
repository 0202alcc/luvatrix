package com.luvatrix.app

import android.app.Application
import android.content.Context
import android.util.Log
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.util.concurrent.Executors
import java.util.concurrent.ThreadFactory
import java.util.concurrent.atomic.AtomicInteger

class LuvatrixApplication : Application() {
    private val pythonStartupExecutor = Executors.newSingleThreadExecutor(namedThreadFactory("luvatrix-python-startup"))
    private val nativeStartupExecutor = Executors.newSingleThreadExecutor(namedThreadFactory("luvatrix-vulkan-startup"))
    private val runtimeThreadNumber = AtomicInteger()
    internal val runtimeExecutor = Executors.newCachedThreadPool { task ->
        Thread(task, "luvatrix-runtime-${runtimeThreadNumber.incrementAndGet()}").apply { isDaemon = true }
    }

    internal lateinit var pythonStartup: SharedStartup<PyObject>
        private set
    internal lateinit var nativeVulkanStartup: SharedStartup<Unit>
        private set

    override fun onCreate() {
        super.onCreate()
        AndroidLaunchTelemetry.mark("application_on_create")
        pythonStartup = SharedStartup(pythonStartupExecutor) { startPython() }
        nativeVulkanStartup = SharedStartup(nativeStartupExecutor) { startNativeVulkan() }
    }

    internal fun executeNative(task: () -> Unit) {
        nativeStartupExecutor.execute(task)
    }

    internal fun whenNativeReady(onReady: () -> Unit, onFailure: (Throwable) -> Unit) {
        nativeVulkanStartup.whenReady(
            executor = nativeStartupExecutor,
            onReady = { onReady() },
            onFailure = onFailure,
        )
    }

    private fun startPython(): PyObject {
        AndroidLaunchTelemetry.mark("python_start_begin")
        Log.i(MainActivity.TAG, "starting Python runtime")
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        AndroidLaunchTelemetry.mark("python_start_end")
        Log.i(MainActivity.TAG, "loading luvatrix_android_boot")
        return Python.getInstance().getModule("luvatrix_android_boot").also {
            AndroidLaunchTelemetry.mark("boot_module_loaded")
        }
    }

    private fun startNativeVulkan() {
        AndroidLaunchTelemetry.mark("vulkan_start_begin")
        NativeVulkan.ensureLoaded()
        try {
            val table = assets.open("luvatrix_bitmap_font.txt").bufferedReader().use { it.readText() }
            if (!NativeVulkan.setBitmapGlyphTable(table)) {
                Log.w(MainActivity.TAG, "Android bitmap glyph table rejected; using built-in glyphs")
            }
        } catch (exc: Throwable) {
            Log.w(MainActivity.TAG, "Android bitmap glyph table unavailable; using built-in glyphs", exc)
        }
        AndroidLaunchTelemetry.mark("vulkan_start_end")
    }

    private fun namedThreadFactory(name: String): ThreadFactory = ThreadFactory { task ->
        Thread(task, name).apply { isDaemon = true }
    }

    companion object {
        internal fun from(context: Context): LuvatrixApplication {
            return context.applicationContext as? LuvatrixApplication
                ?: error("LuvatrixApplication must be registered in AndroidManifest.xml")
        }
    }
}
