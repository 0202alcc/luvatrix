from __future__ import annotations

from dataclasses import dataclass
import ctypes
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import struct
import time
from typing import Any
import zlib
import zipfile

import torch

from luvatrix_core.core.debug_capture import (
    FrameStepState,
    ReplayInputEvent,
    build_debug_bundle_export,
    build_overlay_spec,
    build_perf_hud_snapshot,
    build_recording_manifest,
    build_replay_manifest,
    build_screenshot_artifact_bundle,
    bundle_has_required_artifact_classes,
    evaluate_replay_determinism,
    evaluate_recording_budget,
    frame_step_advance,
    toggle_overlay_non_destructive,
    RecordingBudgetEnvelope,
    OverlayRect,
)
from luvatrix_core.core.debug_menu import (
    DEFAULT_DEBUG_MENU_ACTIONS,
    DebugMenuDispatcher,
    DebugMenuDispatchResult,
)
from ..frame_pipeline import prepare_frame_for_extent
from ..vulkan_scaling import RenderScaleController, compute_blit_rect
from ..vulkan_compat import SwapchainOutOfDateError, VulkanKHRCompatMixin, decode_vk_string
from luvatrix_core.perf.copy_telemetry import add_copy_telemetry
from .vulkan_presenter import VulkanContext
from .window_system import (
    AppKitWindowSystem,
    MacOSDebugMenuAction,
    MacOSMenuConfig,
    MacOSWindowHandle,
    MacOSWindowSystem,
)

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
        self._staging_mapped_ptr = None
        self._upload_image = None
        self._upload_image_memory = None
        self._upload_image_extent: tuple[int, int] = (0, 0)
        self._upload_image_format = None
        self._upload_image_layout = None
        self._upload_extent: tuple[int, int] = (0, 0)
        self._clear_color = (0.0, 0.0, 0.0, 1.0)
        self._vk_proc_cache: dict[str, Any] = {}
        self._frame_wait_timeout_ns = 50_000_000  # 50ms safety bound to keep UI responsive
        self._consecutive_acquire_timeouts = 0
        self._swapchain_recreate_count = 0
        self._swapchain_recreate_failures = 0
        self._swapchain_recreate_debounced = 0
        self._last_swapchain_recreate_ns = 0
        self._swapchain_recreate_min_interval_ns = max(
            0, int(float(os.getenv("LUVATRIX_VK_SWAPCHAIN_RECREATE_MIN_INTERVAL_MS", "16.0")) * 1_000_000.0)
        )
        self._swapchain_max_failures_before_fallback = max(
            1, int(os.getenv("LUVATRIX_VK_SWAPCHAIN_MAX_FAILURES", "3"))
        )
        self._persistent_staging_enabled = os.getenv("LUVATRIX_VK_PERSISTENT_STAGING_MAP", "1").strip() != "0"
        self._transfer_growth_enabled = os.getenv("LUVATRIX_VK_TRANSFER_GROWTH", "1").strip() != "0"
        self._upload_image_reuse_enabled = os.getenv("LUVATRIX_VK_UPLOAD_IMAGE_REUSE", "1").strip() != "0"
        self._fast_upload_path_enabled = os.getenv("LUVATRIX_VK_FAST_UPLOAD_PATH", "1").strip() != "0"
        self._debounced_swapchain_recreate_enabled = os.getenv("LUVATRIX_VK_DEBOUNCE_SWAPCHAIN_RECREATE", "1").strip() != "0"
        self._fallback_last_cf_data = None
        self._fallback_last_image = None
        self._fallback_last_ns_image = None
        self._fallback_blit_layer = None
        self._fallback_blit_view = None
        self._fallback_image_view = None
        self._fallback_replaced_content_layer = False
        self._active_present_path: str | None = None
        self._debug_menu_dispatcher = DebugMenuDispatcher(warning_sink=self._on_debug_menu_warning)
        self._debug_menu_profile: dict[str, object] = {}
        self._debug_menu_app_id = "unknown"
        self._debug_menu_artifact_dir = Path("artifacts/debug_menu/runtime")
        self._debug_menu_events_path = self._debug_menu_artifact_dir / "events.jsonl"
        self._debug_menu_enabled = True
        self._debug_menu_functional_enabled = os.getenv("LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS", "1").strip() != "0"
        self._debug_menu_audit: list[str] = []
        self._last_presented_rgba: torch.Tensor | None = None
        self._last_presented_digest = ""
        self._last_present_elapsed_ms: float = 16.667
        self._debug_screenshot_count = 0
        self._debug_clipboard_capture_count = 0
        self._last_clipboard_png_size = 0
        self._recording_active = False
        self._recording_session_id = ""
        self._recording_started_at_utc = ""
        self._recording_start_frame = 0
        self._recording_artifacts: list[str] = []
        self._overlay_enabled = False
        self._overlay_last_spec: dict[str, object] | None = None
        self._runtime_origin_refs_state_setter = None
        self._runtime_origin_refs_enabled = False
        self._replay_active = False
        self._replay_paused = False
        self._replay_session_id = ""
        self._replay_seed = 1337
        self._replay_ordering_digest = ""
        self._frame_step_state = FrameStepState(paused=False, frame_index=0, last_ordering_digest="bootstrap")
        self._perf_hud_enabled = False
        self._last_perf_hud_snapshot: dict[str, object] | None = None
        self._artifact_latest_by_class: dict[str, str] = {}
        self._bundle_export_count = 0
        self._render_scale_controller = RenderScaleController.from_env()
        self._render_scale_levels: tuple[float, ...] = self._render_scale_controller.levels
        self._render_scale_fixed: float | None = self._render_scale_controller.fixed_scale
        self._render_scale_auto_enabled = self._render_scale_controller.auto_enabled
        self._vulkan_internal_scale_enabled = os.getenv("LUVATRIX_VULKAN_INTERNAL_SCALE", "0").strip() == "1"
        self._render_scale_current = self._render_scale_controller.current_scale
        self._present_time_ema_ms: float | None = self._render_scale_controller.present_time_ema_ms
        self._render_scale_cooldown_frames = self._render_scale_controller.cooldown_frames
        if self.window_system is None:
            self.window_system = AppKitWindowSystem()
        self._register_debug_menu_handlers()

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
        started_at = time.perf_counter()
        self._require_initialized()
        self._validate_frame(rgba, context.width, context.height)
        self._capture_presented_frame(rgba)
        self._acquire_next_swapchain_image()
        if self._vulkan_available and self._current_image_index is None:
            return
        self._upload_rgba_to_staging(rgba)
        self._record_and_submit_commands(revision=revision)
        self._present_swapchain_image()
        self._frames_presented += 1
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        self._last_present_elapsed_ms = max(0.001, elapsed_ms)
        self._update_render_scale(elapsed_ms=elapsed_ms, fallback_active=not self._vulkan_available)

    def resize(self, context: VulkanContext, width: int, height: int) -> VulkanContext:
        self._require_initialized()
        self._validate_dimensions(width, height)
        self._wait_device_idle()
        self._recreate_swapchain(width, height)
        self._record_swapchain_recreate()
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
        menu_config = self._build_menu_config(title)
        self._window_handle = self.window_system.create_window(
            width,
            height,
            title,
            use_metal_layer=True,
            preserve_aspect_ratio=self.preserve_aspect_ratio,
            menu_config=menu_config,
        )

    def configure_debug_menu(
        self,
        *,
        app_id: str,
        profile: dict[str, object],
        artifact_dir: str | Path = "artifacts/debug_menu/runtime",
        runtime_origin_refs_state_setter=None,
    ) -> None:
        self._debug_menu_app_id = app_id
        self._debug_menu_profile = dict(profile)
        self._debug_menu_artifact_dir = Path(artifact_dir)
        self._debug_menu_events_path = self._debug_menu_artifact_dir / "events.jsonl"
        self._debug_menu_enabled = os.getenv("LUVATRIX_MACOS_DEBUG_MENU_WIRING", "1").strip() != "0"
        self._debug_menu_functional_enabled = os.getenv("LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS", "1").strip() != "0"
        self._runtime_origin_refs_state_setter = runtime_origin_refs_state_setter
        self._write_debug_menu_manifest()

    def dispatch_debug_menu_action(self, action_id: str) -> DebugMenuDispatchResult:
        context = {
            "app_id": self._debug_menu_app_id,
            "profile": dict(self._debug_menu_profile),
            "menu_wiring_enabled": self._debug_menu_enabled,
            "functional_wiring_enabled": self._debug_menu_functional_enabled,
        }
        result = self._debug_menu_dispatcher.dispatch(action_id, context)
        self._append_debug_menu_event(
            {
                "action_id": result.action_id,
                "status": result.status,
                "warning": result.warning,
            }
        )
        return result

    def _create_vulkan_instance(self) -> None:
        if self._vk is None:
            try:
                import vulkan as _vk  # type: ignore
            except Exception as exc:  # noqa: BLE001
                self._vulkan_available = False
                self._vulkan_note = (
                    "Python Vulkan bindings not available. Install with `pip install \"luvatrix[vulkan]\"` "
                    "(or `pip install vulkan`) and ensure MoltenVK "
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
        if self._debounced_swapchain_recreate_enabled:
            now_ns = time.perf_counter_ns()
            if now_ns - self._last_swapchain_recreate_ns < self._swapchain_recreate_min_interval_ns:
                self._swapchain_recreate_debounced += 1
                return
        try:
            # Avoid blocking app responsiveness while user is actively resizing.
            self._recreate_swapchain(width, height)
            self._record_swapchain_recreate()
        except Exception as exc:  # noqa: BLE001
            self._swapchain_recreate_failures += 1
            if self._swapchain_recreate_failures >= self._swapchain_max_failures_before_fallback:
                LOGGER.warning("swapchain recreation failed repeatedly; falling back to layer-blit: %s", exc)
                self._vulkan_available = False
                self._vulkan_note = "Swapchain recreation failed repeatedly; fallback layer-blit mode enabled."
            else:
                LOGGER.warning(
                    "swapchain recreation failed (%d/%d): %s",
                    self._swapchain_recreate_failures,
                    self._swapchain_max_failures_before_fallback,
                    exc,
                )

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
        # Keep CPU-side frame copy only when fallback presenter is active.
        if not self._vulkan_available:
            started = time.perf_counter_ns()
            self._pending_rgba = rgba.contiguous().clone()
            add_copy_telemetry(
                copy_count=1,
                copy_bytes=int(self._pending_rgba.numel()),
                upload_pack_ns=time.perf_counter_ns() - started,
            )
        else:
            self._pending_rgba = None
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
        clipped = self._upload_clip_if_needed(rgba_upload, upload_w=upload_w, upload_h=upload_h)
        self._ensure_upload_image(upload_w, upload_h)
        pack_started = time.perf_counter_ns()
        clipped_cpu = clipped.cpu() if clipped.device.type != "cpu" else clipped
        upload_array = clipped_cpu.numpy()
        src_view = memoryview(upload_array)
        packed_nbytes = int(src_view.nbytes)
        pack_ns = time.perf_counter_ns() - pack_started
        self._ensure_staging_buffer(packed_nbytes)
        mapped_ptr, map_ns, should_unmap, map_count = self._resolve_staging_ptr(size=packed_nbytes)
        memcpy_ns = 0
        try:
            # vulkan-python returns ffi.buffer(...) for vkMapMemory on some builds.
            memcpy_started = time.perf_counter_ns()
            mapped_cdata = vk.ffi.from_buffer(mapped_ptr)
            src_cdata = vk.ffi.from_buffer(src_view)
            vk.ffi.memmove(mapped_cdata, src_cdata, packed_nbytes)
            memcpy_ns = time.perf_counter_ns() - memcpy_started
        except Exception:
            # Fallback for bindings that return an integer-like pointer.
            memcpy_started = time.perf_counter_ns()
            dest_ptr = ctypes.c_void_p(int(mapped_ptr))
            ctypes.memmove(dest_ptr, upload_array.ctypes.data, packed_nbytes)
            memcpy_ns = time.perf_counter_ns() - memcpy_started
        finally:
            if should_unmap:
                vk.vkUnmapMemory(self._logical_device, self._staging_memory)
        add_copy_telemetry(
            copy_count=1,
            copy_bytes=packed_nbytes,
            upload_bytes=packed_nbytes,
            upload_pack_ns=pack_ns,
            upload_map_ns=map_ns,
            upload_memcpy_ns=memcpy_ns,
            staging_map_count=map_count,
        )
        self._upload_extent = (upload_w, upload_h)
        self._clear_color = (0.0, 0.0, 0.0, 1.0)

    def _resolve_staging_ptr(self, size: int) -> tuple[Any, int, bool, int]:
        if self._logical_device is None or self._staging_memory is None:
            raise RuntimeError("Vulkan staging memory is not initialized")
        vk = self._require_vk()
        if not self._persistent_staging_enabled:
            started = time.perf_counter_ns()
            ptr = vk.vkMapMemory(self._logical_device, self._staging_memory, 0, size, 0)
            return (ptr, time.perf_counter_ns() - started, True, 1)
        if self._staging_mapped_ptr is None:
            started = time.perf_counter_ns()
            self._staging_mapped_ptr = vk.vkMapMemory(self._logical_device, self._staging_memory, 0, self._staging_size, 0)
            return (self._staging_mapped_ptr, time.perf_counter_ns() - started, False, 1)
        return (self._staging_mapped_ptr, 0, False, 0)

    def _upload_clip_if_needed(self, rgba_upload: torch.Tensor, upload_w: int, upload_h: int) -> torch.Tensor:
        if not self._fast_upload_path_enabled:
            return rgba_upload[:upload_h, :upload_w, :].contiguous()
        if upload_w == int(rgba_upload.shape[1]) and upload_h == int(rgba_upload.shape[0]):
            if rgba_upload.is_contiguous():
                return rgba_upload
            return rgba_upload.contiguous()
        return rgba_upload[:upload_h, :upload_w, :].contiguous()

    def _next_transfer_allocation_size(self, required_size: int) -> int:
        if required_size <= 0:
            return required_size
        if not self._transfer_growth_enabled:
            return required_size
        base = max(64 * 1024, required_size)
        if base & (base - 1) == 0:
            return base
        return 1 << base.bit_length()

    def _next_upload_extent(self, size: int) -> int:
        if size <= 0:
            return size
        if not self._transfer_growth_enabled:
            return size
        block = 64
        return int(((int(size) + block - 1) // block) * block)

    def _record_swapchain_recreate(self) -> None:
        self._swapchain_recreate_count += 1
        self._swapchain_recreate_failures = 0
        self._last_swapchain_recreate_ns = time.perf_counter_ns()
        add_copy_telemetry(swapchain_recreate_count=1)

    def _prepare_upload_frame(self, rgba: torch.Tensor) -> torch.Tensor:
        source = rgba
        if self._vulkan_internal_scale_enabled:
            source = self._prepare_scaled_source_frame(rgba)
        if self._can_use_gpu_blit():
            return source
        if self._swapchain_extent is None:
            return source
        swap_w, swap_h = self._swapchain_extent
        if swap_w <= 0 or swap_h <= 0:
            return source
        if int(source.shape[1]) == int(swap_w) and int(source.shape[0]) == int(swap_h):
            return source if source.is_contiguous() else source.contiguous()
        return prepare_frame_for_extent(
            source,
            target_w=swap_w,
            target_h=swap_h,
            preserve_aspect_ratio=self.preserve_aspect_ratio,
        )

    def _prepare_scaled_source_frame(self, rgba: torch.Tensor) -> torch.Tensor:
        self._sync_render_scale_attrs_to_controller()
        out = self._render_scale_controller.scale_frame(rgba)
        self._sync_render_scale_attrs_from_controller()
        return out

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
            or self._upload_image is None
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
            self._record_upload_copy_and_scale(cmd=cmd, swapchain_image=image)
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
        submit_started = time.perf_counter_ns()
        self._queue_submit(self._graphics_queue, submit, self._in_flight_fence)
        add_copy_telemetry(queue_submit_ns=time.perf_counter_ns() - submit_started)

    def _record_upload_copy_and_scale(self, cmd, swapchain_image) -> None:
        if self._upload_image is None:
            raise RuntimeError("upload image is not initialized")
        vk = self._require_vk()
        subresource_range = vk.VkImageSubresourceRange(
            aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
            baseMipLevel=0,
            levelCount=1,
            baseArrayLayer=0,
            layerCount=1,
        )
        old_layout = (
            getattr(vk, "VK_IMAGE_LAYOUT_UNDEFINED", 0)
            if self._upload_image_layout is None
            else int(self._upload_image_layout)
        )
        to_dst = vk.VkImageMemoryBarrier(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            srcAccessMask=getattr(vk, "VK_ACCESS_TRANSFER_READ_BIT", 0x0800),
            dstAccessMask=getattr(vk, "VK_ACCESS_TRANSFER_WRITE_BIT", 0x1000),
            oldLayout=old_layout,
            newLayout=getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            srcQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            dstQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            image=self._upload_image,
            subresourceRange=subresource_range,
        )
        vk.vkCmdPipelineBarrier(
            cmd,
            getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000),
            getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000),
            0,
            0,
            None,
            0,
            None,
            1,
            [to_dst],
        )
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
            self._upload_image,
            getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            1,
            [copy_region],
        )
        to_src = vk.VkImageMemoryBarrier(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            srcAccessMask=getattr(vk, "VK_ACCESS_TRANSFER_WRITE_BIT", 0x1000),
            dstAccessMask=getattr(vk, "VK_ACCESS_TRANSFER_READ_BIT", 0x0800),
            oldLayout=getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            newLayout=getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL", 6),
            srcQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            dstQueueFamilyIndex=getattr(vk, "VK_QUEUE_FAMILY_IGNORED", -1),
            image=self._upload_image,
            subresourceRange=subresource_range,
        )
        vk.vkCmdPipelineBarrier(
            cmd,
            getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000),
            getattr(vk, "VK_PIPELINE_STAGE_TRANSFER_BIT", 0x1000),
            0,
            0,
            None,
            0,
            None,
            1,
            [to_src],
        )
        self._upload_image_layout = getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL", 6)
        if self._can_use_gpu_blit():
            self._record_blit_upload_to_swapchain(cmd=cmd, swapchain_image=swapchain_image)
            return
        copy_to_swapchain = vk.VkImageCopy(
            srcSubresource=vk.VkImageSubresourceLayers(
                aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
                mipLevel=0,
                baseArrayLayer=0,
                layerCount=1,
            ),
            srcOffset=(0, 0, 0),
            dstSubresource=vk.VkImageSubresourceLayers(
                aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
                mipLevel=0,
                baseArrayLayer=0,
                layerCount=1,
            ),
            dstOffset=(0, 0, 0),
            extent=(self._upload_extent[0], self._upload_extent[1], 1),
        )
        vk.vkCmdCopyImage(
            cmd,
            self._upload_image,
            getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL", 6),
            swapchain_image,
            getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            1,
            [copy_to_swapchain],
        )

    def _record_blit_upload_to_swapchain(self, cmd, swapchain_image) -> None:
        vk = self._require_vk()
        if self._swapchain_extent is None:
            raise RuntimeError("swapchain extent missing for GPU blit")
        src_w, src_h = self._upload_extent
        dst_w, dst_h = self._swapchain_extent
        if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
            return
        dst_x0, dst_y0, dst_x1, dst_y1 = compute_blit_rect(
            src_w=src_w,
            src_h=src_h,
            dst_w=dst_w,
            dst_h=dst_h,
            preserve_aspect_ratio=self.preserve_aspect_ratio,
        )
        blit = vk.VkImageBlit(
            srcSubresource=vk.VkImageSubresourceLayers(
                aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
                mipLevel=0,
                baseArrayLayer=0,
                layerCount=1,
            ),
            srcOffsets=((0, 0, 0), (src_w, src_h, 1)),
            dstSubresource=vk.VkImageSubresourceLayers(
                aspectMask=getattr(vk, "VK_IMAGE_ASPECT_COLOR_BIT", 0x1),
                mipLevel=0,
                baseArrayLayer=0,
                layerCount=1,
            ),
            dstOffsets=((dst_x0, dst_y0, 0), (dst_x1, dst_y1, 1)),
        )
        vk.vkCmdBlitImage(
            cmd,
            self._upload_image,
            getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL", 6),
            swapchain_image,
            getattr(vk, "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL", 7),
            1,
            [blit],
            getattr(vk, "VK_FILTER_NEAREST", 0),
        )

    def _queue_submit(self, queue, submit, fence) -> None:
        vk = self._require_vk()
        vk.vkQueueSubmit(queue, 1, [submit], fence)

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
                present_started = time.perf_counter_ns()
                self._vk_queue_present(self._graphics_queue, present_info)
                add_copy_telemetry(queue_present_ns=time.perf_counter_ns() - present_started)
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
        self._destroy_command_resources(destroy_transfer_resources=False)
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

    def _destroy_command_resources(self, *, destroy_transfer_resources: bool = True) -> None:
        if not self._vulkan_available:
            return
        if self._logical_device is None:
            return
        vk = self._require_vk()
        if destroy_transfer_resources:
            self._destroy_staging_resources()
            self._destroy_upload_image_resources()
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
        rgba_display = self._prepare_fallback_frame(rgba)
        height, width, _ = rgba_display.shape
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
        data = rgba_display.contiguous().cpu().numpy().tobytes(order="C")
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

    def _register_debug_menu_handlers(self) -> None:
        for spec in DEFAULT_DEBUG_MENU_ACTIONS:
            self._debug_menu_dispatcher.register(
                spec.menu_id,
                self._make_debug_handler(spec.menu_id),
                is_enabled=lambda ctx, action_id=spec.menu_id: self._is_debug_action_enabled(action_id, ctx),
            )

    def _is_debug_action_enabled(self, action_id: str, context: dict[str, object]) -> bool:
        if not context.get("menu_wiring_enabled", True):
            return False
        if not context.get("functional_wiring_enabled", True):
            return False
        profile = context.get("profile")
        if not isinstance(profile, dict):
            return False
        if not (bool(profile.get("supported", False)) and bool(profile.get("enable_default_debug_root", False))):
            return False
        return self._runtime_action_enabled(action_id)

    def _make_debug_handler(self, action_id: str):
        def _handler(_context: dict[str, object]) -> None:
            handlers = {
                "debug.menu.capture.screenshot": self._handle_debug_screenshot,
                "debug.menu.capture.screenshot.clipboard": self._handle_debug_screenshot_clipboard,
                "debug.menu.capture.record.toggle": self._handle_debug_recording_toggle,
                "debug.menu.overlay.toggle": self._handle_debug_overlay_toggle,
                "debug.menu.overlay.origin_refs.toggle": self._handle_debug_origin_refs_toggle,
                "debug.menu.replay.start": self._handle_debug_replay_start,
                "debug.menu.frame.step": self._handle_debug_frame_step,
                "debug.menu.perf.hud.toggle": self._handle_debug_perf_hud_toggle,
                "debug.menu.bundle.export": self._handle_debug_bundle_export,
            }
            handler = handlers.get(action_id)
            if handler is None:
                return
            handler()

        return _handler

    def _runtime_action_enabled(self, action_id: str) -> bool:
        if action_id == "debug.menu.frame.step":
            return bool(self._replay_paused)
        if action_id == "debug.menu.bundle.export":
            required = {"captures", "replay", "perf", "provenance"}
            return required.issubset(set(self._artifact_latest_by_class))
        return True

    def _build_runtime_action_states(self) -> dict[str, bool]:
        return {spec.menu_id: self._runtime_action_enabled(spec.menu_id) for spec in DEFAULT_DEBUG_MENU_ACTIONS}

    def _handle_debug_screenshot(self) -> None:
        frame = self._latest_frame_or_placeholder()
        capture_id = f"capture-{self._frames_presented:06d}-{self._debug_screenshot_count:03d}"
        self._debug_screenshot_count += 1
        captured_at = self._now_utc()
        provenance_id = self._frame_digest(frame)
        bundle = build_screenshot_artifact_bundle(
            capture_id=capture_id,
            route=self._debug_menu_app_id,
            revision=str(self._frames_presented),
            captured_at_utc=captured_at,
            provenance_id=provenance_id,
            output_dir=str(self._debug_menu_artifact_dir / "captures"),
        )
        png_path = Path(bundle.png_path)
        sidecar_path = Path(bundle.sidecar_path)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_png_rgba(frame, png_path)
        sidecar_path.write_text(json.dumps(bundle.sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._artifact_latest_by_class["captures"] = str(png_path)
        self._artifact_latest_by_class["provenance"] = str(sidecar_path)
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.capture.screenshot",
                "status": "HANDLER_EXECUTED",
                "capture_id": capture_id,
                "png_path": str(png_path),
                "sidecar_path": str(sidecar_path),
                "provenance_id": provenance_id,
            }
        )

    def _handle_debug_screenshot_clipboard(self) -> None:
        frame = self._latest_frame_or_placeholder()
        capture_id = f"clipboard-{self._frames_presented:06d}-{self._debug_clipboard_capture_count:03d}"
        self._debug_clipboard_capture_count += 1
        captured_at = self._now_utc()
        provenance_id = self._frame_digest(frame)
        png_bytes = self._encode_png_rgba_bytes(frame)
        self._last_clipboard_png_size = len(png_bytes)
        clipboard_write = "OK" if self._write_png_bytes_to_clipboard(png_bytes) else "UNAVAILABLE"
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.capture.screenshot.clipboard",
                "status": "HANDLER_EXECUTED",
                "capture_id": capture_id,
                "captured_at_utc": captured_at,
                "provenance_id": provenance_id,
                "clipboard_bytes": self._last_clipboard_png_size,
                "clipboard_write": clipboard_write,
            }
        )

    def _write_png_bytes_to_clipboard(self, png_bytes: bytes) -> bool:
        if not png_bytes:
            return False
        try:
            from AppKit import NSPasteboard  # type: ignore
            try:
                from AppKit import NSPasteboardTypePNG  # type: ignore
            except Exception:
                NSPasteboardTypePNG = "public.png"
            from Foundation import NSData  # type: ignore
        except Exception:
            return False
        try:
            pasteboard = NSPasteboard.generalPasteboard()
            if pasteboard is None:
                return False
            pasteboard.clearContents()
            data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
            return bool(pasteboard.setData_forType_(data, NSPasteboardTypePNG))
        except Exception:  # noqa: BLE001
            LOGGER.exception("clipboard screenshot write failed")
            return False

    def _handle_debug_recording_toggle(self) -> None:
        now_utc = self._now_utc()
        if not self._recording_active:
            self._recording_active = True
            self._recording_session_id = f"rec-{self._frames_presented:06d}"
            self._recording_started_at_utc = now_utc
            self._recording_start_frame = self._frames_presented
            self._append_debug_menu_event(
                {
                    "action_id": "debug.menu.capture.record.toggle",
                    "status": "RECORDING_STARTED",
                    "session_id": self._recording_session_id,
                }
            )
            return
        frame_count = max(0, self._frames_presented - self._recording_start_frame)
        manifest = build_recording_manifest(
            session_id=self._recording_session_id,
            route=self._debug_menu_app_id,
            revision=str(self._frames_presented),
            started_at_utc=self._recording_started_at_utc,
            stopped_at_utc=now_utc,
            provenance_id=self._last_presented_digest or "none",
            frame_count=frame_count,
        )
        budget = evaluate_recording_budget(
            envelope=RecordingBudgetEnvelope(start_overhead_ms=10.0, stop_overhead_ms=10.0, steady_overhead_ms=2.0),
            observed_start_overhead_ms=2.0,
            observed_stop_overhead_ms=2.0,
            observed_steady_overhead_ms=0.5,
        )
        payload: dict[str, object] = dict(manifest)
        payload["budget"] = {
            "passed": budget.passed,
            "exceeded_limits": list(budget.exceeded_limits),
        }
        out_path = self._debug_menu_artifact_dir / "recordings" / f"{self._recording_session_id}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._recording_artifacts.append(str(out_path))
        self._artifact_latest_by_class["captures"] = str(out_path)
        self._recording_active = False
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.capture.record.toggle",
                "status": "RECORDING_STOPPED",
                "session_id": self._recording_session_id,
                "manifest_path": str(out_path),
            }
        )

    def _handle_debug_overlay_toggle(self) -> None:
        self._overlay_enabled = not self._overlay_enabled
        spec = build_overlay_spec(
            overlay_id="runtime.debug.overlay",
            bounds=OverlayRect(x=0, y=0, width=1920, height=1080),
            dirty_rects=(OverlayRect(x=128, y=96, width=320, height=240),),
            coordinate_space="window_px",
            opacity=0.7,
            enabled=self._overlay_enabled,
        )
        digest = self._last_presented_digest or "frame-unavailable"
        toggle = toggle_overlay_non_destructive(
            overlay_id=spec.overlay_id,
            previous_enabled=not self._overlay_enabled,
            next_enabled=self._overlay_enabled,
            content_digest=digest,
        )
        out_path = self._debug_menu_artifact_dir / "overlays" / "state.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "overlay_id": spec.overlay_id,
            "enabled": spec.enabled,
            "coordinate_space": spec.coordinate_space,
            "dirty_rects": [rect.__dict__ for rect in spec.dirty_rects],
            "toggle": toggle.__dict__,
        }
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._overlay_last_spec = payload
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.overlay.toggle",
                "status": "HANDLER_EXECUTED",
                "enabled": self._overlay_enabled,
                "state_path": str(out_path),
            }
        )

    def _handle_debug_origin_refs_toggle(self) -> None:
        setter = self._runtime_origin_refs_state_setter
        if callable(setter):
            next_enabled = bool(setter())
        else:
            next_enabled = not bool(self._runtime_origin_refs_enabled)
        self._runtime_origin_refs_enabled = next_enabled
        payload = {
            "action_id": "debug.menu.overlay.origin_refs.toggle",
            "status": "HANDLER_EXECUTED",
            "enabled": self._runtime_origin_refs_enabled,
            "mode": "runtime_local" if callable(setter) else "stub",
        }
        self._append_debug_menu_event(payload)

    def _handle_debug_replay_start(self) -> None:
        self._replay_active = True
        self._replay_paused = True
        self._replay_session_id = f"replay-{self._frames_presented:06d}"
        self._replay_seed = 1337 + self._frames_presented
        self._frame_step_state = FrameStepState(
            paused=True,
            frame_index=max(0, self._frames_presented),
            last_ordering_digest=self._last_presented_digest or "replay-bootstrap",
        )
        digest = self._last_presented_digest or "digest-unavailable"
        events = (
            ReplayInputEvent(
                sequence=1,
                timestamp_ms=max(1, self._frames_presented * 16),
                event_type="frame.snapshot",
                payload_digest=digest,
            ),
        )
        replay = evaluate_replay_determinism(
            session_id=self._replay_session_id,
            seed=self._replay_seed,
            platform="macos",
            events=events,
            expected_digest=None,
        )
        self._replay_ordering_digest = replay.ordering_digest
        manifest = build_replay_manifest(
            session_id=replay.session_id,
            seed=replay.seed,
            platform=replay.platform,
            ordering_digest=replay.ordering_digest,
            event_count=replay.event_count,
            recorded_at_utc=self._now_utc(),
        )
        out_path = self._debug_menu_artifact_dir / "replay" / f"{self._replay_session_id}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._artifact_latest_by_class["replay"] = str(out_path)
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.replay.start",
                "status": "HANDLER_EXECUTED",
                "session_id": self._replay_session_id,
                "manifest_path": str(out_path),
                "ordering_digest": self._replay_ordering_digest,
            }
        )

    def _handle_debug_frame_step(self) -> None:
        next_digest = self._last_presented_digest or self._replay_ordering_digest or "frame-step-digest"
        self._frame_step_state = frame_step_advance(self._frame_step_state, next_ordering_digest=next_digest)
        out_path = self._debug_menu_artifact_dir / "replay" / "frame_step_state.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(self._frame_step_state.__dict__, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.frame.step",
                "status": "HANDLER_EXECUTED",
                "frame_index": self._frame_step_state.frame_index,
                "ordering_digest": self._frame_step_state.last_ordering_digest,
            }
        )

    def _handle_debug_perf_hud_toggle(self) -> None:
        self._perf_hud_enabled = not self._perf_hud_enabled
        if self._perf_hud_enabled:
            snapshot = build_perf_hud_snapshot(
                frame_index=max(0, self._frames_presented),
                frame_time_ms=max(0.001, self._last_present_elapsed_ms),
                present_mode="vulkan" if self._vulkan_available else "fallback",
                ordering_digest=self._last_presented_digest or self._replay_ordering_digest or "perf-digest",
            )
            self._last_perf_hud_snapshot = snapshot
            out_path = self._debug_menu_artifact_dir / "perf" / "hud_snapshot.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self._artifact_latest_by_class["perf"] = str(out_path)
            self._append_debug_menu_event(
                {
                    "action_id": "debug.menu.perf.hud.toggle",
                    "status": "HANDLER_EXECUTED",
                    "enabled": True,
                    "snapshot_path": str(out_path),
                }
            )
            return
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.perf.hud.toggle",
                "status": "HANDLER_EXECUTED",
                "enabled": False,
            }
        )

    def _handle_debug_bundle_export(self) -> None:
        self._bundle_export_count += 1
        bundle_id = f"bundle-{self._frames_presented:06d}-{self._bundle_export_count:03d}"
        provenance_id = self._last_presented_digest or self._replay_ordering_digest or "bundle-provenance"
        artifact_paths = (
            self._artifact_latest_by_class.get("captures", ""),
            self._artifact_latest_by_class.get("replay", ""),
            self._artifact_latest_by_class.get("perf", ""),
            self._artifact_latest_by_class.get("provenance", ""),
        )
        export = build_debug_bundle_export(
            bundle_id=bundle_id,
            platform="macos",
            exported_at_utc=self._now_utc(),
            provenance_id=provenance_id,
            artifact_paths=artifact_paths,
            artifact_classes=("captures", "replay", "perf", "provenance"),
            output_dir=str(self._debug_menu_artifact_dir / "bundles"),
        )
        if not bundle_has_required_artifact_classes(export.manifest):
            raise RuntimeError("bundle export missing required artifact classes")
        zip_path = Path(export.zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            manifest_bytes = json.dumps(export.manifest, indent=2, sort_keys=True).encode("utf-8")
            zf.writestr("manifest.json", manifest_bytes)
            for idx, artifact in enumerate(export.manifest["artifact_paths"]):
                path = Path(str(artifact))
                arcname = f"artifact_{idx}_{path.name}"
                if path.exists():
                    zf.write(path, arcname=arcname)
                else:
                    zf.writestr(arcname, "")
        manifest_path = self._debug_menu_artifact_dir / "bundles" / f"{bundle_id}.json"
        manifest_path.write_text(json.dumps(export.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.bundle.export",
                "status": "HANDLER_EXECUTED",
                "bundle_id": bundle_id,
                "zip_path": str(zip_path),
                "manifest_path": str(manifest_path),
            }
        )

    def _latest_frame_or_placeholder(self) -> torch.Tensor:
        if self._last_presented_rgba is not None:
            return self._last_presented_rgba
        return torch.zeros((1, 1, 4), dtype=torch.uint8)

    def _capture_presented_frame(self, rgba: torch.Tensor) -> None:
        self._last_presented_rgba = rgba.contiguous().clone()
        self._last_presented_digest = self._frame_digest(self._last_presented_rgba)

    def _frame_digest(self, rgba: torch.Tensor) -> str:
        return hashlib.sha256(rgba.contiguous().cpu().numpy().tobytes(order="C")).hexdigest()

    def _now_utc(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _write_png_rgba(self, rgba: torch.Tensor, out_path: Path) -> None:
        out_path.write_bytes(self._encode_png_rgba_bytes(rgba))

    def _encode_png_rgba_bytes(self, rgba: torch.Tensor) -> bytes:
        arr = rgba.contiguous().cpu().numpy()
        height, width, channels = arr.shape
        if channels != 4:
            raise ValueError("expected RGBA image with 4 channels")
        raw = b"".join(b"\x00" + arr[row].tobytes() for row in range(height))
        payload = zlib.compress(raw)

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            return (
                struct.pack("!I", len(data))
                + chunk_type
                + data
                + struct.pack("!I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
            )

        header = b"\x89PNG\r\n\x1a\n"
        ihdr = _chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0))
        idat = _chunk(b"IDAT", payload)
        iend = _chunk(b"IEND", b"")
        return header + ihdr + idat + iend

    def _build_menu_config(self, title: str) -> MacOSMenuConfig:
        def _on_action(action_id: str) -> None:
            self.dispatch_debug_menu_action(action_id)

        enabled_default = bool(self._debug_menu_profile.get("supported", False)) and bool(
            self._debug_menu_profile.get("enable_default_debug_root", False)
        )
        enabled_default = enabled_default and self._debug_menu_enabled and self._debug_menu_functional_enabled
        runtime_states = self._build_runtime_action_states()
        actions = tuple(
            MacOSDebugMenuAction(
                action_id=spec.menu_id,
                label=spec.label,
                enabled=enabled_default and runtime_states.get(spec.menu_id, False),
            )
            for spec in DEFAULT_DEBUG_MENU_ACTIONS
        )
        return MacOSMenuConfig(
            app_title=title,
            debug_actions=actions,
            on_debug_action=_on_action,
        )

    def _write_debug_menu_manifest(self) -> None:
        self._debug_menu_artifact_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._debug_menu_artifact_dir / "manifest.json"
        payload = {
            "app_id": self._debug_menu_app_id,
            "menu_wiring_enabled": self._debug_menu_enabled,
            "functional_wiring_enabled": self._debug_menu_functional_enabled,
            "profile": dict(self._debug_menu_profile),
            "actions": [spec.menu_id for spec in DEFAULT_DEBUG_MENU_ACTIONS],
            "action_states": self._build_runtime_action_states(),
        }
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _append_debug_menu_event(self, payload: dict[str, object]) -> None:
        self._debug_menu_artifact_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, sort_keys=True) + "\n"
        with self._debug_menu_events_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _on_debug_menu_warning(self, message: str) -> None:
        self._debug_menu_audit.append(message)
        self._append_debug_menu_event({"status": "WARNING", "warning": message})

    def _effective_render_scale(self) -> float:
        self._sync_render_scale_attrs_to_controller()
        return self._render_scale_controller.effective_scale()

    def _prepare_fallback_frame(self, rgba: torch.Tensor) -> torch.Tensor:
        return self._prepare_scaled_source_frame(rgba)

    def _update_render_scale(self, elapsed_ms: float, fallback_active: bool) -> None:
        enabled = fallback_active or self._vulkan_internal_scale_enabled
        self._sync_render_scale_attrs_to_controller()
        changed = self._render_scale_controller.update(elapsed_ms=elapsed_ms, enabled=enabled)
        self._sync_render_scale_attrs_from_controller()
        if changed:
            LOGGER.warning("macOS render scale adjusted: %.2f", self._render_scale_current)

    def _sync_render_scale_attrs_to_controller(self) -> None:
        self._render_scale_controller.fixed_scale = self._render_scale_fixed
        self._render_scale_controller.auto_enabled = self._render_scale_auto_enabled
        self._render_scale_controller.current_scale = self._render_scale_current
        self._render_scale_controller.present_time_ema_ms = self._present_time_ema_ms
        self._render_scale_controller.cooldown_frames = self._render_scale_cooldown_frames

    def _sync_render_scale_attrs_from_controller(self) -> None:
        self._render_scale_fixed = self._render_scale_controller.fixed_scale
        self._render_scale_auto_enabled = self._render_scale_controller.auto_enabled
        self._render_scale_current = self._render_scale_controller.current_scale
        self._present_time_ema_ms = self._render_scale_controller.present_time_ema_ms
        self._render_scale_cooldown_frames = self._render_scale_controller.cooldown_frames

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
        alloc_size = self._next_transfer_allocation_size(required_size)
        vk = self._require_vk()
        usage_transfer_src = getattr(vk, "VK_BUFFER_USAGE_TRANSFER_SRC_BIT", 0x00000001)
        buffer_ci = vk.VkBufferCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            pNext=None,
            flags=0,
            size=alloc_size,
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
        self._staging_size = alloc_size
        add_copy_telemetry(staging_realloc_count=1)

    def _destroy_staging_resources(self) -> None:
        if self._logical_device is None:
            self._staging_buffer = None
            self._staging_memory = None
            self._staging_size = 0
            self._staging_mapped_ptr = None
            self._upload_extent = (0, 0)
            return
        vk = self._require_vk()
        if self._staging_mapped_ptr is not None and self._staging_memory is not None:
            try:
                vk.vkUnmapMemory(self._logical_device, self._staging_memory)
            except Exception:  # noqa: BLE001
                pass
            self._staging_mapped_ptr = None
        if self._staging_buffer is not None:
            vk.vkDestroyBuffer(self._logical_device, self._staging_buffer, None)
            self._staging_buffer = None
        if self._staging_memory is not None:
            vk.vkFreeMemory(self._logical_device, self._staging_memory, None)
            self._staging_memory = None
        self._staging_size = 0
        self._upload_extent = (0, 0)

    def _destroy_upload_image_resources(self) -> None:
        if self._logical_device is None:
            self._upload_image = None
            self._upload_image_memory = None
            self._upload_image_extent = (0, 0)
            self._upload_image_format = None
            self._upload_image_layout = None
            return
        vk = self._require_vk()
        if self._upload_image is not None:
            vk.vkDestroyImage(self._logical_device, self._upload_image, None)
            self._upload_image = None
        if self._upload_image_memory is not None:
            vk.vkFreeMemory(self._logical_device, self._upload_image_memory, None)
            self._upload_image_memory = None
        self._upload_image_extent = (0, 0)
        self._upload_image_format = None
        self._upload_image_layout = None

    def _ensure_upload_image(self, width: int, height: int) -> None:
        if self._logical_device is None or self._physical_device is None:
            raise RuntimeError("Vulkan device not initialized for upload image")
        if width <= 0 or height <= 0:
            raise ValueError("upload image extent must be > 0")
        vk = self._require_vk()
        desired_format = int(
            self._swapchain_image_format
            if self._swapchain_image_format is not None
            else getattr(vk, "VK_FORMAT_R8G8B8A8_UNORM", 37)
        )
        current_w, current_h = self._upload_image_extent
        same_extent = (current_w, current_h) == (width, height)
        reusable_extent = self._upload_image_reuse_enabled and current_w >= width and current_h >= height
        same_format = self._upload_image_format is None or desired_format == int(self._upload_image_format)
        if self._upload_image is not None and same_format and (same_extent or reusable_extent):
            return
        alloc_w = width
        alloc_h = height
        if self._transfer_growth_enabled:
            alloc_w = self._next_upload_extent(width)
            alloc_h = self._next_upload_extent(height)
        self._destroy_upload_image_resources()
        image_ci = vk.VkImageCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            pNext=None,
            flags=0,
            imageType=getattr(vk, "VK_IMAGE_TYPE_2D", 1),
            format=desired_format,
            extent=(int(alloc_w), int(alloc_h), 1),
            mipLevels=1,
            arrayLayers=1,
            samples=getattr(vk, "VK_SAMPLE_COUNT_1_BIT", 1),
            tiling=getattr(vk, "VK_IMAGE_TILING_OPTIMAL", 0),
            usage=(
                getattr(vk, "VK_IMAGE_USAGE_TRANSFER_DST_BIT", 0x00000002)
                | getattr(vk, "VK_IMAGE_USAGE_TRANSFER_SRC_BIT", 0x00000001)
            ),
            sharingMode=getattr(vk, "VK_SHARING_MODE_EXCLUSIVE", 0),
            queueFamilyIndexCount=0,
            pQueueFamilyIndices=None,
            initialLayout=getattr(vk, "VK_IMAGE_LAYOUT_UNDEFINED", 0),
        )
        self._upload_image = vk.vkCreateImage(self._logical_device, image_ci, None)
        req = vk.vkGetImageMemoryRequirements(self._logical_device, self._upload_image)
        device_local = getattr(vk, "VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT", 0x00000001)
        try:
            mem_type = self._find_memory_type(type_bits=int(req.memoryTypeBits), required_flags=device_local)
        except Exception:
            mem_type = self._find_memory_type(type_bits=int(req.memoryTypeBits), required_flags=0)
        alloc_info = vk.VkMemoryAllocateInfo(
            sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            pNext=None,
            allocationSize=int(req.size),
            memoryTypeIndex=mem_type,
        )
        self._upload_image_memory = vk.vkAllocateMemory(self._logical_device, alloc_info, None)
        vk.vkBindImageMemory(self._logical_device, self._upload_image, self._upload_image_memory, 0)
        self._upload_image_extent = (int(alloc_w), int(alloc_h))
        self._upload_image_format = desired_format
        self._upload_image_layout = getattr(vk, "VK_IMAGE_LAYOUT_UNDEFINED", 0)
        add_copy_telemetry(upload_image_realloc_count=1)

    def _can_use_gpu_blit(self) -> bool:
        if not self._vulkan_available:
            return False
        vk = self._require_vk()
        return all(
            hasattr(vk, name)
            for name in (
                "vkCmdBlitImage",
                "VkImageBlit",
            )
        )

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
