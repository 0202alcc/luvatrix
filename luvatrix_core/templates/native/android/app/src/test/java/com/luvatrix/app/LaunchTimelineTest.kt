package com.luvatrix.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.Executor

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
    fun sharedStartupBeginsImmediatelyAndPublishesOneFuture() {
        val scheduled = mutableListOf<Runnable>()
        val executor = Executor { task -> scheduled += task }
        var starts = 0
        val observed = mutableListOf<String>()

        val startup = SharedStartup(executor) {
            starts += 1
            "python-module"
        }
        startup.whenReady(executor, observed::add) { throw it }
        startup.whenReady(executor, observed::add) { throw it }

        assertEquals(1, scheduled.size)
        assertEquals(0, starts)
        assertSame(startup.future, startup.future)

        scheduled.removeAt(0).run()
        assertEquals(2, scheduled.size)
        scheduled.removeAt(0).run()
        scheduled.removeAt(0).run()

        assertEquals(1, starts)
        assertEquals(listOf("python-module", "python-module"), observed)
        assertEquals("python-module", startup.future.getNow(null))
    }

    @Test
    fun readyCallbacksStayAsynchronousAndKeepTheOriginalFailure() {
        val scheduled = mutableListOf<Runnable>()
        val executor = Executor { task -> scheduled += task }
        val expected = IllegalStateException("CPython failed")
        val startup = SharedStartup<String>(executor) { throw expected }
        var observed: Throwable? = null

        startup.whenReady(
            executor = executor,
            onReady = { throw AssertionError("startup should have failed") },
            onFailure = { observed = it },
        )

        assertEquals(1, scheduled.size)
        scheduled.removeAt(0).run()
        assertEquals(1, scheduled.size)
        assertTrue(observed == null)

        scheduled.removeAt(0).run()

        assertSame(expected, observed)
    }
}
