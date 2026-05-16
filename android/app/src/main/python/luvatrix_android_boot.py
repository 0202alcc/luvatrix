from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time


_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LAST_MARKER = ""
_FRAME_COUNT = 0


def _log(message: str) -> None:
    print(message, flush=True)


def import_probe() -> str:
    import luvatrix_core  # noqa: F401
    import luvatrix_ui  # noqa: F401
    import examples.full_suite_interactive.app_main  # noqa: F401

    return _mark("luvatrix import probe ok")


def run_headless_ticks(ticks: int = 5) -> str:
    from luvatrix_core.core.hdi_thread import HDIThread
    from luvatrix_core.core.sensor_manager import SensorManagerThread
    from luvatrix_core.core.unified_runtime import UnifiedRuntime
    from luvatrix_core.core.window_matrix import WindowMatrix
    from luvatrix_core.platform.android.hdi_source import AndroidHDISource, clear_android_input_events
    from luvatrix_core.targets.base import RenderTarget

    class _Target(RenderTarget):
        def start(self) -> None:
            pass

        def present_frame(self, frame) -> None:
            global _FRAME_COUNT
            _FRAME_COUNT += 1

        def stop(self) -> None:
            pass

    runtime = UnifiedRuntime(
        matrix=WindowMatrix(height=852, width=393),
        target=_Target(),
        hdi=HDIThread(source=AndroidHDISource()),
        sensor_manager=SensorManagerThread(providers={}),
        capability_decider=lambda cap: True,
        logical_width_px=393.0,
        logical_height_px=852.0,
    )
    result = runtime.run_app(_app_dir(), max_ticks=int(ticks), target_fps=60, present_fps=60)
    _log(f"luvatrix headless ticks={result.ticks_run} frames={result.frames_presented}")
    return _mark("luvatrix headless lifecycle ok")


def run_app_vulkan(view=None) -> str:
    try:
        import_probe()
        result = _run_visual_runtime(view)
        _log(f"luvatrix visual ticks={result.ticks_run} frames={result.frames_presented}")
        return _mark("luvatrix full_suite visual ok")
    except Exception as exc:
        _log(f"luvatrix run_app_vulkan failed: {type(exc).__name__}: {exc}")
        raise


def enqueue_touch(touch_id: int, phase: str, x: float, y: float, force: float = 0.0, major_radius: float = 0.0, tool_type: str = "") -> None:
    from luvatrix_core.platform.android.hdi_source import enqueue_native_touch_event

    enqueue_native_touch_event(
        int(touch_id),
        str(phase),
        float(x),
        float(y),
        force=float(force),
        major_radius=float(major_radius),
        tool_type=str(tool_type),
    )


def enqueue_key(key: str, phase: str, scan_code: int = 0) -> None:
    from luvatrix_core.platform.android.hdi_source import enqueue_native_key_event

    enqueue_native_key_event(str(key), str(phase), scan_code=int(scan_code))


def android_telemetry() -> dict[str, object]:
    from luvatrix_core.platform.android.hdi_source import android_input_telemetry

    return {
        "marker": _LAST_MARKER,
        "frames": _FRAME_COUNT,
        "input": android_input_telemetry(),
        "sensors": ["thermal.temperature", "power.voltage_current", "motion.accelerometer"],
    }


def full_suite_emulator_acceptance(view=None) -> str:
    run_app_vulkan(view)
    telemetry = android_telemetry()
    if int(telemetry["frames"]) < 30:
        raise RuntimeError(f"expected at least 30 frames, got {telemetry['frames']}")
    return _mark("luvatrix full_suite emulator ok")


def _run_visual_runtime(view):
    global _FRAME_COUNT

    from luvatrix_core.core.hdi_thread import HDIThread
    from luvatrix_core.core.sensor_manager import SensorManagerThread
    from luvatrix_core.core.unified_runtime import UnifiedRuntime
    from luvatrix_core.core.window_matrix import WindowMatrix
    from luvatrix_core.platform.android.hdi_source import AndroidHDISource, clear_android_input_events
    from luvatrix_core.platform.android.scene_target import AndroidNativeSceneTarget
    from luvatrix_core.platform.android.sensors import make_android_sensor_providers
    from luvatrix_core.platform.android.vulkan_target import AndroidVulkanBridge, AndroidVulkanTarget
    from luvatrix_core.targets.base import RenderTarget

    config = _launch_config()
    width, height = _runtime_dimensions(view, config)
    render_scale = max(0.05, float(config.get("render_scale", 1.0) or 1.0))
    matrix_width = max(1, int(round(width * render_scale)))
    matrix_height = max(1, int(round(height * render_scale)))
    target_fps, present_fps = _runtime_frame_rates(view, config)
    render_mode = str(config.get("render_mode") or "auto")
    clear_android_input_events()

    class _CountingTarget(RenderTarget):
        def __init__(self) -> None:
            self.frames_presented = 0

        def start(self) -> None:
            pass

        def present_frame(self, frame) -> None:
            global _FRAME_COUNT
            self.frames_presented += 1
            _FRAME_COUNT += 1

        def stop(self) -> None:
            pass

    target = AndroidVulkanTarget(AndroidVulkanBridge(view)) if view is not None else _CountingTarget()
    scene_target = AndroidNativeSceneTarget(view) if view is not None and render_mode in ("auto", "scene") else None
    runtime = UnifiedRuntime(
        matrix=WindowMatrix(height=matrix_height, width=matrix_width),
        target=target,
        hdi=HDIThread(
            source=AndroidHDISource(view, logical_width=float(width), logical_height=float(height)),
            poll_interval_s=1.0 / 1000.0,
            window_geometry_provider=lambda: (0.0, 0.0, float(width), float(height)),
            target_extent_provider=lambda: (float(width), float(height)),
        ),
        sensor_manager=SensorManagerThread(providers=make_android_sensor_providers()),
        capability_decider=lambda cap: True,
        logical_width_px=float(width),
        logical_height_px=float(height),
        scene_target=scene_target,
        render_mode=render_mode,
    )
    result = runtime.run_app(
        _app_dir(),
        max_ticks=None if view is not None else 60,
        target_fps=target_fps,
        present_fps=present_fps,
    )
    if view is not None:
        _FRAME_COUNT = int(getattr(scene_target, "frames_presented", 0) or getattr(target, "frames_presented", _FRAME_COUNT))
    return result


