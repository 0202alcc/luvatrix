from __future__ import annotations

import unittest
import os
from unittest.mock import patch

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

    def test_fallback_clean_does_not_mutate_cametal_contents(self) -> None:
        class _Size:
            width = 64.0
            height = 32.0

        class _Bounds:
            size = _Size()

        class _ContentView:
            def __init__(self) -> None:
                self._bounds = _Bounds()

            def bounds(self):
                return self._bounds

        class _Window:
            def __init__(self) -> None:
                self._content = _ContentView()

            def contentView(self):
                return self._content

            def backingScaleFactor(self):
                return 2.0

        class CAMetalLayer:
            def __init__(self) -> None:
                self.set_contents_calls = 0
                self.sublayers: list[object] = []

            def setFrame_(self, bounds) -> None:
                self.bounds = bounds

            def setContentsScale_(self, scale) -> None:
                self.scale = scale

            def setContents_(self, image) -> None:
                self.set_contents_calls += 1

            def addSublayer_(self, layer) -> None:
                self.sublayers.append(layer)

        class _FallbackLayer:
            def __init__(self) -> None:
                self.set_contents_calls = 0

            def setFrame_(self, bounds) -> None:
                self.bounds = bounds

            def setContentsScale_(self, scale) -> None:
                self.scale = scale

            def setContentsGravity_(self, gravity) -> None:
                self.gravity = gravity

            def setBackgroundColor_(self, color) -> None:
                self.bg = color

            def setContents_(self, image) -> None:
                self.set_contents_calls += 1

            def setNeedsDisplay(self) -> None:
                pass

        class _CALayerFactory:
            @staticmethod
            def layer():
                return _FallbackLayer()

        class _FakeQuartz:
            CALayer = _CALayerFactory
            kCGBitmapByteOrder32Big = 1
            kCGImageAlphaPremultipliedLast = 2
            kCGRenderingIntentDefault = 0

            @staticmethod
            def CFDataCreate(_, data, length):
                return data[:length]

            @staticmethod
            def CGDataProviderCreateWithCFData(data):
                return data

            @staticmethod
            def CGColorSpaceCreateDeviceRGB():
                return "rgb"

            @staticmethod
            def CGImageCreate(*args, **kwargs):
                return object()

            @staticmethod
            def CGColorCreateGenericRGB(r, g, b, a):
                return (r, g, b, a)

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        host_layer = CAMetalLayer()
        backend._window_handle = MacOSWindowHandle(window=_Window(), layer=host_layer)
        backend._pending_rgba = torch.zeros((32, 64, 4), dtype=torch.uint8)
        with patch.dict("sys.modules", {"Quartz": _FakeQuartz}):
            with patch.dict(os.environ, {"LUVATRIX_ENABLE_LEGACY_CAMETAL_FALLBACK": "0"}, clear=False):
                backend._present_fallback_to_layer()

        self.assertEqual(backend._active_present_path, "fallback_clean")
        self.assertEqual(host_layer.set_contents_calls, 0)
        self.assertIsNotNone(backend._fallback_blit_layer)
        self.assertEqual(backend._fallback_blit_layer.set_contents_calls, 1)

    def test_fallback_legacy_requires_env_opt_in(self) -> None:
        class _Size:
            width = 64.0
            height = 32.0

        class _Bounds:
            size = _Size()

        class _ContentView:
            def __init__(self) -> None:
                self._bounds = _Bounds()

            def bounds(self):
                return self._bounds

        class _Window:
            def __init__(self) -> None:
                self._content = _ContentView()

            def contentView(self):
                return self._content

            def backingScaleFactor(self):
                return 2.0

        class CAMetalLayer:
            def __init__(self) -> None:
                self.set_contents_calls = 0

            def setFrame_(self, bounds) -> None:
                self.bounds = bounds

            def setContentsScale_(self, scale) -> None:
                self.scale = scale

            def setContents_(self, image) -> None:
                self.set_contents_calls += 1

            def setNeedsDisplay(self) -> None:
                pass

        class _FakeQuartz:
            kCGBitmapByteOrder32Big = 1
            kCGImageAlphaPremultipliedLast = 2
            kCGRenderingIntentDefault = 0

            @staticmethod
            def CFDataCreate(_, data, length):
                return data[:length]

            @staticmethod
            def CGDataProviderCreateWithCFData(data):
                return data

            @staticmethod
            def CGColorSpaceCreateDeviceRGB():
                return "rgb"

            @staticmethod
            def CGImageCreate(*args, **kwargs):
                return object()

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        host_layer = CAMetalLayer()
        backend._window_handle = MacOSWindowHandle(window=_Window(), layer=host_layer)
        backend._pending_rgba = torch.zeros((32, 64, 4), dtype=torch.uint8)
        with patch.dict("sys.modules", {"Quartz": _FakeQuartz}):
            with patch.dict(os.environ, {"LUVATRIX_ENABLE_LEGACY_CAMETAL_FALLBACK": "1"}, clear=False):
                backend._present_fallback_to_layer()

        self.assertEqual(backend._active_present_path, "fallback_legacy")
        self.assertEqual(host_layer.set_contents_calls, 1)

    def test_fallback_clean_replaces_content_view_layer_when_supported(self) -> None:
        class _Size:
            width = 80.0
            height = 40.0

        class _Bounds:
            size = _Size()

        class _ContentView:
            def __init__(self) -> None:
                self._bounds = _Bounds()
                self.layer = None

            def bounds(self):
                return self._bounds

            def setWantsLayer_(self, value) -> None:
                self.wants_layer = bool(value)

            def setLayer_(self, layer) -> None:
                self.layer = layer

        class _Window:
            def __init__(self) -> None:
                self._content = _ContentView()

            def contentView(self):
                return self._content

            def backingScaleFactor(self):
                return 2.0

        class CAMetalLayer:
            def __init__(self) -> None:
                self.set_contents_calls = 0

            def setFrame_(self, bounds) -> None:
                self.bounds = bounds

            def setContentsScale_(self, scale) -> None:
                self.scale = scale

            def setContents_(self, image) -> None:
                self.set_contents_calls += 1

        class _FallbackLayer:
            def __init__(self) -> None:
                self.set_contents_calls = 0

            def setFrame_(self, bounds) -> None:
                self.bounds = bounds

            def setContentsScale_(self, scale) -> None:
                self.scale = scale

            def setContentsGravity_(self, gravity) -> None:
                self.gravity = gravity

            def setBackgroundColor_(self, color) -> None:
                self.bg = color

            def setContents_(self, image) -> None:
                self.set_contents_calls += 1

            def setNeedsDisplay(self) -> None:
                pass

        class _CALayerFactory:
            @staticmethod
            def layer():
                return _FallbackLayer()

        class _FakeQuartz:
            CALayer = _CALayerFactory
            kCGBitmapByteOrder32Big = 1
            kCGImageAlphaPremultipliedLast = 2
            kCGRenderingIntentDefault = 0

            @staticmethod
            def CFDataCreate(_, data, length):
                return data[:length]

            @staticmethod
            def CGDataProviderCreateWithCFData(data):
                return data

            @staticmethod
            def CGColorSpaceCreateDeviceRGB():
                return "rgb"

            @staticmethod
            def CGImageCreate(*args, **kwargs):
                return object()

            @staticmethod
            def CGColorCreateGenericRGB(r, g, b, a):
                return (r, g, b, a)

        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        window = _Window()
        host_layer = CAMetalLayer()
        backend._window_handle = MacOSWindowHandle(window=window, layer=host_layer)
        backend._pending_rgba = torch.zeros((40, 80, 4), dtype=torch.uint8)
        with patch.dict("sys.modules", {"Quartz": _FakeQuartz}):
            with patch.dict(os.environ, {"LUVATRIX_ENABLE_LEGACY_CAMETAL_FALLBACK": "0"}, clear=False):
                backend._present_fallback_to_layer()

        self.assertEqual(backend._active_present_path, "fallback_clean")
        self.assertEqual(host_layer.set_contents_calls, 0)
        self.assertIsNotNone(window.contentView().layer)
        self.assertIs(window.contentView().layer, backend._fallback_blit_layer)
        self.assertTrue(backend._fallback_replaced_content_layer)

    def test_present_swapchain_sets_vulkan_present_path(self) -> None:
        class _FakeVk:
            VK_STRUCTURE_TYPE_PRESENT_INFO_KHR = 100

            @staticmethod
            def VkPresentInfoKHR(**kwargs):
                return kwargs

        class _Backend(MoltenVKMacOSBackend):
            def _vk_queue_present(self, queue, present_info) -> None:
                return

        backend = _Backend(window_system=_FakeWindowSystem())
        backend._vk = _FakeVk()
        backend._vulkan_available = True
        backend._graphics_queue = "queue"
        backend._swapchain = "swapchain"
        backend._render_finished_semaphore = "sem"
        backend._current_image_index = 0

        backend._present_swapchain_image()

        self.assertEqual(backend._active_present_path, "vulkan")

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

            def _ensure_upload_image(self, width: int, height: int) -> None:
                self._upload_image = "upload-image"
                self._upload_image_extent = (width, height)

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

    def test_fixed_internal_render_scale_is_parsed_and_quantized(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "0.8"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            self.assertEqual(backend._render_scale_fixed, 0.75)
            self.assertEqual(backend._effective_render_scale(), 0.75)
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old

    def test_prepare_fallback_frame_applies_render_scale(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "0.5"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            src = torch.zeros((120, 200, 4), dtype=torch.uint8)
            out = backend._prepare_fallback_frame(src)
            self.assertEqual(tuple(out.shape), (60, 100, 4))
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old

    def test_prepare_scaled_source_frame_applies_internal_scale(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "0.5"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            src = torch.zeros((120, 200, 4), dtype=torch.uint8)
            out = backend._prepare_scaled_source_frame(src)
            self.assertEqual(tuple(out.shape), (60, 100, 4))
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old

    def test_prepare_upload_frame_defaults_to_no_internal_scale_for_vulkan(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        old_vulkan = os.environ.get("LUVATRIX_VULKAN_INTERNAL_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "0.5"
        os.environ["LUVATRIX_VULKAN_INTERNAL_SCALE"] = "0"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem(), preserve_aspect_ratio=False)
            backend._swapchain_extent = (400, 200)
            src = torch.zeros((100, 200, 4), dtype=torch.uint8)
            out = backend._prepare_upload_frame(src)
            self.assertEqual(tuple(out.shape), (200, 400, 4))
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old
            if old_vulkan is None:
                os.environ.pop("LUVATRIX_VULKAN_INTERNAL_SCALE", None)
            else:
                os.environ["LUVATRIX_VULKAN_INTERNAL_SCALE"] = old_vulkan

    def test_prepare_upload_frame_applies_internal_scale_when_vulkan_opt_in_enabled(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        old_vulkan = os.environ.get("LUVATRIX_VULKAN_INTERNAL_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "0.5"
        os.environ["LUVATRIX_VULKAN_INTERNAL_SCALE"] = "1"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem(), preserve_aspect_ratio=False)
            backend._swapchain_extent = (400, 200)
            src = torch.zeros((100, 200, 4), dtype=torch.uint8)
            out = backend._prepare_upload_frame(src)
            self.assertEqual(tuple(out.shape), (200, 400, 4))
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old
            if old_vulkan is None:
                os.environ.pop("LUVATRIX_VULKAN_INTERNAL_SCALE", None)
            else:
                os.environ["LUVATRIX_VULKAN_INTERNAL_SCALE"] = old_vulkan

    def test_prepare_upload_frame_uses_source_extent_when_gpu_blit_available(self) -> None:
        old = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = "1.0"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem(), preserve_aspect_ratio=False)
            backend._vulkan_available = True
            backend._swapchain_extent = (400, 200)
            backend._vk = type(
                "_FakeVk",
                (),
                {
                    "vkCmdBlitImage": lambda *args, **kwargs: None,
                    "VkImageBlit": lambda *args, **kwargs: None,
                },
            )()
            src = torch.zeros((100, 200, 4), dtype=torch.uint8)
            out = backend._prepare_upload_frame(src)
            self.assertEqual(tuple(out.shape), (100, 200, 4))
        finally:
            if old is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old

    def test_auto_render_scale_steps_down_on_high_present_cost(self) -> None:
        old_fixed = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        old_auto = os.environ.get("LUVATRIX_AUTO_RENDER_SCALE")
        os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
        os.environ["LUVATRIX_AUTO_RENDER_SCALE"] = "1"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            self.assertEqual(backend._render_scale_current, 1.0)
            for _ in range(20):
                backend._update_render_scale(elapsed_ms=24.0, fallback_active=True)
            self.assertIn(backend._render_scale_current, (0.75, 0.5))
        finally:
            if old_fixed is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old_fixed
            if old_auto is None:
                os.environ.pop("LUVATRIX_AUTO_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_AUTO_RENDER_SCALE"] = old_auto

    def test_auto_render_scale_steps_up_when_headroom_returns(self) -> None:
        old_fixed = os.environ.get("LUVATRIX_INTERNAL_RENDER_SCALE")
        old_auto = os.environ.get("LUVATRIX_AUTO_RENDER_SCALE")
        os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
        os.environ["LUVATRIX_AUTO_RENDER_SCALE"] = "1"
        try:
            backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
            backend._render_scale_current = 0.5
            backend._render_scale_cooldown_frames = 0
            backend._present_time_ema_ms = 8.0
            for _ in range(2):
                backend._update_render_scale(elapsed_ms=8.0, fallback_active=True)
            self.assertEqual(backend._render_scale_current, 0.75)
        finally:
            if old_fixed is None:
                os.environ.pop("LUVATRIX_INTERNAL_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_INTERNAL_RENDER_SCALE"] = old_fixed
            if old_auto is None:
                os.environ.pop("LUVATRIX_AUTO_RENDER_SCALE", None)
            else:
                os.environ["LUVATRIX_AUTO_RENDER_SCALE"] = old_auto


if __name__ == "__main__":
    unittest.main()
