package com.luvatrix.app

object NativeCameraProcessor {
    init {
        System.loadLibrary("luvatrix_vulkan_renderer")
    }

    external fun processYuvBurst(
        manifestPath: String,
        outputRgbaPath: String,
        previewRgbaPath: String,
        previewMaxEdge: Int,
    ): String

    external fun processRawBurst(
        manifestPath: String,
        outputRgbaPath: String,
        previewRgbaPath: String,
        previewMaxEdge: Int,
        qualityMode: String,
        demosaicMode: String,
        mergeMode: String,
        renderStyle: String,
        lensShadingMode: String,
    ): String
}
