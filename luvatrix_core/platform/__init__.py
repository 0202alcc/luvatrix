"""Platform-specific rendering integrations."""

from .frame_pipeline import (
    PresentationMode,
    normalize_presentation_mode,
    prepare_frame_for_extent,
    prepare_pixel_preserve_frame,
    resize_rgba_bilinear,
    resize_rgba_nearest,
)
from .vulkan_compat import SwapchainOutOfDateError, VulkanKHRCompatMixin, decode_vk_string

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
