package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FullSuiteVisualLaunchTest {
    @Test
    fun fullSuiteVisualLaunchPasses() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        val marker = Python.getInstance().getModule("luvatrix_android_boot").callAttr("run_app_vulkan").toString()
        assertEquals("luvatrix full_suite visual ok", marker)
    }
}
