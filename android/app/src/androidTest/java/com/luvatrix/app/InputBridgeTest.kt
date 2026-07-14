package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InputBridgeTest {
    @Test
    fun inputBridgeReachesPythonTelemetry() {
        val module = awaitPythonModule()
        module.callAttr("enqueue_touch", 1, "down", 10.0, 20.0, 0.5, 8.0, "finger")
        val telemetry = module.callAttr("android_telemetry").toString()
        assertTrue(telemetry.contains("enqueued"))
        assertTrue(telemetry.contains("active_touches"))
        println("luvatrix input bridge ok")
    }
}
