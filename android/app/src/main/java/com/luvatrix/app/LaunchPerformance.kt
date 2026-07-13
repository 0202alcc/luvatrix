package com.luvatrix.app

import java.util.concurrent.ConcurrentHashMap

internal class LaunchTimeline(private val clockNs: () -> Long = System::nanoTime) {
    private val originNs = clockNs()
    private val milestones = ConcurrentHashMap<String, Long>()

    fun mark(name: String) {
        milestones.putIfAbsent(name, (clockNs() - originNs).coerceAtLeast(0L))
    }

    fun snapshot(): Map<String, Long> = milestones.toMap()
}

internal object AndroidLaunchTelemetry {
    private val timeline = LaunchTimeline()

    fun mark(name: String) = timeline.mark(name)

    fun snapshot(): Map<String, Long> = timeline.snapshot()
}

internal class BackgroundStartupRunner(
    private val schedule: ((() -> Unit) -> Unit) = { task ->
        Thread(task, "luvatrix-python-startup").apply { isDaemon = true }.start()
    },
) {
    fun start(task: () -> Unit, onFailure: (Throwable) -> Unit) {
        schedule {
            try {
                task()
            } catch (exc: Throwable) {
                onFailure(exc)
            }
        }
    }
}
