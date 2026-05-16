package com.luvatrix.app

import android.view.Surface

object NativeVulkan {
    init {
        System.loadLibrary("luvatrix_vulkan_renderer")
    }

    external fun probeVulkan(): Int

    external fun setSurface(surface: Surface?)

    external fun presentScene(sceneJson: String, revision: Int, width: Int, height: Int): Boolean
}
