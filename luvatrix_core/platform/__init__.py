"""Platform-specific rendering integrations."""

__all__ = [
    "PresentationMode",
    "normalize_presentation_mode",
    "prepare_frame_for_extent",
    "prepare_pixel_preserve_frame",
    "resize_rgba_bilinear",
    "resize_rgba_nearest",
    "SwapchainOutOfDateError",
    "VulkanKHRCompatMixin",
    "decode_vk_string",
]

_FRAME_PIPELINE_NAMES = frozenset({
    "PresentationMode",
    "normalize_presentation_mode",
    "prepare_frame_for_extent",
    "prepare_pixel_preserve_frame",
    "resize_rgba_bilinear",
    "resize_rgba_nearest",
})


def __getattr__(name: str):  # noqa: N807
    if name in _FRAME_PIPELINE_NAMES:
        from .frame_pipeline import (  # noqa: PLC0415
            PresentationMode,
            normalize_presentation_mode,
            prepare_frame_for_extent,
            prepare_pixel_preserve_frame,
            resize_rgba_bilinear,
            resize_rgba_nearest,
        )
        globals().update({
            "PresentationMode": PresentationMode,
            "normalize_presentation_mode": normalize_presentation_mode,
            "prepare_frame_for_extent": prepare_frame_for_extent,
            "prepare_pixel_preserve_frame": prepare_pixel_preserve_frame,
            "resize_rgba_bilinear": resize_rgba_bilinear,
            "resize_rgba_nearest": resize_rgba_nearest,
        })
        return globals()[name]
    if name in ("SwapchainOutOfDateError", "VulkanKHRCompatMixin", "decode_vk_string"):
        from .vulkan_compat import SwapchainOutOfDateError, VulkanKHRCompatMixin, decode_vk_string  # noqa: PLC0415
        globals()["SwapchainOutOfDateError"] = SwapchainOutOfDateError
        globals()["VulkanKHRCompatMixin"] = VulkanKHRCompatMixin
        globals()["decode_vk_string"] = decode_vk_string
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
