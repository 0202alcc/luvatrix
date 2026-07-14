package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FullSuiteEmulatorAcceptanceTest {
    @Test
    fun fullSuiteEmulatorAcceptancePasses() {
        val marker = awaitPythonModule()
            .callAttr("full_suite_emulator_acceptance")
            .toString()
        assertEquals("luvatrix full_suite emulator ok", marker)
    }
}
