package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SensorProbeTest {
    @Test
    fun sensorInventoryReachesPython() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        val telemetry = Python.getInstance().getModule("luvatrix_android_boot").callAttr("android_telemetry").toString()
        assertTrue(telemetry.contains("thermal.temperature"))
        println("luvatrix sensor probe ok")
    }
}
