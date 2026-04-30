__all__ = [
    "DisplayFrame",
    "RenderTarget",
    "VulkanTarget",
    "WebTarget",
    "CpuSceneTarget",
    "SceneRenderTarget",
    "SceneTargetAdapter",
]

_MODULE_MAP = {
    "DisplayFrame": ".base",
    "RenderTarget": ".base",
    "VulkanTarget": ".vulkan_target",
    "WebTarget": ".web_target",
    "CpuSceneTarget": ".cpu_scene_target",
    "SceneRenderTarget": ".scene_target",
    "SceneTargetAdapter": ".scene_target",
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
