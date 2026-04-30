__all__ = [
    "MacOSVulkanBackend",
    "MacOSVulkanPresenter",
    "AppKitWindowSystem",
    "MacOSWindowHandle",
    "MacOSWindowSystem",
    "MoltenVKMacOSBackend",
    "MacOSThermalTemperatureProvider",
    "MacOSPowerVoltageCurrentProvider",
    "MacOSMotionProvider",
    "MacOSCameraDeviceProvider",
    "MacOSMicrophoneDeviceProvider",
    "MacOSSpeakerDeviceProvider",
    "make_default_macos_sensor_providers",
    "MacOSWindowHDISource",
    "PresenterState",
    "StubMacOSVulkanBackend",
    "VulkanContext",
]

_MODULE_MAP: dict[str, str] = {
    "MoltenVKMacOSBackend": ".vulkan_backend",
    "MacOSCameraDeviceProvider": ".sensors",
    "MacOSMicrophoneDeviceProvider": ".sensors",
    "MacOSMotionProvider": ".sensors",
    "MacOSPowerVoltageCurrentProvider": ".sensors",
    "MacOSSpeakerDeviceProvider": ".sensors",
    "MacOSThermalTemperatureProvider": ".sensors",
    "make_default_macos_sensor_providers": ".sensors",
    "MacOSWindowHDISource": ".hdi_source",
    "MacOSVulkanBackend": ".vulkan_presenter",
    "MacOSVulkanPresenter": ".vulkan_presenter",
    "PresenterState": ".vulkan_presenter",
    "StubMacOSVulkanBackend": ".vulkan_presenter",
    "VulkanContext": ".vulkan_presenter",
    "AppKitWindowSystem": ".window_system",
    "MacOSWindowHandle": ".window_system",
    "MacOSWindowSystem": ".window_system",
}


def __getattr__(name: str):  # noqa: N807
    module_path = _MODULE_MAP.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    mod = importlib.import_module(module_path, __name__)
    obj = getattr(mod, name)
    globals()[name] = obj
    return obj
