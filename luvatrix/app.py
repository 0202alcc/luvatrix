from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import importlib.util
import platform
from pathlib import Path

from luvatrix_core.core.app_runtime import (
    APP_PROTOCOL_VERSION,
    AppContext,
    AppLifecycle,
    AppManifest,
    AppRuntime,
    AppUIRenderer,
    AppVariant,
    ResolvedAppVariant,
)
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix

PLATFORM_MACOS = "macos"
PLATFORM_IOS = "ios"
PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
PLATFORM_WEB = "web"

SUPPORTED_APP_PLATFORMS = (
    PLATFORM_MACOS,
    PLATFORM_IOS,
    PLATFORM_LINUX,
    PLATFORM_WINDOWS,
    PLATFORM_WEB,
)

RENDER_PLATFORM: dict[str, str | None] = {
    "headless": None,
    "macos": PLATFORM_MACOS,
    "macos-metal": PLATFORM_MACOS,
    "ios-simulator": PLATFORM_IOS,
    "ios-device": PLATFORM_IOS,
    "web": PLATFORM_WEB,
}

RENDER_EXTRA_MODULES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "headless": (),
    "macos": (
        ("macos", ("AppKit", "Quartz", "Metal", "objc")),
        ("vulkan", ("vulkan",)),
    ),
    "macos-metal": (
        ("macos", ("AppKit", "Quartz", "Metal", "objc")),
    ),
    "ios-simulator": (
        ("ios", ()),
    ),
    "ios-device": (
        ("ios", ()),
    ),
    "web": (
        ("web", ("websockets",)),
    ),
}


@dataclass(frozen=True)
class AppInstallValidation:
    app_dir: Path
    render: str
    target_platform: str
    manifest: AppManifest
    resolved_variant: ResolvedAppVariant
    required_extras: tuple[str, ...]
    missing_modules: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_modules

    @property
    def install_hint(self) -> str:
        if self.ok or not self.required_extras:
            return ""
        extras = ",".join(self.required_extras)
        return f'Install the missing optional runtime with: pip install "luvatrix[{extras}]"'


class MissingOptionalDependencyError(RuntimeError):
    def __init__(self, validation: AppInstallValidation) -> None:
        missing = ", ".join(validation.missing_modules)
        hint = validation.install_hint
        message = f"render={validation.render!r} requires missing modules: {missing}"
        if hint:
            message = f"{message}. {hint}"
        super().__init__(message)
        self.validation = validation


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def load_app_manifest(app_dir: str | Path, *, host_os: str | None = None, host_arch: str | None = None) -> AppManifest:
    return _manifest_runtime(host_os=host_os, host_arch=host_arch).load_manifest(app_dir)


def check_app_install(
    app_dir: str | Path,
    *,
    render: str = "headless",
    host_os: str | None = None,
    host_arch: str | None = None,
    module_available: Callable[[str], bool] | None = None,
) -> AppInstallValidation:
    if render not in RENDER_PLATFORM:
        raise ValueError(f"unsupported render target: {render}")

    target_platform = RENDER_PLATFORM[render] or _normalize_host_os(host_os or platform.system())
    runtime = _manifest_runtime(host_os=target_platform, host_arch=host_arch)
    app_path = Path(app_dir)
    manifest = runtime.load_manifest(app_path)
    resolved = runtime.resolve_variant(app_path.resolve(), manifest)

    module_available = module_available or _module_available
    missing_modules: list[str] = []
    required_extras: list[str] = []
    for extra, modules in RENDER_EXTRA_MODULES[render]:
        required_extras.append(extra)
        for module_name in modules:
            if not module_available(module_name):
                missing_modules.append(module_name)

    return AppInstallValidation(
        app_dir=app_path,
        render=render,
        target_platform=target_platform,
        manifest=manifest,
        resolved_variant=resolved,
        required_extras=tuple(dict.fromkeys(required_extras)),
        missing_modules=tuple(dict.fromkeys(missing_modules)),
    )


def validate_app_install(
    app_dir: str | Path,
    *,
    render: str = "headless",
    host_os: str | None = None,
    host_arch: str | None = None,
    module_available: Callable[[str], bool] | None = None,
) -> AppInstallValidation:
    validation = check_app_install(
        app_dir,
        render=render,
        host_os=host_os,
        host_arch=host_arch,
        module_available=module_available,
    )
    if not validation.ok:
        raise MissingOptionalDependencyError(validation)
    return validation


def _manifest_runtime(*, host_os: str | None = None, host_arch: str | None = None) -> AppRuntime:
    return AppRuntime(
        matrix=WindowMatrix(1, 1),
        hdi=HDIThread(source=_NoopHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        host_os=host_os,
        host_arch=host_arch,
    )


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _normalize_host_os(value: str) -> str:
    normalized = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "darwin": PLATFORM_MACOS,
        "macos": PLATFORM_MACOS,
        "osx": PLATFORM_MACOS,
        "mac": PLATFORM_MACOS,
        "linux": PLATFORM_LINUX,
        "windows": PLATFORM_WINDOWS,
        "win": PLATFORM_WINDOWS,
        "ios": PLATFORM_IOS,
        "web": PLATFORM_WEB,
        "wasm": PLATFORM_WEB,
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported os identifier: {value}")
    return aliases[normalized]


__all__ = [
    "APP_PROTOCOL_VERSION",
    "PLATFORM_IOS",
    "PLATFORM_LINUX",
    "PLATFORM_MACOS",
    "PLATFORM_WEB",
    "PLATFORM_WINDOWS",
    "RENDER_EXTRA_MODULES",
    "RENDER_PLATFORM",
    "SUPPORTED_APP_PLATFORMS",
    "AppContext",
    "AppInstallValidation",
    "AppLifecycle",
    "AppManifest",
    "AppRuntime",
    "AppUIRenderer",
    "AppVariant",
    "MissingOptionalDependencyError",
    "ResolvedAppVariant",
    "check_app_install",
    "load_app_manifest",
    "validate_app_install",
]