def _runtime_dimensions(view, config: dict[str, object]) -> tuple[int, int]:
    width = int(config.get("width") or config.get("native_width") or 0)
    height = int(config.get("height") or config.get("native_height") or 0)
    if view is not None:
        if width <= 0:
            try:
                width = int(view.getWidth())
            except Exception:
                width = 0
        if height <= 0:
            try:
                height = int(view.getHeight())
            except Exception:
                height = 0
    if width <= 0:
        width = int(config.get("width") or config.get("native_width") or 393)
    if height <= 0:
        height = int(config.get("height") or config.get("native_height") or 852)
    return max(1, width), max(1, height)


def _runtime_frame_rates(view, config: dict[str, object]) -> tuple[int, int]:
    refresh_hz = _display_refresh_rate_hz(view, config)
    explicit_target = _positive_int_or_none(config.get("target_fps"))
    explicit_present = _positive_int_or_none(config.get("present_fps"))
    target_fps = explicit_target or max(1, int(round(refresh_hz * 2.0)))
    present_fps = explicit_present or max(1, int(round(refresh_hz)))
    return target_fps, present_fps


def _display_refresh_rate_hz(view, config: dict[str, object]) -> float:
    for key in ("refresh_rate_hz", "display_refresh_hz"):
        try:
            value = float(config.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0.0:
            return value
    if view is not None:
        method = getattr(view, "displayRefreshRateHz", None) or getattr(view, "display_refresh_rate_hz", None)
        if callable(method):
            try:
                value = float(method())
            except Exception:
                value = 0.0
            if value > 0.0:
                return value
    return 60.0


def _positive_int_or_none(value: object) -> int | None:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _launch_config() -> dict[str, object]:
    config_path = _ROOT / "luvatrix_launch_config.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _paint_view(view, frames: int) -> None:
    global _FRAME_COUNT
    width = 64
    height = 64
    for idx in range(frames):
        rgba = bytearray(width * height * 4)
        for pixel in range(width * height):
            off = pixel * 4
            rgba[off] = (idx * 7 + 30) % 255
            rgba[off + 1] = 90
            rgba[off + 2] = 160
            rgba[off + 3] = 255
        view.presentRgba(bytes(rgba), idx + 1, width, height)
        _FRAME_COUNT += 1
        time.sleep(1.0 / 60.0)


def _app_dir() -> Path:
    materialized = _materialize_packaged_app()
    if materialized is not None:
        return materialized

    try:
        import examples.full_suite_interactive.app_main as full_suite_app

        module_path = Path(str(full_suite_app.__file__)).resolve()
        candidate = module_path.parent
        if (candidate / "app.toml").exists() and (candidate / "app_main.py").exists():
            return candidate
    except Exception:
        pass

    candidate = (_ROOT / "luvatrix_app").resolve()
    if (candidate / "app.toml").exists() and (candidate / "app_main.py").exists():
        return candidate

    config_path = _ROOT / "luvatrix_launch_config.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return (_ROOT / str(raw.get("app_dir", "luvatrix_app"))).resolve()


def _materialize_packaged_app() -> Path | None:
    try:
        from examples.full_suite_interactive import _luvatrix_bundle

        app_toml = str(_luvatrix_bundle.APP_TOML)
        app_main = str(_luvatrix_bundle.APP_MAIN)
        return _write_materialized_app(app_toml, app_main)
    except Exception:
        pass

    try:
        from importlib import resources

        package_root = resources.files("examples.full_suite_interactive")
        app_toml = package_root.joinpath("app.toml").read_text(encoding="utf-8")
        app_main = package_root.joinpath("app_main.py").read_text(encoding="utf-8")
    except Exception:
        return None

    return _write_materialized_app(app_toml, app_main)


def _write_materialized_app(app_toml: str, app_main: str) -> Path:
    dest = Path(tempfile.gettempdir()) / "luvatrix_full_suite_interactive"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "app.toml").write_text(app_toml, encoding="utf-8")
    (dest / "app_main.py").write_text(app_main, encoding="utf-8")
    return dest


def _mark(marker: str) -> str:
    global _LAST_MARKER
    _LAST_MARKER = marker
    _log(marker)
    return marker
