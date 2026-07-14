package com.luvatrix.app

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CompletionException
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executor
import java.util.function.Supplier

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

internal class SharedStartup<T>(executor: Executor, initializer: () -> T) {
    val future: CompletableFuture<T> = CompletableFuture.supplyAsync(Supplier(initializer), executor)

    fun whenReady(
        executor: Executor,
        onReady: (T) -> Unit,
        onFailure: (Throwable) -> Unit,
    ) {
        future.whenCompleteAsync({ value, error ->
            if (error == null) {
                onReady(value)
            } else {
                onFailure(unwrapCompletionError(error))
            }
        }, executor)
    }

    fun isSuccessful(): Boolean {
        return future.isDone && !future.isCompletedExceptionally && !future.isCancelled
    }

    private fun unwrapCompletionError(error: Throwable): Throwable {
        var current = error
        while ((current is CompletionException || current is ExecutionException) && current.cause != null) {
            current = current.cause!!
        }
        return current
    }
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
