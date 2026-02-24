from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any


class SwapchainOutOfDateError(RuntimeError):
    """Vulkan swapchain became invalid due to resize/minimize or surface change."""


def decode_vk_string(value: Any) -> str:
    if isinstance(value, bytes):
        return value.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    return str(value)


class VulkanKHRCompatMixin:
    """Reusable dynamic Vulkan KHR/proc-loader path for python Vulkan bindings."""

    def _supports_required_khr_path(self) -> bool:
        vk = self._require_vk()
        required = (
            "vkGetPhysicalDeviceSurfaceSupportKHR",
            "vkGetPhysicalDeviceSurfaceCapabilitiesKHR",
            "vkGetPhysicalDeviceSurfaceFormatsKHR",
            "vkGetPhysicalDeviceSurfacePresentModesKHR",
            "vkCreateSwapchainKHR",
            "vkGetSwapchainImagesKHR",
            "vkAcquireNextImageKHR",
            "vkQueuePresentKHR",
            "vkDestroySurfaceKHR",
            "vkDestroySwapchainKHR",
        )
        if all(hasattr(vk, name) for name in required):
            return True
        return self._supports_dynamic_khr_path()

    def _supports_dynamic_khr_path(self) -> bool:
        vk = self._require_vk()
        if not hasattr(vk, "ffi"):
            return False
        try:
            lib = self._load_vulkan_loader_lib()
            return hasattr(lib, "vkGetInstanceProcAddr")
        except Exception:  # noqa: BLE001
            return False

    def _get_vk_proc(self, name: str, restype, argtypes):
        if name in self._vk_proc_cache:
            return self._vk_proc_cache[name]
        if self._instance is None:
            raise RuntimeError(f"Vulkan instance is required before resolving {name}")
        lib = self._load_vulkan_loader_lib()
        lib.vkGetInstanceProcAddr.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.vkGetInstanceProcAddr.restype = ctypes.c_void_p
        proc_addr = lib.vkGetInstanceProcAddr(self._instance_as_void_p(), name.encode("utf-8"))
        if not proc_addr:
            raise RuntimeError(f"Vulkan procedure not found: {name}")
        fn = ctypes.CFUNCTYPE(restype, *argtypes)(proc_addr)
        self._vk_proc_cache[name] = fn
        return fn

    def _vk_get_physical_device_surface_support(self, device, queue_family_index: int, surface) -> bool:
        vk = self._require_vk()
        if hasattr(vk, "vkGetPhysicalDeviceSurfaceSupportKHR"):
            return bool(vk.vkGetPhysicalDeviceSurfaceSupportKHR(device, queue_family_index, surface))
        out_supported = ctypes.c_uint32(0)
        fn = self._get_vk_proc(
            "vkGetPhysicalDeviceSurfaceSupportKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)],
        )
        result = int(
            fn(
                self._handle_as_void_p(device),
                ctypes.c_uint32(queue_family_index),
                self._handle_as_void_p(surface),
                ctypes.byref(out_supported),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetPhysicalDeviceSurfaceSupportKHR returned VkResult={result}")
        return bool(out_supported.value)

    def _vk_get_surface_capabilities(self, physical_device, surface):
        vk = self._require_vk()
        if hasattr(vk, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR"):
            return vk.vkGetPhysicalDeviceSurfaceCapabilitiesKHR(physical_device, surface)
        out_caps = vk.VkSurfaceCapabilitiesKHR()
        fn = self._get_vk_proc(
            "vkGetPhysicalDeviceSurfaceCapabilitiesKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
        )
        result = int(
            fn(
                self._handle_as_void_p(physical_device),
                self._handle_as_void_p(surface),
                self._struct_addr(out_caps),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetPhysicalDeviceSurfaceCapabilitiesKHR returned VkResult={result}")
        return out_caps

    def _vk_get_surface_formats(self, physical_device, surface):
        vk = self._require_vk()
        if hasattr(vk, "vkGetPhysicalDeviceSurfaceFormatsKHR"):
            return vk.vkGetPhysicalDeviceSurfaceFormatsKHR(physical_device, surface)
        count = ctypes.c_uint32(0)
        fn = self._get_vk_proc(
            "vkGetPhysicalDeviceSurfaceFormatsKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p],
        )
        result = int(
            fn(
                self._handle_as_void_p(physical_device),
                self._handle_as_void_p(surface),
                ctypes.byref(count),
                None,
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetPhysicalDeviceSurfaceFormatsKHR(count) returned VkResult={result}")
        if count.value == 0:
            return []
        formats = vk.ffi.new("VkSurfaceFormatKHR[]", int(count.value))
        result = int(
            fn(
                self._handle_as_void_p(physical_device),
                self._handle_as_void_p(surface),
                ctypes.byref(count),
                ctypes.c_void_p(int(vk.ffi.cast("uintptr_t", formats))),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetPhysicalDeviceSurfaceFormatsKHR(data) returned VkResult={result}")
        return [formats[i] for i in range(int(count.value))]

    def _vk_get_surface_present_modes(self, physical_device, surface):
        vk = self._require_vk()
        if hasattr(vk, "vkGetPhysicalDeviceSurfacePresentModesKHR"):
            return vk.vkGetPhysicalDeviceSurfacePresentModesKHR(physical_device, surface)
        count = ctypes.c_uint32(0)
        fn = self._get_vk_proc(
            "vkGetPhysicalDeviceSurfacePresentModesKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p],
        )
        result = int(
            fn(
                self._handle_as_void_p(physical_device),
                self._handle_as_void_p(surface),
                ctypes.byref(count),
                None,
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetPhysicalDeviceSurfacePresentModesKHR(count) returned VkResult={result}")
        if count.value == 0:
            return []
        modes = (ctypes.c_int32 * int(count.value))()
        result = int(
            fn(
                self._handle_as_void_p(physical_device),
                self._handle_as_void_p(surface),
                ctypes.byref(count),
                ctypes.cast(modes, ctypes.c_void_p),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetPhysicalDeviceSurfacePresentModesKHR(data) returned VkResult={result}")
        return [int(modes[i]) for i in range(int(count.value))]

    def _vk_create_swapchain(self, logical_device, swapchain_ci):
        vk = self._require_vk()
        if hasattr(vk, "vkCreateSwapchainKHR"):
            return vk.vkCreateSwapchainKHR(logical_device, swapchain_ci, None)
        out_swapchain = ctypes.c_uint64(0)
        fn = self._get_vk_proc(
            "vkCreateSwapchainKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)],
        )
        result = int(
            fn(
                self._handle_as_void_p(logical_device),
                self._struct_addr(swapchain_ci),
                None,
                ctypes.byref(out_swapchain),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkCreateSwapchainKHR returned VkResult={result}")
        return vk.ffi.cast("VkSwapchainKHR", int(out_swapchain.value))

    def _vk_get_swapchain_images(self, logical_device, swapchain):
        vk = self._require_vk()
        if hasattr(vk, "vkGetSwapchainImagesKHR"):
            return vk.vkGetSwapchainImagesKHR(logical_device, swapchain)
        count = ctypes.c_uint32(0)
        fn = self._get_vk_proc(
            "vkGetSwapchainImagesKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p],
        )
        result = int(
            fn(
                self._handle_as_void_p(logical_device),
                self._handle_as_void_p(swapchain),
                ctypes.byref(count),
                None,
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetSwapchainImagesKHR(count) returned VkResult={result}")
        images_raw = (ctypes.c_uint64 * int(count.value))()
        result = int(
            fn(
                self._handle_as_void_p(logical_device),
                self._handle_as_void_p(swapchain),
                ctypes.byref(count),
                ctypes.cast(images_raw, ctypes.c_void_p),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkGetSwapchainImagesKHR(data) returned VkResult={result}")
        return [vk.ffi.cast("VkImage", int(images_raw[i])) for i in range(int(count.value))]

    def _vk_acquire_next_image(self, logical_device, swapchain, timeout: int, semaphore, fence):
        vk = self._require_vk()
        if hasattr(vk, "vkAcquireNextImageKHR"):
            try:
                acquired = vk.vkAcquireNextImageKHR(logical_device, swapchain, timeout, semaphore, fence)
            except Exception as exc:  # noqa: BLE001
                if exc.__class__.__name__ == "VkTimeout":
                    return None
                raise
            if isinstance(acquired, tuple) and len(acquired) >= 2:
                result_code = int(acquired[0])
                out_of_date = int(getattr(vk, "VK_ERROR_OUT_OF_DATE_KHR", -1000001004))
                if result_code == out_of_date:
                    raise SwapchainOutOfDateError("vkAcquireNextImageKHR returned VK_ERROR_OUT_OF_DATE_KHR")
            return acquired
        out_index = ctypes.c_uint32(0)
        fn = self._get_vk_proc(
            "vkAcquireNextImageKHR",
            ctypes.c_int32,
            [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ],
        )
        result = int(
            fn(
                self._handle_as_void_p(logical_device),
                self._handle_as_void_p(swapchain),
                ctypes.c_uint64(timeout),
                self._handle_as_void_p(semaphore),
                self._handle_as_void_p(fence),
                ctypes.byref(out_index),
            )
        )
        timeout_result = int(getattr(vk, "VK_TIMEOUT", 2))
        suboptimal = int(getattr(vk, "VK_SUBOPTIMAL_KHR", 1000001003))
        out_of_date = int(getattr(vk, "VK_ERROR_OUT_OF_DATE_KHR", -1000001004))
        if result == timeout_result:
            return None
        if result == out_of_date:
            raise SwapchainOutOfDateError("vkAcquireNextImageKHR returned VK_ERROR_OUT_OF_DATE_KHR")
        if result == suboptimal:
            return (result, int(out_index.value))
        if result != 0:
            raise RuntimeError(f"vkAcquireNextImageKHR returned VkResult={result}")
        return int(out_index.value)

    def _vk_wait_for_fence(self, logical_device, fence, timeout_ns: int) -> bool:
        vk = self._require_vk()
        if hasattr(vk, "vkWaitForFences"):
            try:
                result = vk.vkWaitForFences(logical_device, 1, [fence], vk.VK_TRUE, timeout_ns)
            except Exception as exc:  # noqa: BLE001
                if exc.__class__.__name__ == "VkTimeout":
                    return False
                raise
            if isinstance(result, int):
                timeout_result = int(getattr(vk, "VK_TIMEOUT", 2))
                if result == timeout_result:
                    return False
            return True
        fn = self._get_vk_proc(
            "vkWaitForFences",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint64],
        )
        fences = (ctypes.c_uint64 * 1)(self._handle_as_uint64(fence))
        result = int(
            fn(
                self._handle_as_void_p(logical_device),
                ctypes.c_uint32(1),
                ctypes.cast(fences, ctypes.c_void_p),
                ctypes.c_uint32(1),
                ctypes.c_uint64(timeout_ns),
            )
        )
        timeout_result = int(getattr(vk, "VK_TIMEOUT", 2))
        if result == timeout_result:
            return False
        if result != 0:
            raise RuntimeError(f"vkWaitForFences returned VkResult={result}")
        return True

    def _vk_reset_fence(self, logical_device, fence) -> None:
        vk = self._require_vk()
        if hasattr(vk, "vkResetFences"):
            vk.vkResetFences(logical_device, 1, [fence])
            return
        fn = self._get_vk_proc(
            "vkResetFences",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p],
        )
        fences = (ctypes.c_uint64 * 1)(self._handle_as_uint64(fence))
        result = int(
            fn(
                self._handle_as_void_p(logical_device),
                ctypes.c_uint32(1),
                ctypes.cast(fences, ctypes.c_void_p),
            )
        )
        if result != 0:
            raise RuntimeError(f"vkResetFences returned VkResult={result}")

    def _vk_queue_present(self, queue, present_info) -> None:
        vk = self._require_vk()
        if hasattr(vk, "vkQueuePresentKHR"):
            result = vk.vkQueuePresentKHR(queue, present_info)
            if isinstance(result, int):
                suboptimal = int(getattr(vk, "VK_SUBOPTIMAL_KHR", 1000001003))
                out_of_date = int(getattr(vk, "VK_ERROR_OUT_OF_DATE_KHR", -1000001004))
                if result in (suboptimal, out_of_date):
                    raise SwapchainOutOfDateError(f"vkQueuePresentKHR returned VkResult={result}")
            return
        fn = self._get_vk_proc(
            "vkQueuePresentKHR",
            ctypes.c_int32,
            [ctypes.c_void_p, ctypes.c_void_p],
        )
        result = int(fn(self._handle_as_void_p(queue), self._struct_addr(present_info)))
        suboptimal = int(getattr(vk, "VK_SUBOPTIMAL_KHR", 1000001003))
        out_of_date = int(getattr(vk, "VK_ERROR_OUT_OF_DATE_KHR", -1000001004))
        if result in (suboptimal, out_of_date):
            raise SwapchainOutOfDateError(f"vkQueuePresentKHR returned VkResult={result}")
        if result != 0:
            raise RuntimeError(f"vkQueuePresentKHR returned VkResult={result}")

    def _vk_destroy_surface(self, instance, surface) -> None:
        vk = self._require_vk()
        if hasattr(vk, "vkDestroySurfaceKHR"):
            vk.vkDestroySurfaceKHR(instance, surface, None)
            return
        fn = self._get_vk_proc(
            "vkDestroySurfaceKHR",
            None,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
        )
        fn(self._handle_as_void_p(instance), self._handle_as_void_p(surface), None)

    def _vk_destroy_swapchain(self, logical_device, swapchain) -> None:
        vk = self._require_vk()
        if hasattr(vk, "vkDestroySwapchainKHR"):
            vk.vkDestroySwapchainKHR(logical_device, swapchain, None)
            return
        fn = self._get_vk_proc(
            "vkDestroySwapchainKHR",
            None,
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
        )
        fn(self._handle_as_void_p(logical_device), self._handle_as_void_p(swapchain), None)

    def _handle_as_void_p(self, handle) -> ctypes.c_void_p:
        if handle is None:
            return ctypes.c_void_p(0)
        if isinstance(handle, int):
            return ctypes.c_void_p(handle)
        vk = self._require_vk()
        return ctypes.c_void_p(int(vk.ffi.cast("uintptr_t", handle)))

    def _handle_as_uint64(self, handle) -> int:
        if handle is None:
            return 0
        if isinstance(handle, int):
            return int(handle)
        vk = self._require_vk()
        return int(vk.ffi.cast("uintptr_t", handle))

    def _struct_addr(self, struct_obj) -> ctypes.c_void_p:
        vk = self._require_vk()
        try:
            return ctypes.c_void_p(int(vk.ffi.cast("uintptr_t", vk.ffi.addressof(struct_obj))))
        except Exception:
            return ctypes.c_void_p(int(vk.ffi.cast("uintptr_t", struct_obj)))

    def _instance_as_void_p(self) -> ctypes.c_void_p:
        vk = self._require_vk()
        instance_addr = int(vk.ffi.cast("uintptr_t", self._instance))
        return ctypes.c_void_p(instance_addr)

    def _load_vulkan_loader_lib(self):
        sdk = os.environ.get("VULKAN_SDK")
        if sdk:
            candidate = Path(sdk) / "lib" / "libvulkan.1.dylib"
            if candidate.exists():
                return ctypes.CDLL(str(candidate))
        return ctypes.CDLL("libvulkan.1.dylib")
