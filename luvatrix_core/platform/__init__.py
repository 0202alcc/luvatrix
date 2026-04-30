"""Platform-specific rendering integrations."""

<<<<<<< HEAD
from .frame_pipeline import (
    PresentationMode,
    normalize_presentation_mode,
    prepare_frame_for_extent,
    prepare_pixel_preserve_frame,
    resize_rgba_bilinear,
    resize_rgba_nearest,
)
from .vulkan_compat import SwapchainOutOfDateError, VulkanKHRCompatMixin, decode_vk_string

=======
>>>>>>> codex/t-t-1002-marketbook-renderer
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


def __getattr__(name: str):  # noqa: N807
    if name in ("prepare_frame_for_extent", "resize_rgba_bilinear"):
        from .frame_pipeline import prepare_frame_for_extent, resize_rgba_bilinear  # noqa: PLC0415
        globals()["prepare_frame_for_extent"] = prepare_frame_for_extent
        globals()["resize_rgba_bilinear"] = resize_rgba_bilinear
        return globals()[name]
    if name in ("SwapchainOutOfDateError", "VulkanKHRCompatMixin", "decode_vk_string"):
        from .vulkan_compat import SwapchainOutOfDateError, VulkanKHRCompatMixin, decode_vk_string  # noqa: PLC0415
        globals()["SwapchainOutOfDateError"] = SwapchainOutOfDateError
        globals()["VulkanKHRCompatMixin"] = VulkanKHRCompatMixin
        globals()["decode_vk_string"] = decode_vk_string
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
