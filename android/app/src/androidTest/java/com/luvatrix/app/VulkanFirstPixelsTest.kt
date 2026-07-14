package com.luvatrix.app

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class VulkanFirstPixelsTest {
    @Test
    fun vulkanLoaderIsAvailable() {
        assertTrue(NativeVulkan.probeVulkan() > 0)
        println("luvatrix vulkan first pixels ok")
    }

    @Test
    fun vulkanSceneHookIsCallable() {
        assertTrue(!NativeVulkan.presentScene("""[{"type":"clear","color":[0,0,0,255]}]""", 1, 10, 10, ""))
    }
}
