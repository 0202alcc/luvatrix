from __future__ import annotations

import os


def _decode_name(name) -> str:
    if isinstance(name, bytes):
        return name.decode("utf-8", errors="ignore")
    return str(name)


def main() -> int:
    print("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN=", os.getenv("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", "<unset>"))
    print("VULKAN_SDK=", os.getenv("VULKAN_SDK", "<unset>"))
    print("VK_ICD_FILENAMES=", os.getenv("VK_ICD_FILENAMES", "<unset>"))
    try:
        import vulkan as vk  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"vulkan import failed: {exc}")
        return 1

    exts = {
        _decode_name(e.extensionName)
        for e in vk.vkEnumerateInstanceExtensionProperties(None)
    }
    print("VK_EXT_metal_surface available:", "VK_EXT_metal_surface" in exts)
    print("VK_MVK_macos_surface available:", "VK_MVK_macos_surface" in exts)
    for symbol in [
        "vkGetPhysicalDeviceSurfaceSupportKHR",
        "vkGetPhysicalDeviceSurfaceCapabilitiesKHR",
        "vkCreateSwapchainKHR",
        "vkAcquireNextImageKHR",
        "vkQueuePresentKHR",
        "vkCreateMetalSurfaceEXT",
        "vkCreateMacOSSurfaceMVK",
    ]:
        print(f"{symbol}:", hasattr(vk, symbol))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
