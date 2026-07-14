package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SensorProbeTest {
    @Test
    fun sensorInventoryReachesPython() {
        val telemetry = awaitPythonModule().callAttr("android_telemetry").toString()
        assertTrue(telemetry.contains("thermal.temperature"))
        println("luvatrix sensor probe ok")
    }
}
