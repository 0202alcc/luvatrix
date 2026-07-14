package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HeadlessLifecycleTest {
    @Test
    fun fullSuiteRunsHeadlessTicks() {
        val marker = awaitPythonModule().callAttr("run_headless_ticks", 5).toString()
        assertEquals("luvatrix headless lifecycle ok", marker)
    }
}
