package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InputBridgeTest {
    @Test
    fun inputBridgeReachesPythonTelemetry() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        val module = Python.getInstance().getModule("luvatrix_android_boot")
        module.callAttr("enqueue_touch", 1, "down", 10.0, 20.0, 0.5, 8.0, "finger")
        val telemetry = module.callAttr("android_telemetry").toString()
        assertTrue(telemetry.contains("enqueued"))
        assertTrue(telemetry.contains("active_touches"))
        println("luvatrix input bridge ok")
    }
}
