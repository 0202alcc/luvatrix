from __future__ import annotations

import unittest
import os

import torch

from luvatrix_core.platform.macos.vulkan_backend import MoltenVKMacOSBackend
from luvatrix_core.platform.macos.vulkan_presenter import VulkanContext
from luvatrix_core.platform.macos.window_system import MacOSWindowHandle
from luvatrix_core.platform.vulkan_compat import VulkanKHRCompatMixin, decode_vk_string


class _FakeWindowSystem:
    def __init__(self) -> None:
        self.created = 0
        self.destroyed = 0
        self.last_title: str | None = None
        self.last_use_metal_layer: bool | None = None
        self.last_preserve_aspect_ratio: bool | None = None
        self.pumped = 0
        self.open_state = True

    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
    ) -> MacOSWindowHandle:
        self.created += 1
        self.last_title = title
        self.last_use_metal_layer = use_metal_layer
        self.last_preserve_aspect_ratio = preserve_aspect_ratio
        class _Layer:
            def setContents_(self, image) -> None:
                self.last_image = image

        return MacOSWindowHandle(window=object(), layer=_Layer())

    def destroy_window(self, handle: MacOSWindowHandle) -> None:
        self.destroyed += 1

    def pump_events(self) -> None:
        self.pumped += 1

    def is_window_open(self, handle: MacOSWindowHandle) -> bool:
        return self.open_state


class _RecordingBackend(MoltenVKMacOSBackend):
    def __init__(self) -> None:
        super().__init__(window_system=_FakeWindowSystem())
        self.calls: list[str] = []

    def _create_window(self, width: int, height: int, title: str) -> None:
        self.calls.append("create_window")

    def _create_vulkan_instance(self) -> None:
        self.calls.append("create_instance")

    def _pick_physical_device(self) -> None:
        self.calls.append("pick_device")

    def _create_logical_device(self) -> None:
        self.calls.append("create_logical_device")

    def _create_surface(self) -> None:
        self.calls.append("create_surface")

    def _create_swapchain(self, width: int, height: int) -> None:
        self.calls.append("create_swapchain")

    def _create_command_resources(self) -> None:
        self.calls.append("create_command_resources")

    def _create_sync_primitives(self) -> None:
        self.calls.append("create_sync")

    def _acquire_next_swapchain_image(self) -> None:
        self.calls.append("acquire")
        self._current_image_index = 0

    def _upload_rgba_to_staging(self, rgba: torch.Tensor) -> None:
        self.calls.append("upload")

    def _record_and_submit_commands(self, revision: int) -> None:
        self.calls.append("submit")

    def _present_swapchain_image(self) -> None:
        self.calls.append("present")

    def _wait_device_idle(self) -> None:
        self.calls.append("wait_idle")

    def _recreate_swapchain(self, width: int, height: int) -> None:
        self.calls.append("recreate_swapchain")

    def _destroy_sync_primitives(self) -> None:
        self.calls.append("destroy_sync")

    def _destroy_command_resources(self) -> None:
        self.calls.append("destroy_cmd")

    def _destroy_swapchain(self) -> None:
        self.calls.append("destroy_swapchain")

    def _destroy_surface(self) -> None:
        self.calls.append("destroy_surface")

    def _destroy_device(self) -> None:
        self.calls.append("destroy_device")

    def _destroy_instance(self) -> None:
        self.calls.append("destroy_instance")

    def _destroy_window(self) -> None:
        self.calls.append("destroy_window")


