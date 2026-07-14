package com.luvatrix.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class BootstrapStateTest {
    @Test
    fun retainedScenePromotesWhenSurfaceAttachesWithoutAnotherRevision() {
        val coordinator = SceneReplayCoordinator()
        val scene = coordinator.retainFullScene("scene-json", 7, 393, 852, "retained")

        assertNull(coordinator.presentationRequest(scene))

        coordinator.surfaceChanging(11)
        val replay = coordinator.surfaceAttached(11)

        assertEquals(scene, replay?.scene)
        assertTrue(coordinator.markPresented(replay!!, accepted = true))
        assertTrue(coordinator.isPromoted(scene))
    }

    @Test
    fun staleReplayCannotPromoteAReplacementSceneOrSurface() {
        val coordinator = SceneReplayCoordinator()
        val first = coordinator.retainFullScene("first", 1, 100, 200, "")
        coordinator.surfaceChanging(3)
        val staleReplay = coordinator.surfaceAttached(3)!!

        val replacement = coordinator.retainFullScene("replacement", 2, 100, 200, "")

        assertFalse(coordinator.markPresented(staleReplay, accepted = true))
        assertFalse(coordinator.isPromoted(first))

        val replacementRequest = coordinator.presentationRequest(replacement)!!
        coordinator.surfaceChanging(4)
        assertFalse(coordinator.markPresented(replacementRequest, accepted = true))
        assertFalse(coordinator.isPromoted(replacement))
    }

    @Test
    fun surfaceReplayIncludesTheLatestTransform() {
        val coordinator = SceneReplayCoordinator()
        val scene = coordinator.retainFullScene("scene", 5, 393, 852, "retained")
        val transform = coordinator.retainTransform(6, 12.0, 34.0)!!

        coordinator.surfaceChanging(8)
        val replay = coordinator.surfaceAttached(8)!!

        assertEquals(scene, replay.scene)
        assertEquals(transform, replay.transform)
        assertTrue(coordinator.markPresented(replay, accepted = true))
        assertTrue(coordinator.isPromoted(scene))
    }

    @Test
    fun synchronizedLazyResourceInitializesOnlyOnceAcrossThreads() {
        val starts = AtomicInteger()
        val resource = SynchronizedLazyResource {
            starts.incrementAndGet()
            Any()
        }
        val executor = Executors.newFixedThreadPool(8)
        val ready = CountDownLatch(8)
        val release = CountDownLatch(1)
        try {
            val futures = (0 until 16).map {
                executor.submit<Any> {
                    ready.countDown()
                    release.await(5, TimeUnit.SECONDS)
                    resource.get()
                }
            }
            assertTrue(ready.await(5, TimeUnit.SECONDS))
            release.countDown()
            val values = futures.map { it.get(5, TimeUnit.SECONDS) }

            assertEquals(1, starts.get())
            assertTrue(resource.isInitialized())
            values.forEach { assertSame(values.first(), it) }
        } finally {
            release.countDown()
            executor.shutdownNow()
        }
    }
}
