package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FullSuiteVisualLaunchTest {
    @Test
    fun fullSuiteVisualLaunchPasses() {
        val marker = awaitPythonModule().callAttr("run_app_vulkan").toString()
        assertEquals("luvatrix full_suite visual ok", marker)
    }
}
