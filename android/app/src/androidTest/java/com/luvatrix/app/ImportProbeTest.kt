package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ImportProbeTest {
    @Test
    fun importProbePasses() {
        val marker = awaitPythonModule().callAttr("import_probe").toString()
        assertEquals("luvatrix import probe ok", marker)
    }
}
