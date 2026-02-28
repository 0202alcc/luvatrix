from __future__ import annotations

import ctypes
import importlib.util
import os
import platform


def detect_vulkan_preflight_issue() -> str | None:
    system = platform.system()
    if system != "Darwin":
        return None

    if importlib.util.find_spec("vulkan") is None:
        return (
            "Python Vulkan bindings are missing. Install with:\n"
            "  pip install \"luvatrix[vulkan]\"\n"
            "or:\n"
            "  pip install vulkan"
        )

    sdk = os.getenv("VULKAN_SDK", "").strip()
    candidates: list[str] = []
    if sdk:
        candidates.append(os.path.join(sdk, "lib", "libvulkan.1.dylib"))
    candidates.append("libvulkan.1.dylib")

    for candidate in candidates:
        try:
            ctypes.CDLL(candidate)
            return None
        except OSError:
            continue

    return (
        "Vulkan loader (libvulkan.1.dylib) was not found.\n"
        "Install Vulkan SDK / MoltenVK, then restart your shell.\n"
        "Typical macOS options:\n"
        "  1) Install LunarG Vulkan SDK\n"
        "  2) Or install MoltenVK + Vulkan loader via Homebrew\n"
        "Then ensure VULKAN_SDK is exported if your setup requires it."
    )
