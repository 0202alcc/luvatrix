package com.luvatrix.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LaunchTimelineTest {
    @Test
    fun milestonesAreRelativeOrderedAndRecordedOnce() {
        var now = 1_000L
        val timeline = LaunchTimeline { now }

        now = 1_100L
        timeline.mark("python_start_begin")
        now = 1_250L
        timeline.mark("python_start_end")
        now = 1_500L
        timeline.mark("python_start_begin")

        val snapshot = timeline.snapshot()
        assertEquals(100L, snapshot["python_start_begin"])
        assertEquals(250L, snapshot["python_start_end"])
        assertTrue(snapshot["python_start_begin"]!! < snapshot["python_start_end"]!!)
    }

    @Test
    fun startupTaskIsScheduledWithoutRunningInline() {
        var scheduled: (() -> Unit)? = null
        var ran = false
        val runner = BackgroundStartupRunner { task -> scheduled = task }

        runner.start(task = { ran = true }, onFailure = { throw it })

        assertFalse(ran)
        assertTrue(scheduled != null)
        scheduled!!.invoke()
        assertTrue(ran)
    }

    @Test
    fun bootstrapCannotReplaceAnAppFrame() {
        val gate = BootstrapFrameGate()

        assertTrue(gate.shouldPresentBootstrap())
        gate.markAppFramePresented()

        assertFalse(gate.shouldPresentBootstrap())
    }
}
