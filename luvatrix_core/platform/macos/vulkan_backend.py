from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import os
from typing import Any

import torch

from ..frame_pipeline import prepare_frame_for_extent
from ..vulkan_compat import SwapchainOutOfDateError, VulkanKHRCompatMixin, decode_vk_string
from .vulkan_presenter import VulkanContext
from .window_system import AppKitWindowSystem, MacOSWindowHandle, MacOSWindowSystem

LOGGER = logging.getLogger(__name__)


@dataclass
class MoltenVKMacOSBackend(VulkanKHRCompatMixin):
    """Concrete macOS Vulkan backend scaffold.

    This class wires the exact lifecycle sequence we want for real Vulkan work.
    Low-level methods are intentionally stubbed until platform bindings are added.
    """

    _initialized: bool = False
    _frames_presented: int = 0
    window_system: MacOSWindowSystem | None = None
    preserve_aspect_ratio: bool = False

    def __post_init__(self) -> None:
        self._window_handle: MacOSWindowHandle | None = None
        self._pending_rgba: torch.Tensor | None = None
        self._vulkan_available = False
        self._vulkan_note: str | None = None
        self._vk: Any | None = None
        self._instance = None
        self._physical_device = None
        self._queue_family_index: int | None = None
        self._logical_device = None
        self._graphics_queue = None
        self._surface = None
        self._swapchain = None
        self._swapchain_images: list[Any] = []
        self._swapchain_image_format = None
        self._swapchain_extent: tuple[int, int] | None = None
        self._current_image_index: int | None = None
        self._command_pool = None
        self._command_buffers: list[Any] = []
        self._image_available_semaphore = None
        self._render_finished_semaphore = None
        self._in_flight_fence = None
        self._staging_buffer = None
        self._staging_memory = None
        self._staging_size = 0
        self._upload_extent: tuple[int, int] = (0, 0)
        self._clear_color = (0.0, 0.0, 0.0, 1.0)
        self._vk_proc_cache: dict[str, Any] = {}
        self._frame_wait_timeout_ns = 50_000_000  # 50ms safety bound to keep UI responsive
        self._consecutive_acquire_timeouts = 0
        self._fallback_last_cf_data = None
        self._fallback_last_image = None
        self._fallback_last_ns_image = None
        self._fallback_blit_layer = None
        self._fallback_blit_view = None
        self._fallback_image_view = None
        self._fallback_replaced_content_layer = False
        self._active_present_path: str | None = None
        if self.window_system is None:
            self.window_system = AppKitWindowSystem()

    def initialize(self, width: int, height: int, title: str) -> VulkanContext:
        if self._initialized:
            return VulkanContext(width=width, height=height, title=title)

        self._validate_dimensions(width, height)
        self._create_vulkan_instance()
        self._create_window(width, height, title)
        self._create_surface()
        self._pick_physical_device()
        self._create_logical_device()
        self._create_swapchain(width, height)
        self._create_command_resources()
        self._create_sync_primitives()
        self._initialized = True
        return VulkanContext(width=width, height=height, title=title)

    def present(self, context: VulkanContext, rgba: torch.Tensor, revision: int) -> None:
        self._require_initialized()
        self._validate_frame(rgba, context.width, context.height)
        self._acquire_next_swapchain_image()
        if self._vulkan_available and self._current_image_index is None:
            return
        self._upload_rgba_to_staging(rgba)
        self._record_and_submit_commands(revision=revision)
        self._present_swapchain_image()
        self._frames_presented += 1

    def resize(self, context: VulkanContext, width: int, height: int) -> VulkanContext:
        self._require_initialized()
        self._validate_dimensions(width, height)
        self._wait_device_idle()
        self._recreate_swapchain(width, height)
        return VulkanContext(width=width, height=height, title=context.title)

    def shutdown(self, context: VulkanContext) -> None:
        if not self._initialized:
            return
        self._wait_device_idle()
        self._destroy_sync_primitives()
        self._destroy_command_resources()
        self._destroy_swapchain()
        self._destroy_surface()
        self._destroy_device()
        self._destroy_instance()
        self._destroy_window()
        self._initialized = False

    @property
    def frames_presented(self) -> int:
        return self._frames_presented

    def pump_events(self) -> None:
        if self.window_system is None:
            return
        self.window_system.pump_events()

    def should_close(self) -> bool:
        if self._window_handle is None or self.window_system is None:
            return True
        return not self.window_system.is_window_open(self._window_handle)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("MoltenVKMacOSBackend is not initialized")

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be > 0")

    def _validate_frame(self, rgba: torch.Tensor, width: int, height: int) -> None:
        if not torch.is_tensor(rgba):
            raise ValueError("rgba frame must be a torch.Tensor")
        if rgba.dtype != torch.uint8:
            raise ValueError(f"rgba frame must use torch.uint8, got {rgba.dtype}")
        if tuple(rgba.shape) != (height, width, 4):
            raise ValueError(f"rgba frame shape mismatch: got {tuple(rgba.shape)} expected {(height, width, 4)}")

    def _create_window(self, width: int, height: int, title: str) -> None:
        assert self.window_system is not None
        self._window_handle = self.window_system.create_window(
            width,
            height,
            title,
            use_metal_layer=True,
            preserve_aspect_ratio=self.preserve_aspect_ratio,
        )

    def _create_vulkan_instance(self) -> None:
        if self._vk is None:
            try:
                import vulkan as _vk  # type: ignore
            except Exception as exc:  # noqa: BLE001
                self._vulkan_available = False
                self._vulkan_note = (
                    "Python Vulkan bindings not available. Install with `uv add vulkan` and ensure MoltenVK "
                    "runtime is installed. Running in temporary layer-blit mode."
                )
                LOGGER.warning("%s (%s)", self._vulkan_note, exc)
                return
            self._vk = _vk
        # Until the Vulkan command/swapchain path is fully implemented, default to
        # safe fallback rendering even when bindings are available.
        if os.getenv("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", "0") == "1":
            if not self._supports_macos_surface_symbols():
                self._vulkan_available = False
                self._vulkan_note = (
                    "Experimental Vulkan requested, but python Vulkan bindings are missing macOS surface symbols. "
                    "Falling back to layer-blit mode."
                )
                LOGGER.warning("%s", self._vulkan_note)
                return
            if not self._supports_required_khr_path():
                self._vulkan_available = False
                self._vulkan_note = (
                    "Experimental Vulkan requested, but python Vulkan bindings are missing required KHR "
                    "surface/swapchain call path. Falling back to layer-blit mode."
                )
                LOGGER.warning("%s", self._vulkan_note)
                return
            self._vulkan_available = True
            LOGGER.warning(
                "Experimental Vulkan mode enabled. Rendering correctness is not guaranteed yet."
            )
            try:
                self._instance = self._vk_create_instance()
            except Exception as exc:  # noqa: BLE001
                self._vulkan_available = False
                self._vulkan_note = (
                    "Experimental Vulkan requested, but instance initialization failed. "
                    "Falling back to layer-blit mode."
                )
                LOGGER.warning("%s (%s)", self._vulkan_note, exc)
        else:
            self._vulkan_available = False
            self._vulkan_note = (
                "Vulkan bindings found, but backend path is still under construction. "
                "Using fallback layer-blit mode. Set LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN=1 to force Vulkan."
            )
            LOGGER.warning("%s", self._vulkan_note)

    def _pick_physical_device(self) -> None:
        if not self._vulkan_available:
            return
        if self._instance is None:
            raise RuntimeError("Vulkan instance is not initialized")
        if self._surface is None:
            raise RuntimeError("Vulkan surface is not initialized")
        vk = self._require_vk()
        devices = vk.vkEnumeratePhysicalDevices(self._instance)
        if not devices:
            raise RuntimeError("no Vulkan physical devices found")
        selected_device = None
        selected_queue_index: int | None = None
        for device in devices:
            queue_props = vk.vkGetPhysicalDeviceQueueFamilyProperties(device)
            for idx, props in enumerate(queue_props):
                if props.queueCount <= 0:
                    continue
                if props.queueFlags & vk.VK_QUEUE_GRAPHICS_BIT:
                    if self._vk_get_physical_device_surface_support(device, idx, self._surface):
                        selected_device = device
                        selected_queue_index = int(idx)
                        break
            if selected_device is not None:
                break
        if selected_device is None or selected_queue_index is None:
            raise RuntimeError("no Vulkan graphics+present queue family found")
        self._physical_device = selected_device
        self._queue_family_index = selected_queue_index

    def _create_logical_device(self) -> None:
        if not self._vulkan_available:
            return
        if self._physical_device is None or self._queue_family_index is None:
            raise RuntimeError("physical device/queue family not selected")
        vk = self._require_vk()
        queue_priority = [1.0]
        queue_ci = vk.VkDeviceQueueCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            queueFamilyIndex=self._queue_family_index,
            queueCount=1,
            pQueuePriorities=queue_priority,
        )
        ext_props = vk.vkEnumerateDeviceExtensionProperties(self._physical_device, None)
        available_exts = {decode_vk_string(p.extensionName) for p in ext_props}
        enabled_exts: list[str] = []
        if getattr(vk, "VK_KHR_SWAPCHAIN_EXTENSION_NAME", "VK_KHR_swapchain") in available_exts:
            enabled_exts.append(getattr(vk, "VK_KHR_SWAPCHAIN_EXTENSION_NAME", "VK_KHR_swapchain"))
        else:
            raise RuntimeError("VK_KHR_swapchain device extension not available")
        portability_subset = "VK_KHR_portability_subset"
        if portability_subset in available_exts:
            enabled_exts.append(portability_subset)

        device_ci = vk.VkDeviceCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            queueCreateInfoCount=1,
            pQueueCreateInfos=[queue_ci],
            enabledExtensionCount=len(enabled_exts),
            ppEnabledExtensionNames=enabled_exts,
            pEnabledFeatures=None,
        )
        self._logical_device = vk.vkCreateDevice(self._physical_device, device_ci, None)
        self._graphics_queue = vk.vkGetDeviceQueue(self._logical_device, self._queue_family_index, 0)

    def _create_surface(self) -> None:
        if not self._vulkan_available:
            return
        if self._window_handle is None:
            raise RuntimeError("window handle missing while creating Vulkan surface")
        if self._instance is None:
            raise RuntimeError("Vulkan instance is not initialized")
        vk = self._require_vk()
        try:
            import objc  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("PyObjC `objc` module is required to build a metal surface") from exc

        errors: list[str] = []

        # Preferred path: VK_EXT_metal_surface + CAMetalLayer.
        metal_surface_ci_type = getattr(vk, "VkMetalSurfaceCreateInfoEXT", None)
        metal_surface_stype = getattr(vk, "VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT", None)
        create_metal_surface_fn = getattr(vk, "vkCreateMetalSurfaceEXT", None)
        if (
            metal_surface_ci_type is not None
            and metal_surface_stype is not None
            and create_metal_surface_fn is not None
        ):
            try:
                layer_ptr = objc.pyobjc_id(self._window_handle.layer)
                ci = metal_surface_ci_type(
                    sType=metal_surface_stype,
                    pNext=None,
                    flags=0,
                    pLayer=layer_ptr,
                )
                self._surface = create_metal_surface_fn(self._instance, ci, None)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"VK_EXT_metal_surface failed: {exc}")

        # Compatibility path: VK_MVK_macos_surface + NSView.
        macos_surface_ci_type = getattr(vk, "VkMacOSSurfaceCreateInfoMVK", None)
        macos_surface_stype = getattr(vk, "VK_STRUCTURE_TYPE_MACOS_SURFACE_CREATE_INFO_MVK", None)
        create_macos_surface_fn = getattr(vk, "vkCreateMacOSSurfaceMVK", None)
        if (
            macos_surface_ci_type is not None
            and macos_surface_stype is not None
            and create_macos_surface_fn is not None
        ):
            try:
                view = self._window_handle.window.contentView()
                view_ptr = objc.pyobjc_id(view)
                ci = macos_surface_ci_type(
                    sType=macos_surface_stype,
                    pNext=None,
                    flags=0,
                    pView=view_ptr,
                )
                self._surface = create_macos_surface_fn(self._instance, ci, None)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"VK_MVK_macos_surface failed: {exc}")

        # Last-resort path for slim python bindings: call extension procedures
        # directly through the Vulkan loader with ctypes.
        try:
            self._surface = self._create_surface_via_ctypes(prefer_metal=True)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ctypes metal surface failed: {exc}")
        try:
            self._surface = self._create_surface_via_ctypes(prefer_metal=False)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ctypes macos surface failed: {exc}")

        detail = "; ".join(errors) if errors else "missing surface create symbols"
        raise RuntimeError(f"Unable to create macOS Vulkan surface ({detail})")

    def _create_swapchain(self, width: int, height: int) -> None:
        if not self._vulkan_available:
            return
        if self._physical_device is None or self._logical_device is None or self._surface is None:
            raise RuntimeError("Vulkan swapchain prerequisites are not initialized")
        vk = self._require_vk()
        caps = self._vk_get_surface_capabilities(self._physical_device, self._surface)
        formats = self._vk_get_surface_formats(self._physical_device, self._surface)
        present_modes = self._vk_get_surface_present_modes(self._physical_device, self._surface)
        if not formats:
            raise RuntimeError("no Vulkan surface formats available")

        normalized_formats: list[tuple[int, int]] = []
        for f in formats:
            try:
                normalized_formats.append((int(f.format), int(f.colorSpace)))
            except Exception:  # noqa: BLE001
                continue

        preferred_format = None
        for f in formats:
            if (
                f.format == getattr(vk, "VK_FORMAT_B8G8R8A8_UNORM", f.format)
                and f.colorSpace == getattr(vk, "VK_COLOR_SPACE_SRGB_NONLINEAR_KHR", f.colorSpace)
            ):
                preferred_format = f
                break
        if preferred_format is None:
            preferred_format = formats[0]
        preferred_format_value = int(preferred_format.format)
        preferred_colorspace_value = int(preferred_format.colorSpace)

        # MoltenVK can crash during swapchain init if imageFormat is invalid garbage.
        # Clamp to a known-safe default when queried data is malformed.
        safe_default_format = int(getattr(vk, "VK_FORMAT_B8G8R8A8_UNORM", 44))
        safe_default_colorspace = int(getattr(vk, "VK_COLOR_SPACE_SRGB_NONLINEAR_KHR", 0))
        if preferred_format_value <= 0 or preferred_format_value > 1_000_000:
            preferred_format_value = safe_default_format
            preferred_colorspace_value = safe_default_colorspace
        if normalized_formats and (preferred_format_value, preferred_colorspace_value) not in normalized_formats:
            # Prefer known-good default on Apple path if advertised formats look suspicious.
            if (safe_default_format, safe_default_colorspace) in normalized_formats:
                preferred_format_value = safe_default_format
                preferred_colorspace_value = safe_default_colorspace

        current_extent_w = int(caps.currentExtent.width)
        if current_extent_w != 0xFFFFFFFF:
            extent_w = int(caps.currentExtent.width)
            extent_h = int(caps.currentExtent.height)
        else:
            extent_w = max(int(caps.minImageExtent.width), min(width, int(caps.maxImageExtent.width)))
            extent_h = max(int(caps.minImageExtent.height), min(height, int(caps.maxImageExtent.height)))

        image_count = int(caps.minImageCount) + 1
        if int(caps.maxImageCount) > 0 and image_count > int(caps.maxImageCount):
            image_count = int(caps.maxImageCount)

        composite_alpha = getattr(vk, "VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR", 0x1)
        present_mode_fifo = getattr(vk, "VK_PRESENT_MODE_FIFO_KHR", 2)
        present_mode = present_mode_fifo if present_mode_fifo in present_modes else present_modes[0]

        image_usage = getattr(vk, "VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT", 0x10)
        image_usage |= getattr(vk, "VK_IMAGE_USAGE_TRANSFER_DST_BIT", 0x00000002)
        ci = vk.VkSwapchainCreateInfoKHR(
            sType=vk.VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
            surface=self._surface,
            minImageCount=image_count,
            imageFormat=preferred_format_value,
            imageColorSpace=preferred_colorspace_value,
            imageExtent=(extent_w, extent_h),
            imageArrayLayers=1,
            imageUsage=image_usage,
            imageSharingMode=getattr(vk, "VK_SHARING_MODE_EXCLUSIVE", 0),
            queueFamilyIndexCount=0,
            pQueueFamilyIndices=None,
            preTransform=caps.currentTransform,
            compositeAlpha=composite_alpha,
            presentMode=present_mode,
            clipped=vk.VK_TRUE,
            oldSwapchain=getattr(vk, "VK_NULL_HANDLE", 0),
        )
        self._swapchain = self._vk_create_swapchain(self._logical_device, ci)
        self._swapchain_images = list(self._vk_get_swapchain_images(self._logical_device, self._swapchain))
        self._swapchain_image_format = preferred_format_value
        self._swapchain_extent = (extent_w, extent_h)

    def _create_command_resources(self) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None or self._queue_family_index is None:
            raise RuntimeError("logical device/queue family missing for command resources")
        vk = self._require_vk()
        pool_ci = vk.VkCommandPoolCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            flags=0,
            queueFamilyIndex=self._queue_family_index,
        )
        self._command_pool = vk.vkCreateCommandPool(self._logical_device, pool_ci, None)
        if self._swapchain_images:
            alloc_info = vk.VkCommandBufferAllocateInfo(
                sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                commandPool=self._command_pool,
                level=getattr(vk, "VK_COMMAND_BUFFER_LEVEL_PRIMARY", 0),
                commandBufferCount=len(self._swapchain_images),
            )
            self._command_buffers = list(vk.vkAllocateCommandBuffers(self._logical_device, alloc_info))

    def _create_sync_primitives(self) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None:
            raise RuntimeError("logical device missing for sync primitives")
        vk = self._require_vk()
        sem_ci = vk.VkSemaphoreCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO,
            pNext=None,
            flags=0,
        )
        fence_ci = vk.VkFenceCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
            pNext=None,
            flags=getattr(vk, "VK_FENCE_CREATE_SIGNALED_BIT", 0x1),
        )
        self._image_available_semaphore = vk.vkCreateSemaphore(self._logical_device, sem_ci, None)
        self._render_finished_semaphore = vk.vkCreateSemaphore(self._logical_device, sem_ci, None)
        self._in_flight_fence = vk.vkCreateFence(self._logical_device, fence_ci, None)

    def _acquire_next_swapchain_image(self) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None or self._swapchain is None:
            raise RuntimeError("swapchain not created")
        if self._in_flight_fence is None or self._image_available_semaphore is None:
            raise RuntimeError("sync primitives not initialized")
        vk = self._require_vk()
        if not self._vk_wait_for_fence(self._logical_device, self._in_flight_fence, self._frame_wait_timeout_ns):
            self._current_image_index = None
            self._consecutive_acquire_timeouts += 1
            if self._consecutive_acquire_timeouts >= 3:
                self._handle_swapchain_invalidation()
            return
        try:
            acquired = self._vk_acquire_next_image(
                self._logical_device,
                self._swapchain,
                self._frame_wait_timeout_ns,
                self._image_available_semaphore,
                getattr(vk, "VK_NULL_HANDLE", 0),
            )
        except SwapchainOutOfDateError:
            self._current_image_index = None
            self._consecutive_acquire_timeouts = 0
            self._handle_swapchain_invalidation()
            return
        if acquired is None:
            self._current_image_index = None
            self._consecutive_acquire_timeouts += 1
            if self._consecutive_acquire_timeouts >= 3:
                self._handle_swapchain_invalidation()
            return
        if isinstance(acquired, tuple) and len(acquired) >= 2:
            result_code = int(acquired[0])
            if result_code == int(getattr(vk, "VK_SUBOPTIMAL_KHR", 1000001003)):
                self._current_image_index = None
                self._consecutive_acquire_timeouts = 0
                self._handle_swapchain_invalidation()
                return
        self._consecutive_acquire_timeouts = 0
        self._current_image_index = int(self._coerce_image_index(acquired))

    def _handle_swapchain_invalidation(self) -> None:
        if not self._vulkan_available or self._logical_device is None:
            return
        self._consecutive_acquire_timeouts = 0
        width, height = self._resolve_surface_size()
        if width <= 0 or height <= 0:
            return
        try:
            # Avoid blocking app responsiveness while user is actively resizing.
            self._recreate_swapchain(width, height)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("swapchain recreation failed; falling back to layer-blit: %s", exc)
            self._vulkan_available = False
            self._vulkan_note = "Swapchain recreation failed; fallback layer-blit mode enabled."

    def _resolve_surface_size(self) -> tuple[int, int]:
        if self._window_handle is not None:
            try:
                view = self._window_handle.window.contentView()
                bounds = view.bounds()
                width = int(max(1, round(float(bounds.size.width))))
                height = int(max(1, round(float(bounds.size.height))))
                return (width, height)
            except Exception:  # noqa: BLE001
                pass
        if self._swapchain_extent is not None:
            return self._swapchain_extent
        return (1, 1)

    def _upload_rgba_to_staging(self, rgba: torch.Tensor) -> None:
        # Always keep a copy available for fallback layer presentation.
        self._pending_rgba = rgba.contiguous().clone()
        if not self._vulkan_available:
            return
        if self._logical_device is None or self._physical_device is None:
            raise RuntimeError("Vulkan device not initialized for staging upload")
        vk = self._require_vk()
        rgba_upload = self._prepare_upload_frame(rgba)
        # Swap R/B when swapchain format is BGRA so colors remain correct.
        if self._swapchain_image_format in (
            int(getattr(vk, "VK_FORMAT_B8G8R8A8_UNORM", 44)),
            int(getattr(vk, "VK_FORMAT_B8G8R8A8_SRGB", 50)),
        ):
            rgba_upload = rgba_upload[:, :, [2, 1, 0, 3]].contiguous()
        height, width, _ = rgba_upload.shape
        upload_h, upload_w = height, width
        if self._swapchain_extent is not None:
            swap_w, swap_h = self._swapchain_extent
            upload_w = min(upload_w, swap_w)
            upload_h = min(upload_h, swap_h)
        if upload_w <= 0 or upload_h <= 0:
            raise RuntimeError("invalid upload extent for Vulkan staging upload")
        clipped = rgba_upload[:upload_h, :upload_w, :].contiguous()
        data = bytes(clipped.reshape(-1).tolist())
        self._ensure_staging_buffer(len(data))
        mapped_ptr = vk.vkMapMemory(
            self._logical_device,
            self._staging_memory,
            0,
            len(data),
            0,
        )
        try:
            # vulkan-python returns ffi.buffer(...) for vkMapMemory on some builds.
            mapped_cdata = vk.ffi.from_buffer(mapped_ptr)
            vk.ffi.memmove(mapped_cdata, data, len(data))
        except Exception:
            # Fallback for bindings that return an integer-like pointer.
            dest_ptr = ctypes.c_void_p(int(mapped_ptr))
            ctypes.memmove(dest_ptr, data, len(data))
        finally:
            vk.vkUnmapMemory(self._logical_device, self._staging_memory)
        self._upload_extent = (upload_w, upload_h)
        rgbaf = rgba_upload.to(torch.float32).mean(dim=(0, 1)) / 255.0
        self._clear_color = (
            float(rgbaf[0].item()),
            float(rgbaf[1].item()),
            float(rgbaf[2].item()),
            float(rgbaf[3].item()),
        )

    def _prepare_upload_frame(self, rgba: torch.Tensor) -> torch.Tensor:
        if self._swapchain_extent is None:
            return rgba
        swap_w, swap_h = self._swapchain_extent
        if swap_w <= 0 or swap_h <= 0:
            return rgba
        return prepare_frame_for_extent(
            rgba,
            target_w=swap_w,
            target_h=swap_h,
            preserve_aspect_ratio=self.preserve_aspect_ratio,
        )

    def _record_and_submit_commands(self, revision: int) -> None:
        if not self._vulkan_available:
            return
        vk = self._require_vk()
        if (
            self._logical_device is None
            or self._graphics_queue is None
            or self._current_image_index is None
            or self._in_flight_fence is None
            or self._image_available_semaphore is None
            or self._render_finished_semaphore is None
        ):
            raise RuntimeError("Vulkan submit prerequisites are not initialized")
        if not self._command_buffers:
            raise RuntimeError("No Vulkan command buffers were allocated")
        cmd = self._command_buffers[self._current_image_index]
        image = self._swapchain_images[self._current_image_index]
        vk.vkResetCommandBuffer(cmd, 0)
        begin_info = vk.VkCommandBufferBeginInfo(
            sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            flags=0,
            pInheritanceInfo=None,
        )
        vk.vkBeginCommandBuffer(cmd, begin_info)
        subresource_range = vk.VkImageSubresourceRange(
            aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
            baseMipLevel=0,
            levelCount=1,
            baseArrayLayer=0,
            layerCount=1,
        )
        barrier_to_clear = vk.VkImageMemoryBarrier(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            srcAccessMask=0,
            dstAccessMask=getattr(vk, "VK_ACCESS_TRANSFER_WRITE_BIT", 0x1000),
            oldLayout=getattr(vk, "VK_IMAGE_LAYOUT_UNDEFINED", 0),
            newLayout=getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            srcQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            dstQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            image=image,
            subresourceRange=subresource_range,
        )
        vk.vkCmdPipelineBarrier(
            cmd,
            getattr(vk, "VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT", 0x1),
            getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000),
            0,
            0,
            None,
            0,
            None,
            1,
            [barrier_to_clear],
        )
        clear = vk.VkClearColorValue(float32=list(self._clear_color))
        vk.vkCmdClearColorImage(
            cmd,
            image,
            getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            clear,
            1,
            [subresource_range],
        )
        if self._staging_buffer is not None and self._upload_extent[0] > 0 and self._upload_extent[1] > 0:
            copy_region = vk.VkBufferImageCopy(
                bufferOffset=0,
                bufferRowLength=0,
                bufferImageHeight=0,
                imageSubresource=vk.VkImageSubresourceLayers(
                    aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
                    mipLevel=0,
                    baseArrayLayer=0,
                    layerCount=1,
                ),
                imageOffset=(0, 0, 0),
                imageExtent=(self._upload_extent[0], self._upload_extent[1], 1),
            )
            vk.vkCmdCopyBufferToImage(
                cmd,
                self._staging_buffer,
                image,
                getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
                1,
                [copy_region],
            )
        barrier_to_present = vk.VkImageMemoryBarrier(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            srcAccessMask=getattr(vk, "VK_ACCESS_TRANSFER_WRITE_BIT", 0x1000),
            dstAccessMask=0,
            oldLayout=getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            newLayout=getattr(vk, "VK_IMAGE_LAYOUT_PRESENT_SRC_KHR", 1000001002),
            srcQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            dstQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            image=image,
            subresourceRange=subresource_range,
        )
        vk.vkCmdPipelineBarrier(
            cmd,
            getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000),
            getattr(vk, "VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT", 0x2000),
            0,
            0,
            None,
            0,
            None,
            1,
            [barrier_to_present],
        )
        vk.vkEndCommandBuffer(cmd)
        submit = vk.VkSubmitInfo(
            sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO,
            waitSemaphoreCount=1,
            pWaitSemaphores=[self._image_available_semaphore],
            pWaitDstStageMask=[getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000)],
            commandBufferCount=1,
            pCommandBuffers=[cmd],
            signalSemaphoreCount=1,
            pSignalSemaphores=[self._render_finished_semaphore],
        )
        self._vk_reset_fence(self._logical_device, self._in_flight_fence)
        vk.vkQueueSubmit(self._graphics_queue, 1, [submit], self._in_flight_fence)

    def _present_swapchain_image(self) -> None:
        if self._vulkan_available:
            self._set_active_present_path("vulkan")
            vk = self._require_vk()
            if (
                self._graphics_queue is None
                or self._swapchain is None
                or self._render_finished_semaphore is None
                or self._current_image_index is None
            ):
                raise RuntimeError("Vulkan present prerequisites are not initialized")
            present_info = vk.VkPresentInfoKHR(
                sType=vk.VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
                waitSemaphoreCount=1,
                pWaitSemaphores=[self._render_finished_semaphore],
                swapchainCount=1,
                pSwapchains=[self._swapchain],
                pImageIndices=[self._current_image_index],
                pResults=None,
            )
            try:
                self._vk_queue_present(self._graphics_queue, present_info)
            except SwapchainOutOfDateError:
                self._handle_swapchain_invalidation()
            return
        self._present_fallback_to_layer()

    def _wait_device_idle(self) -> None:
        if not self._vulkan_available:
            return
        vk = self._require_vk()
        if self._logical_device is not None:
            vk.vkDeviceWaitIdle(self._logical_device)

    def _recreate_swapchain(self, width: int, height: int) -> None:
        if not self._vulkan_available:
            return
        self._destroy_command_resources()
        self._destroy_swapchain()
        self._create_swapchain(width, height)
        self._create_command_resources()

    def _destroy_sync_primitives(self) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None:
            return
        vk = self._require_vk()
        if self._in_flight_fence is not None:
            vk.vkDestroyFence(self._logical_device, self._in_flight_fence, None)
            self._in_flight_fence = None
        if self._render_finished_semaphore is not None:
            vk.vkDestroySemaphore(self._logical_device, self._render_finished_semaphore, None)
            self._render_finished_semaphore = None
        if self._image_available_semaphore is not None:
            vk.vkDestroySemaphore(self._logical_device, self._image_available_semaphore, None)
            self._image_available_semaphore = None

    def _destroy_command_resources(self) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None:
            return
        vk = self._require_vk()
        self._destroy_staging_resources()
        if self._command_pool is not None:
            vk.vkDestroyCommandPool(self._logical_device, self._command_pool, None)
            self._command_pool = None
            self._command_buffers = []

    def _destroy_swapchain(self) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None:
            return
        vk = self._require_vk()
        if self._swapchain is not None:
            self._vk_destroy_swapchain(self._logical_device, self._swapchain)
            self._swapchain = None
            self._swapchain_images = []
            self._swapchain_extent = None
            self._swapchain_image_format = None
            self._current_image_index = None

    def _destroy_surface(self) -> None:
        if not self._vulkan_available:
            return
        if self._instance is None:
            return
        vk = self._require_vk()
        if self._surface is not None:
            self._vk_destroy_surface(self._instance, self._surface)
            self._surface = None

    def _destroy_device(self) -> None:
        if not self._vulkan_available:
            return
        vk = self._require_vk()
        if self._logical_device is not None:
            vk.vkDestroyDevice(self._logical_device, None)
            self._logical_device = None
            self._graphics_queue = None

    def _destroy_instance(self) -> None:
        if not self._vulkan_available:
            return
        vk = self._require_vk()
        if self._instance is not None:
            vk.vkDestroyInstance(self._instance, None)
            self._instance = None
            self._physical_device = None
            self._queue_family_index = None

    def _destroy_window(self) -> None:
        if self._window_handle is None:
            return
        assert self.window_system is not None
        self.window_system.destroy_window(self._window_handle)
        self._window_handle = None
        self._fallback_blit_layer = None
        self._fallback_blit_view = None
        self._fallback_image_view = None
        self._fallback_last_ns_image = None
        self._fallback_replaced_content_layer = False
        self._active_present_path = None

    def _present_fallback_to_layer(self) -> None:
        if self._window_handle is None or self._pending_rgba is None:
            return
        host_layer = self._window_handle.layer
        try:
            import Quartz  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Quartz not available for fallback layer presentation") from exc

        legacy_enabled = os.getenv("LUVATRIX_ENABLE_LEGACY_CAMETAL_FALLBACK", "0").strip() == "1"
        target_layer = host_layer
        is_metal_host = type(host_layer).__name__ == "CAMetalLayer"
        if legacy_enabled:
            self._set_active_present_path("fallback_legacy")
        else:
            self._set_active_present_path("fallback_clean")

        rgba = self._pending_rgba
        height, width, _ = rgba.shape
        try:
            content_view = self._window_handle.window.contentView()
            bounds = content_view.bounds()
            host_layer.setFrame_(bounds)
            if target_layer is not host_layer:
                target_layer.setFrame_(bounds)
            try:
                scale = float(self._window_handle.window.backingScaleFactor())
                host_layer.setContentsScale_(scale)
                if target_layer is not host_layer:
                    target_layer.setContentsScale_(scale)
            except Exception:
                pass
        except Exception:
            pass
        # Fast path: avoid Python per-element conversion when building CGImage bytes.
        data = rgba.contiguous().cpu().numpy().tobytes(order="C")
        cf_data = Quartz.CFDataCreate(None, data, len(data))
        provider = Quartz.CGDataProviderCreateWithCFData(cf_data)
        color_space = Quartz.CGColorSpaceCreateDeviceRGB()
        bitmap_info = Quartz.kCGBitmapByteOrder32Big | Quartz.kCGImageAlphaPremultipliedLast
        image = Quartz.CGImageCreate(
            width,
            height,
            8,
            32,
            width * 4,
            color_space,
            bitmap_info,
            provider,
            None,
            True,
            Quartz.kCGRenderingIntentDefault,
        )
        if image is None:
            raise RuntimeError("failed to build fallback CGImage")
        self._fallback_last_cf_data = cf_data
        self._fallback_last_image = image
        if is_metal_host and not legacy_enabled:
            # Preferred clean path for CAMetal-hosted windows.
            if self._present_fallback_image_view(Quartz, image, width, height):
                return
            # Secondary clean path when NSImageView bridging is unavailable.
            target_layer = self._ensure_clean_fallback_surface(Quartz)
        target_layer.setContents_(image)
        try:
            target_layer.setNeedsDisplay()
        except Exception:
            pass

    def _present_fallback_image_view(self, quartz_module, cg_image: object, image_w: int, image_h: int) -> bool:
        if self._window_handle is None:
            return False
        try:
            from AppKit import (  # type: ignore
                NSImage,
                NSImageScaleAxesIndependently,
                NSImageScaleProportionallyUpOrDown,
                NSImageView,
                NSMakeRect,
                NSViewHeightSizable,
                NSViewWidthSizable,
            )
        except Exception:
            return False
        try:
            content_view = self._window_handle.window.contentView()
            bounds = content_view.bounds()
            if self._fallback_image_view is None:
                image_view = NSImageView.alloc().initWithFrame_(
                    NSMakeRect(0.0, 0.0, float(bounds.size.width), float(bounds.size.height))
                )
                image_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
                image_view.setImageScaling_(
                    NSImageScaleProportionallyUpOrDown if self.preserve_aspect_ratio else NSImageScaleAxesIndependently
                )
                content_view.addSubview_(image_view)
                self._fallback_image_view = image_view
                if self.preserve_aspect_ratio:
                    try:
                        content_view.setWantsLayer_(True)
                        content_view.layer().setBackgroundColor_(quartz_module.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 1.0))
                    except Exception:
                        pass
            self._fallback_image_view.setFrame_(bounds)
            ns_image = NSImage.alloc().initWithCGImage_size_(cg_image, (float(image_w), float(image_h)))
            self._fallback_last_ns_image = ns_image
            self._fallback_image_view.setImage_(ns_image)
            return True
        except Exception:
            return False

    def _ensure_clean_fallback_surface(self, quartz_module) -> object:
        if self._fallback_blit_layer is not None:
            return self._fallback_blit_layer
        if self._window_handle is None:
            raise RuntimeError("window handle missing for clean fallback surface")
        host_layer = self._window_handle.layer
        content_view = self._window_handle.window.contentView()
        bounds = content_view.bounds()
        # Most robust path: replace content view's layer with a dedicated CALayer
        # while in fallback mode. This avoids CAMetalLayer contents mutation entirely.
        try:
            fallback_layer = quartz_module.CALayer.layer()
            fallback_layer.setFrame_(bounds)
            fallback_layer.setContentsGravity_("resizeAspect" if self.preserve_aspect_ratio else "resize")
            if self.preserve_aspect_ratio:
                try:
                    fallback_layer.setBackgroundColor_(quartz_module.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 1.0))
                except Exception:
                    pass
            content_view.setWantsLayer_(True)
            content_view.setLayer_(fallback_layer)
            self._fallback_blit_layer = fallback_layer
            self._fallback_replaced_content_layer = True
            return self._fallback_blit_layer
        except Exception:
            pass

        view_added = False
        try:
            from AppKit import NSMakeRect, NSView, NSViewHeightSizable, NSViewWidthSizable  # type: ignore

            fallback_view = NSView.alloc().initWithFrame_(
                NSMakeRect(0.0, 0.0, float(bounds.size.width), float(bounds.size.height))
            )
            fallback_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            fallback_view.setWantsLayer_(True)
            fallback_layer = quartz_module.CALayer.layer()
            fallback_layer.setFrame_(fallback_view.bounds())
            fallback_layer.setContentsGravity_("resizeAspect" if self.preserve_aspect_ratio else "resize")
            if self.preserve_aspect_ratio:
                try:
                    fallback_layer.setBackgroundColor_(quartz_module.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 1.0))
                except Exception:
                    pass
            fallback_view.setLayer_(fallback_layer)
            try:
                from AppKit import NSWindowAbove  # type: ignore

                content_view.addSubview_positioned_relativeTo_(fallback_view, NSWindowAbove, None)
            except Exception:
                content_view.addSubview_(fallback_view)
            self._fallback_blit_view = fallback_view
            self._fallback_blit_layer = fallback_layer
            view_added = True
        except Exception:
            view_added = False

        if not view_added:
            # Secondary clean path: child CALayer (still avoids writing host CAMetalLayer contents).
            fallback_layer = quartz_module.CALayer.layer()
            fallback_layer.setFrame_(bounds)
            fallback_layer.setContentsGravity_("resizeAspect" if self.preserve_aspect_ratio else "resize")
            if self.preserve_aspect_ratio:
                try:
                    fallback_layer.setBackgroundColor_(quartz_module.CGColorCreateGenericRGB(0.0, 0.0, 0.0, 1.0))
                except Exception:
                    pass
            host_layer.addSublayer_(fallback_layer)
            self._fallback_blit_layer = fallback_layer
        return self._fallback_blit_layer

    def _set_active_present_path(self, path: str) -> None:
        if path == self._active_present_path:
            return
        self._active_present_path = path
        LOGGER.warning("macOS present path active: %s", path)

    def _vk_create_instance(self):
        vk = self._require_vk()
        app_info = vk.VkApplicationInfo(
            sType=vk.VK_STRUCTURE_TYPE_APPLICATION_INFO,
            pApplicationName="luvatrix",
            applicationVersion=vk.VK_MAKE_VERSION(0, 1, 0),
            pEngineName="luvatrix",
            engineVersion=vk.VK_MAKE_VERSION(0, 1, 0),
            apiVersion=vk.VK_API_VERSION_1_0,
        )
        ext_names = [vk.VK_KHR_SURFACE_EXTENSION_NAME]
        metal_ext = getattr(vk, "VK_EXT_METAL_SURFACE_EXTENSION_NAME", "VK_EXT_metal_surface")
        macos_ext = getattr(vk, "VK_MVK_MACOS_SURFACE_EXTENSION_NAME", "VK_MVK_macos_surface")
        portability_ext = "VK_KHR_portability_enumeration"
        flags = 0
        avail = {decode_vk_string(e.extensionName) for e in vk.vkEnumerateInstanceExtensionProperties(None)}
        if metal_ext in avail:
            ext_names.append(metal_ext)
        if macos_ext in avail:
            ext_names.append(macos_ext)
        if metal_ext not in ext_names and macos_ext not in ext_names:
            raise RuntimeError(
                "No macOS Vulkan surface extension available (expected VK_EXT_metal_surface or VK_MVK_macos_surface)"
            )
        if portability_ext in avail:
            ext_names.append(portability_ext)
            flags |= getattr(vk, "VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR", 0)
        ci = vk.VkInstanceCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
            pApplicationInfo=app_info,
            enabledExtensionCount=len(ext_names),
            ppEnabledExtensionNames=ext_names,
            enabledLayerCount=0,
            ppEnabledLayerNames=[],
            flags=flags,
        )
        return vk.vkCreateInstance(ci, None)

    def _require_vk(self):
        if self._vk is None:
            raise RuntimeError("Vulkan python bindings are not loaded")
        return self._vk

    def _supports_macos_surface_symbols(self) -> bool:
        vk = self._require_vk()
        has_metal = all(
            hasattr(vk, name)
            for name in (
                "VkMetalSurfaceCreateInfoEXT",
                "VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT",
                "vkCreateMetalSurfaceEXT",
            )
        )
        has_macos = all(
            hasattr(vk, name)
            for name in (
                "VkMacOSSurfaceCreateInfoMVK",
                "VK_STRUCTURE_TYPE_MACOS_SURFACE_CREATE_INFO_MVK",
                "vkCreateMacOSSurfaceMVK",
            )
        )
        if has_metal or has_macos:
            return True
        # Accept slim bindings when we can at least access vkGetInstanceProcAddr via loader.
        try:
            lib = self._load_vulkan_loader_lib()
            return hasattr(lib, "vkGetInstanceProcAddr")
        except Exception:  # noqa: BLE001
            return False

    def _create_surface_via_ctypes(self, prefer_metal: bool) -> int:
        if self._window_handle is None:
            raise RuntimeError("window handle missing while creating Vulkan surface")
        vk = self._require_vk()
        try:
            import objc  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("PyObjC `objc` module is required to build a macOS surface") from exc

        lib = self._load_vulkan_loader_lib()
        lib.vkGetInstanceProcAddr.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.vkGetInstanceProcAddr.restype = ctypes.c_void_p
        instance_ptr = self._instance_as_void_p()
        if prefer_metal:
            proc_name = b"vkCreateMetalSurfaceEXT"
            proc_addr = lib.vkGetInstanceProcAddr(instance_ptr, proc_name)
            if not proc_addr:
                raise RuntimeError("vkCreateMetalSurfaceEXT not found in loader")

            class VkMetalSurfaceCreateInfoEXT(ctypes.Structure):
                _fields_ = [
                    ("sType", ctypes.c_int32),
                    ("pNext", ctypes.c_void_p),
                    ("flags", ctypes.c_uint32),
                    ("pLayer", ctypes.c_void_p),
                ]

            fn_type = ctypes.CFUNCTYPE(
                ctypes.c_int32,
                ctypes.c_void_p,
                ctypes.POINTER(VkMetalSurfaceCreateInfoEXT),
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint64),
            )
            fn = fn_type(proc_addr)
            ci = VkMetalSurfaceCreateInfoEXT(
                sType=int(getattr(vk, "VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT", 1000217000)),
                pNext=None,
                flags=0,
                pLayer=ctypes.c_void_p(int(objc.pyobjc_id(self._window_handle.layer))),
            )
            out_surface = ctypes.c_uint64(0)
            result = int(fn(instance_ptr, ctypes.byref(ci), None, ctypes.byref(out_surface)))
            if result != 0:
                raise RuntimeError(f"vkCreateMetalSurfaceEXT returned VkResult={result}")
            return int(out_surface.value)

        proc_name = b"vkCreateMacOSSurfaceMVK"
        proc_addr = lib.vkGetInstanceProcAddr(instance_ptr, proc_name)
        if not proc_addr:
            raise RuntimeError("vkCreateMacOSSurfaceMVK not found in loader")

        class VkMacOSSurfaceCreateInfoMVK(ctypes.Structure):
            _fields_ = [
                ("sType", ctypes.c_int32),
                ("pNext", ctypes.c_void_p),
                ("flags", ctypes.c_uint32),
                ("pView", ctypes.c_void_p),
            ]

        fn_type = ctypes.CFUNCTYPE(
            ctypes.c_int32,
            ctypes.c_void_p,
            ctypes.POINTER(VkMacOSSurfaceCreateInfoMVK),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
        )
        fn = fn_type(proc_addr)
        content_view = self._window_handle.window.contentView()
        ci = VkMacOSSurfaceCreateInfoMVK(
            sType=int(getattr(vk, "VK_STRUCTURE_TYPE_MACOS_SURFACE_CREATE_INFO_MVK", 1000123000)),
            pNext=None,
            flags=0,
            pView=ctypes.c_void_p(int(objc.pyobjc_id(content_view))),
        )
        out_surface = ctypes.c_uint64(0)
        result = int(fn(instance_ptr, ctypes.byref(ci), None, ctypes.byref(out_surface)))
        if result != 0:
            raise RuntimeError(f"vkCreateMacOSSurfaceMVK returned VkResult={result}")
        return int(out_surface.value)

    def _ensure_staging_buffer(self, required_size: int) -> None:
        if self._logical_device is None or self._physical_device is None:
            raise RuntimeError("Vulkan device not initialized for staging buffer")
        if required_size <= 0:
            raise ValueError("required_size must be > 0")
        if self._staging_buffer is not None and self._staging_size >= required_size:
            return
        self._destroy_staging_resources()
        vk = self._require_vk()
        usage_transfer_src = getattr(vk, "VK_BUFFER_USAGE_TRANSFER_SRC_BIT", 0x00000001)
        buffer_ci = vk.VkBufferCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            pNext=None,
            flags=0,
            size=required_size,
            usage=usage_transfer_src,
            sharingMode=getattr(vk, "VK_SHARING_MODE_EXCLUSIVE", 0),
            queueFamilyIndexCount=0,
            pQueueFamilyIndices=None,
        )
        self._staging_buffer = vk.vkCreateBuffer(self._logical_device, buffer_ci, None)
        req = vk.vkGetBufferMemoryRequirements(self._logical_device, self._staging_buffer)
        mem_type = self._find_memory_type(
            type_bits=int(req.memoryTypeBits),
            required_flags=(
                getattr(vk, "VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT", 0x00000002)
                | getattr(vk, "VK_MEMORY_PROPERTY_HOST_COHERENT_BIT", 0x00000004)
            ),
        )
        alloc_info = vk.VkMemoryAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            pNext=None,
            allocationSize=int(req.size),
            memoryTypeIndex=mem_type,
        )
        self._staging_memory = vk.vkAllocateMemory(self._logical_device, alloc_info, None)
        vk.vkBindBufferMemory(self._logical_device, self._staging_buffer, self._staging_memory, 0)
        self._staging_size = required_size

    def _destroy_staging_resources(self) -> None:
        if self._logical_device is None:
            self._staging_buffer = None
            self._staging_memory = None
            self._staging_size = 0
            self._upload_extent = (0, 0)
            return
        vk = self._require_vk()
        if self._staging_buffer is not None:
            vk.vkDestroyBuffer(self._logical_device, self._staging_buffer, None)
            self._staging_buffer = None
        if self._staging_memory is not None:
            vk.vkFreeMemory(self._logical_device, self._staging_memory, None)
            self._staging_memory = None
        self._staging_size = 0
        self._upload_extent = (0, 0)

    def _find_memory_type(self, type_bits: int, required_flags: int) -> int:
        if self._physical_device is None:
            raise RuntimeError("physical device missing while selecting memory type")
        vk = self._require_vk()
        mem_props = vk.vkGetPhysicalDeviceMemoryProperties(self._physical_device)
        count = int(mem_props.memoryTypeCount)
        for i in range(count):
            mem_type = mem_props.memoryTypes[i]
            if (type_bits & (1 << i)) and ((int(mem_type.propertyFlags) & required_flags) == required_flags):
                return i
        raise RuntimeError("no suitable Vulkan memory type found for staging buffer")

    def _coerce_image_index(self, acquire_result: Any) -> int:
        if isinstance(acquire_result, tuple):
            if len(acquire_result) == 0:
                raise RuntimeError("vkAcquireNextImageKHR returned an empty tuple")
            return int(acquire_result[-1])
        return int(acquire_result)