class MacOSVulkanBackendTests(unittest.TestCase):
    def test_backend_uses_shared_vulkan_compat_mixin(self) -> None:
        self.assertTrue(issubclass(MoltenVKMacOSBackend, VulkanKHRCompatMixin))

    def test_decode_vk_string_handles_nul_terminated_bytes(self) -> None:
        self.assertEqual(decode_vk_string(b"VK_KHR_surface\x00garbage"), "VK_KHR_surface")

    def test_initialize_runs_expected_sequence(self) -> None:
        backend = _RecordingBackend()
        ctx = backend.initialize(width=4, height=3, title="Demo")
        self.assertEqual(ctx, VulkanContext(width=4, height=3, title="Demo"))
        self.assertEqual(
            backend.calls,
            [
                "create_instance",
                "create_window",
                "create_surface",
                "pick_device",
                "create_logical_device",
                "create_swapchain",
                "create_command_resources",
                "create_sync",
            ],
        )

    def test_present_runs_expected_sequence(self) -> None:
        backend = _RecordingBackend()
        ctx = backend.initialize(width=2, height=2, title="Demo")
        backend.calls.clear()
        backend.present(ctx, torch.zeros((2, 2, 4), dtype=torch.uint8), revision=7)
        self.assertEqual(backend.calls, ["acquire", "upload", "submit", "present"])
        self.assertEqual(backend.frames_presented, 1)

    def test_resize_runs_expected_sequence(self) -> None:
        backend = _RecordingBackend()
        ctx = backend.initialize(width=2, height=2, title="Demo")
        backend.calls.clear()
        out = backend.resize(ctx, width=5, height=6)
        self.assertEqual(out.width, 5)
        self.assertEqual(out.height, 6)
        self.assertEqual(backend.calls, ["wait_idle", "recreate_swapchain"])

    def test_shutdown_runs_expected_sequence(self) -> None:
        backend = _RecordingBackend()
        ctx = backend.initialize(width=2, height=2, title="Demo")
        backend.calls.clear()
        backend.shutdown(ctx)
        self.assertEqual(
            backend.calls,
            [
                "wait_idle",
                "destroy_sync",
                "destroy_cmd",
                "destroy_swapchain",
                "destroy_surface",
                "destroy_device",
                "destroy_instance",
                "destroy_window",
            ],
        )

    def test_present_before_initialize_raises(self) -> None:
        backend = _RecordingBackend()
        with self.assertRaises(RuntimeError):
            backend.present(VulkanContext(width=1, height=1, title="x"), torch.zeros((1, 1, 4), dtype=torch.uint8), 1)

    def test_default_backend_initializes_with_fallback_mode(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        ctx = backend.initialize(2, 2, "Demo")
        self.assertEqual(ctx.width, 2)
        self.assertEqual(ctx.height, 2)
        self.assertFalse(backend._vulkan_available)  # fallback mode expected in test env

    def test_default_backend_present_requires_quartz_in_fallback_mode(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        ctx = backend.initialize(2, 2, "Demo")
        rgba = torch.zeros((2, 2, 4), dtype=torch.uint8)
        try:
            import Quartz  # type: ignore  # noqa: F401
        except Exception:
            with self.assertRaises(RuntimeError):
                backend.present(ctx, rgba, revision=1)
        else:
            backend.present(ctx, rgba, revision=1)

    def test_window_system_is_used_for_create_and_destroy(self) -> None:
        ws = _FakeWindowSystem()
        backend = MoltenVKMacOSBackend(window_system=ws)
        backend.initialize(2, 2, "Demo")
        self.assertEqual(ws.created, 1)
        self.assertFalse(bool(ws.last_preserve_aspect_ratio))
        ctx = VulkanContext(width=2, height=2, title="Demo")
        backend.shutdown(ctx)
        self.assertEqual(ws.destroyed, 1)

    def test_preserve_aspect_ratio_flag_flows_to_window_system(self) -> None:
        ws = _FakeWindowSystem()
        backend = MoltenVKMacOSBackend(window_system=ws, preserve_aspect_ratio=True)
        backend.initialize(2, 2, "Demo")
        self.assertTrue(bool(ws.last_preserve_aspect_ratio))

    def test_should_close_and_pump_events_delegate_to_window_system(self) -> None:
        ws = _FakeWindowSystem()
        backend = MoltenVKMacOSBackend(window_system=ws)
        backend.initialize(2, 2, "Demo")
        self.assertFalse(backend.should_close())
        backend.pump_events()
        self.assertEqual(ws.pumped, 1)
        ws.open_state = False
        self.assertTrue(backend.should_close())

    def test_vulkan_instance_and_device_bootstrap_with_fake_vk(self) -> None:
        class _QueueProps:
            def __init__(self, count: int, flags: int) -> None:
                self.queueCount = count
                self.queueFlags = flags

        class _FakeVk:
            VK_STRUCTURE_TYPE_APPLICATION_INFO = 1
            VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 2
            VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO = 3
            VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO = 4
            VK_QUEUE_GRAPHICS_BIT = 0x00000001
            VK_KHR_SURFACE_EXTENSION_NAME = "VK_KHR_surface"
            VK_EXT_METAL_SURFACE_EXTENSION_NAME = "VK_EXT_metal_surface"
            VK_KHR_SWAPCHAIN_EXTENSION_NAME = "VK_KHR_swapchain"
            VK_API_VERSION_1_0 = 1
            VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT = 1000217000

            @staticmethod
            def VK_MAKE_VERSION(major: int, minor: int, patch: int) -> int:
                return (major << 22) | (minor << 12) | patch

            @staticmethod
            def VkApplicationInfo(**kwargs):
                return kwargs

            @staticmethod
            def VkInstanceCreateInfo(**kwargs):
                return kwargs

            @staticmethod
            def VkDeviceQueueCreateInfo(**kwargs):
                return kwargs

            @staticmethod
            def VkDeviceCreateInfo(**kwargs):
                return kwargs

            @staticmethod
            def VkMetalSurfaceCreateInfoEXT(**kwargs):
                return kwargs

            @staticmethod
            def vkEnumerateInstanceExtensionProperties(layer_name):
                class _Ext:
                    extensionName = "VK_EXT_metal_surface"

                return [_Ext()]

            @staticmethod
            def vkCreateInstance(ci, allocator):
                return "instance-handle"

            @staticmethod
            def vkEnumeratePhysicalDevices(instance):
                return ["gpu0"]

            @staticmethod
            def vkEnumerateDeviceExtensionProperties(device, layer_name):
                class _Ext:
                    def __init__(self, name: str) -> None:
                        self.extensionName = name

                return [_Ext("VK_KHR_swapchain")]

            @staticmethod
            def vkGetPhysicalDeviceQueueFamilyProperties(device):
                return [_QueueProps(count=1, flags=_FakeVk.VK_QUEUE_GRAPHICS_BIT)]

            @staticmethod
            def vkGetPhysicalDeviceSurfaceSupportKHR(device, queue_family_idx, surface):
                return True

            @staticmethod
            def vkCreateDevice(device, ci, allocator):
                return "logical-device"

            @staticmethod
            def vkCreateMetalSurfaceEXT(instance, ci, allocator):
                return "surface"

            @staticmethod
            def vkGetDeviceQueue(device, queue_family_idx, queue_idx):
                return ("queue", queue_family_idx, queue_idx)

            @staticmethod
            def vkGetPhysicalDeviceSurfaceCapabilitiesKHR(device, surface):
                class _Extent:
                    width = 2
                    height = 2

                class _Caps:
                    minImageCount = 1
                    maxImageCount = 2
                    currentExtent = _Extent()
                    minImageExtent = _Extent()
                    maxImageExtent = _Extent()
                    currentTransform = 0

                return _Caps()

            @staticmethod
            def vkGetPhysicalDeviceSurfaceFormatsKHR(device, surface):
                class _Fmt:
                    format = 44
                    colorSpace = 0

                return [_Fmt()]

            @staticmethod
            def vkGetPhysicalDeviceSurfacePresentModesKHR(device, surface):
                return [2]

            @staticmethod
            def vkCreateSwapchainKHR(device, ci, allocator):
                return "swapchain"

            @staticmethod
            def vkGetSwapchainImagesKHR(device, swapchain):
                return ["img0"]

            @staticmethod
            def vkAcquireNextImageKHR(device, swapchain, timeout, semaphore, fence):
                return 0

            @staticmethod
            def vkQueuePresentKHR(queue, present_info):
                return None

            @staticmethod
            def vkDestroySurfaceKHR(instance, surface, allocator):
                return None

            @staticmethod
            def vkDestroySwapchainKHR(device, swapchain, allocator):
                return None

            @staticmethod
            def vkDeviceWaitIdle(device):
                return None

            @staticmethod
            def vkDestroyDevice(device, allocator):
                return None

            @staticmethod
            def vkDestroyInstance(instance, allocator):
                return None

        class _DeviceOnlyBackend(MoltenVKMacOSBackend):
            def _create_window(self, width: int, height: int, title: str) -> None:
                return

            def _create_surface(self) -> None:
                self._surface = "surface"

            def _create_swapchain(self, width: int, height: int) -> None:
                self._swapchain = (width, height)

            def _create_command_resources(self) -> None:
                return

            def _create_sync_primitives(self) -> None:
                return

            def _destroy_sync_primitives(self) -> None:
                return

            def _destroy_command_resources(self) -> None:
                return

            def _destroy_swapchain(self) -> None:
                return

            def _destroy_surface(self) -> None:
                return

            def _destroy_window(self) -> None:
                return

        old = os.environ.get("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN")
        os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = "1"
        try:
            backend = _DeviceOnlyBackend(window_system=_FakeWindowSystem())
            backend._vk = _FakeVk()
            ctx = backend.initialize(2, 2, "Demo")
            self.assertEqual(ctx.width, 2)
            self.assertTrue(backend._vulkan_available)
            self.assertEqual(backend._instance, "instance-handle")
            self.assertEqual(backend._physical_device, "gpu0")
            self.assertEqual(backend._queue_family_index, 0)
            self.assertEqual(backend._logical_device, "logical-device")
            self.assertEqual(backend._graphics_queue, ("queue", 0, 0))
            backend.shutdown(ctx)
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", None)
            else:
                os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = old

    def test_swapchain_usage_includes_transfer_dst(self) -> None:
        class _Extent:
            def __init__(self, w: int, h: int) -> None:
                self.width = w
                self.height = h

        class _Caps:
            minImageCount = 1
            maxImageCount = 3
            currentExtent = _Extent(0xFFFFFFFF, 0xFFFFFFFF)
            minImageExtent = _Extent(64, 64)
            maxImageExtent = _Extent(4096, 4096)
            currentTransform = 0

        class _Format:
            format = 44
            colorSpace = 0

        class _FakeVk:
            VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR = 1000
            VK_TRUE = 1
            VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT = 0x10
            VK_IMAGE_USAGE_TRANSFER_DST_BIT = 0x2
            VK_PRESENT_MODE_FIFO_KHR = 2

            def __init__(self) -> None:
                self.last_swapchain_ci = None

            @staticmethod
            def VkSwapchainCreateInfoKHR(**kwargs):
                return kwargs

            @staticmethod
            def vkGetPhysicalDeviceSurfaceCapabilitiesKHR(device, surface):
                return _Caps()

            @staticmethod
            def vkGetPhysicalDeviceSurfaceFormatsKHR(device, surface):
                return [_Format()]

            @staticmethod
            def vkGetPhysicalDeviceSurfacePresentModesKHR(device, surface):
                return [_FakeVk.VK_PRESENT_MODE_FIFO_KHR]

            def vkCreateSwapchainKHR(self, device, ci, allocator):
                self.last_swapchain_ci = ci
                return "swapchain"

            @staticmethod
            def vkGetSwapchainImagesKHR(device, swapchain):
                return ["image0", "image1"]

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        fake_vk = _FakeVk()
        backend._vk = fake_vk
        backend._vulkan_available = True
        backend._physical_device = "gpu0"
        backend._logical_device = "device0"
        backend._surface = "surface0"

        backend._create_swapchain(320, 180)

        assert fake_vk.last_swapchain_ci is not None
        expected_flags = _FakeVk.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | _FakeVk.VK_IMAGE_USAGE_TRANSFER_DST_BIT
        self.assertEqual(int(fake_vk.last_swapchain_ci["imageUsage"]), expected_flags)

    def test_acquire_next_image_accepts_tuple_result(self) -> None:
        class _FakeVk:
            VK_TRUE = 1

            @staticmethod
            def vkWaitForFences(device, fence_count, fences, wait_all, timeout):
                return None

            @staticmethod
            def vkResetFences(device, fence_count, fences):
                return None

            @staticmethod
            def vkAcquireNextImageKHR(device, swapchain, timeout, semaphore, fence):
                return (0, 2)

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        backend._vulkan_available = True
        backend._logical_device = "device"
        backend._swapchain = "swapchain"
        backend._in_flight_fence = "fence"
        backend._image_available_semaphore = "semaphore"

        backend._acquire_next_swapchain_image()

        self.assertEqual(backend._current_image_index, 2)

    def test_acquire_next_image_suboptimal_recreates_swapchain(self) -> None:
        class _FakeVk:
            VK_TRUE = 1
            VK_SUBOPTIMAL_KHR = 1000001003

            @staticmethod
            def vkWaitForFences(device, fence_count, fences, wait_all, timeout):
                return None

            @staticmethod
            def vkResetFences(device, fence_count, fences):
                return None

            @staticmethod
            def vkAcquireNextImageKHR(device, swapchain, timeout, semaphore, fence):
                return (_FakeVk.VK_SUBOPTIMAL_KHR, 0)

        class _Backend(MoltenVKMacOSBackend):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.recreated = False

            def _handle_swapchain_invalidation(self) -> None:
                self.recreated = True

        backend = _Backend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        backend._vulkan_available = True
        backend._logical_device = "device"
        backend._swapchain = "swapchain"
        backend._in_flight_fence = "fence"
        backend._image_available_semaphore = "semaphore"

        backend._acquire_next_swapchain_image()

        self.assertIsNone(backend._current_image_index)
        self.assertTrue(backend.recreated)

    def test_acquire_next_image_skips_frame_on_fence_timeout(self) -> None:
        class _FakeVk:
            VK_TRUE = 1
            VK_TIMEOUT = 2

            @staticmethod
            def vkWaitForFences(device, fence_count, fences, wait_all, timeout):
                return _FakeVk.VK_TIMEOUT

            @staticmethod
            def vkResetFences(device, fence_count, fences):
                raise AssertionError("vkResetFences should not be called on wait timeout")

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        backend._vulkan_available = True
        backend._logical_device = "device"
        backend._swapchain = "swapchain"
        backend._in_flight_fence = "fence"
        backend._image_available_semaphore = "semaphore"

        backend._acquire_next_swapchain_image()

        self.assertIsNone(backend._current_image_index)

    def test_acquire_next_image_skips_frame_on_fence_timeout_exception(self) -> None:
        class VkTimeout(Exception):
            pass

        class _FakeVk:
            VK_TRUE = 1

            @staticmethod
            def vkWaitForFences(device, fence_count, fences, wait_all, timeout):
                raise VkTimeout()

            @staticmethod
            def vkResetFences(device, fence_count, fences):
                raise AssertionError("vkResetFences should not be called on wait timeout")

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        backend._vulkan_available = True
        backend._logical_device = "device"
        backend._swapchain = "swapchain"
        backend._in_flight_fence = "fence"
        backend._image_available_semaphore = "semaphore"

        backend._acquire_next_swapchain_image()

        self.assertIsNone(backend._current_image_index)

    def test_acquire_timeout_streak_triggers_swapchain_recreate(self) -> None:
        class _FakeVk:
            VK_TRUE = 1
            VK_TIMEOUT = 2

            @staticmethod
            def vkWaitForFences(device, fence_count, fences, wait_all, timeout):
                return _FakeVk.VK_TIMEOUT

            @staticmethod
            def vkResetFences(device, fence_count, fences):
                raise AssertionError("vkResetFences should not be called on wait timeout")

        class _Backend(MoltenVKMacOSBackend):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.recreated = 0

            def _handle_swapchain_invalidation(self) -> None:
                self.recreated += 1
                self._consecutive_acquire_timeouts = 0

        backend = _Backend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        backend._vulkan_available = True
        backend._logical_device = "device"
        backend._swapchain = "swapchain"
        backend._in_flight_fence = "fence"
        backend._image_available_semaphore = "semaphore"

        backend._acquire_next_swapchain_image()
        backend._acquire_next_swapchain_image()
        backend._acquire_next_swapchain_image()

        self.assertEqual(backend.recreated, 1)

    def test_upload_rgba_to_staging_supports_cffi_buffer_return(self) -> None:
        class _FakeFFI:
            @staticmethod
            def from_buffer(buf):
                return buf

            @staticmethod
            def memmove(dst, src, n):
                dst[:n] = src[:n]

        class _FakeVk:
            def __init__(self) -> None:
                self.ffi = _FakeFFI()
                self.mapped = bytearray(16)
                self.unmapped = False

            def vkMapMemory(self, device, memory, offset, size, flags):
                self.mapped = bytearray(size)
                return self.mapped

            def vkUnmapMemory(self, device, memory):
                self.unmapped = True

        class _UploadBackend(MoltenVKMacOSBackend):
            def _ensure_staging_buffer(self, required_size: int) -> None:
                self._staging_size = required_size
                self._staging_memory = "staging-memory"

        backend = _UploadBackend(window_system=_FakeWindowSystem())
        fake_vk = _FakeVk()
        backend._vk = fake_vk
        backend._vulkan_available = True
        backend._logical_device = "device"
        backend._physical_device = "gpu"
        rgba = torch.tensor([[[1, 2, 3, 4]]], dtype=torch.uint8)

        backend._upload_rgba_to_staging(rgba)

        self.assertEqual(bytes(fake_vk.mapped), bytes([1, 2, 3, 4]))
        self.assertTrue(fake_vk.unmapped)

    def test_upload_frame_stretches_to_swapchain_extent_when_enabled(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem(), preserve_aspect_ratio=False)
        backend._swapchain_extent = (4, 2)
        src = torch.zeros((1, 2, 4), dtype=torch.uint8)
        src[:, :, 0] = 10
        src[:, :, 1] = 20
        src[:, :, 2] = 30
        src[:, :, 3] = 255

        out = backend._prepare_upload_frame(src)

        self.assertEqual(tuple(out.shape), (2, 4, 4))
        self.assertEqual(int(out[0, 0, 0].item()), 10)
        self.assertEqual(int(out[0, 0, 3].item()), 255)

    def test_upload_frame_preserve_aspect_letterboxes(self) -> None:
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem(), preserve_aspect_ratio=True)
        backend._swapchain_extent = (4, 4)  # square window
        src = torch.zeros((1, 4, 4), dtype=torch.uint8)  # very wide frame
        src[:, :, 0] = 50
        src[:, :, 1] = 100
        src[:, :, 2] = 150
        src[:, :, 3] = 255

        out = backend._prepare_upload_frame(src)

        self.assertEqual(tuple(out.shape), (4, 4, 4))
        # Top and bottom rows should be black bars.
        self.assertTrue(torch.equal(out[0, :, :3], torch.zeros((4, 3), dtype=torch.uint8)))
        self.assertTrue(torch.equal(out[3, :, :3], torch.zeros((4, 3), dtype=torch.uint8)))
        # Center rows should contain the source colors.
        self.assertEqual(int(out[1, 0, 0].item()), 50)
        self.assertEqual(int(out[1, 0, 1].item()), 100)
        self.assertEqual(int(out[1, 0, 2].item()), 150)

    def test_vk_instance_uses_mvk_surface_extension_when_metal_missing(self) -> None:
        class _FakeVk:
            VK_STRUCTURE_TYPE_APPLICATION_INFO = 1
            VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 2
            VK_KHR_SURFACE_EXTENSION_NAME = "VK_KHR_surface"
            VK_API_VERSION_1_0 = 1

            @staticmethod
            def VK_MAKE_VERSION(major: int, minor: int, patch: int) -> int:
                return (major << 22) | (minor << 12) | patch

            @staticmethod
            def VkApplicationInfo(**kwargs):
                return kwargs

            @staticmethod
            def VkInstanceCreateInfo(**kwargs):
                return kwargs

            @staticmethod
            def vkEnumerateInstanceExtensionProperties(layer_name):
                class _Ext:
                    def __init__(self, name: str) -> None:
                        self.extensionName = name

                return [_Ext("VK_MVK_macos_surface")]

            @staticmethod
            def vkCreateInstance(ci, allocator):
                return ci

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        ci = backend._vk_create_instance()

        enabled = list(ci["ppEnabledExtensionNames"])
        self.assertIn("VK_KHR_surface", enabled)
        self.assertIn("VK_MVK_macos_surface", enabled)

    def test_experimental_mode_falls_back_when_surface_symbols_missing(self) -> None:
        class _FakeVkNoSurface:
            pass

        old = os.environ.get("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN")
        os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = "1"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            backend._vk = _FakeVkNoSurface()
            backend._create_vulkan_instance()
            self.assertFalse(backend._vulkan_available)
            note = str(backend._vulkan_note)
            self.assertTrue(
                ("missing macOS surface symbols" in note) or ("instance initialization failed" in note)
            )
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", None)
            else:
                os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = old

    def test_experimental_mode_falls_back_when_khr_wrappers_missing(self) -> None:
        class _FakeVkMissingKhr:
            VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT = 1000217000

            @staticmethod
            def VkMetalSurfaceCreateInfoEXT(**kwargs):
                return kwargs

            @staticmethod
            def vkCreateMetalSurfaceEXT(instance, ci, allocator):
                return "surface"

        old = os.environ.get("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN")
        os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = "1"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            backend._vk = _FakeVkMissingKhr()
            backend._create_vulkan_instance()
            self.assertFalse(backend._vulkan_available)
            self.assertIn("missing required KHR surface/swapchain call path", str(backend._vulkan_note))
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", None)
            else:
                os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = old


if __name__ == "__main__":
    unittest.main()
