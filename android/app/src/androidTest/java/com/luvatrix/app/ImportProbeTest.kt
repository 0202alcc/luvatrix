package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.platform.app.InstrumentationRegistry

@RunWith(AndroidJUnit4::class)
class ImportProbeTest {
    @Test
    fun importProbePasses() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        val marker = Python.getInstance().getModule("luvatrix_android_boot").callAttr("import_probe").toString()
        assertEquals("luvatrix import probe ok", marker)
    }
}
