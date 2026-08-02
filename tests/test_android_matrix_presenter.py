from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOTS = (
    ROOT / "android" / "app" / "src" / "main",
    ROOT / "luvatrix_core" / "templates" / "native" / "android" / "app" / "src" / "main",
)


def test_matrix_rgba_uses_direct_vulkan_with_latest_frame_fallback() -> None:
    for android in ANDROID_ROOTS:
        native_api = (android / "java/com/luvatrix/app/NativeVulkan.kt").read_text(encoding="utf-8")
        view = (android / "java/com/luvatrix/app/LuvatrixVulkanView.kt").read_text(encoding="utf-8")
        mailbox = (android / "java/com/luvatrix/app/LatestFrameMailbox.kt").read_text(encoding="utf-8")
        renderer = (android / "cpp/luvatrix_vulkan_renderer.cpp").read_text(encoding="utf-8")
        cmake = (android / "cpp/CMakeLists.txt").read_text(encoding="utf-8")

        assert "external fun presentRgba" in native_api
        assert "external fun presentRgbaRegion" in native_api
        assert "external fun presentRgbaViewport" in native_api
        assert "external fun presentRgbaRegionViewport" in native_api
        assert "external fun presentViewport" in native_api
        assert "NativeVulkan.presentRgba" in view
        assert "NativeVulkan.presentRgbaRegion" in view
        assert "NativeVulkan.presentRgbaViewport" in view
        assert "NativeVulkan.presentRgbaRegionViewport" in view
        assert "NativeVulkan.presentViewport" in view
        assert "rgbaFrameMailbox.offer" in view
        assert "class LatestFrameMailbox" in mailbox
        assert "Java_com_luvatrix_app_NativeVulkan_presentRgba" in renderer
        assert "Java_com_luvatrix_app_NativeVulkan_presentRgbaRegion" in renderer
        assert "Java_com_luvatrix_app_NativeVulkan_presentRgbaViewport" in renderer
        assert "Java_com_luvatrix_app_NativeVulkan_presentRgbaRegionViewport" in renderer
        assert "Java_com_luvatrix_app_NativeVulkan_presentViewport" in renderer
        assert "render_rgba_matrix_region" in renderer
        rgba_renderer = renderer.split("bool render_rgba_matrix_region(", 1)[1].split(
            "\nbool render_rgba_matrix(", 1
        )[0]
        assert "record_overlay_texture_upload" in rgba_renderer
        assert "record_matrix_viewport_blit" in rgba_renderer
        assert "vkQueueWaitIdle" not in rgba_renderer
        rgba_wrapper = renderer.split("bool render_rgba_matrix(", 1)[1].split(
            "\nbool render_clear(", 1
        )[0]
        assert "render_rgba_matrix_region" in rgba_wrapper
        assert "rgba_to_bgra_in_place" in renderer
        assert "vld4q_u8" in renderer
        assert "$<$<CONFIG:Debug>:-O3>" in cmake
