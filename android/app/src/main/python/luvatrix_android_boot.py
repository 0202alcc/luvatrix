from __future__ import annotations

import json
import base64
import importlib.util
import importlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import tomllib
from urllib.parse import urlparse


_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LAST_MARKER = ""
_FRAME_COUNT = 0
_ANDROID_VIEW = None
_RUNTIME_LOCK = threading.Lock()
_RUNTIME_RUNNING = False
_RUNTIME_VIEW_GENERATION = 0


class _AndroidViewPresenter:
    """Rebinds a process-scoped runtime to the current Android Activity view."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._view = None
        self._last_presentation: tuple[str, tuple[object, ...]] | None = None

    def bind(self, view) -> None:
        with self._lock:
            self._view = view
            presentation = self._last_presentation
            if presentation is not None:
                self._present(view, *presentation)

    def unbind(self, view) -> None:
        with self._lock:
            if self._view is view:
                self._view = None

    def current_view(self):
        with self._lock:
            return self._view

    def presentRgba(self, rgba: bytes, revision: int, width: int, height: int) -> None:
        self._remember_and_present("presentRgba", (rgba, revision, width, height))

    def presentScene(
        self,
        scene_json: str,
        revision: int,
        logical_width: int,
        logical_height: int,
        presentation_mode: str = "",
    ) -> None:
        self._remember_and_present(
            "presentScene",
            (scene_json, revision, logical_width, logical_height, presentation_mode),
        )

    def __getattr__(self, name: str):
        view = self.current_view()
        if view is None:
            raise AttributeError(name)
        return getattr(view, name)

    def _remember_and_present(self, method_name: str, args: tuple[object, ...]) -> None:
        with self._lock:
            self._last_presentation = (method_name, args)
            view = self._view
            if view is not None:
                self._present(view, method_name, args)

    @staticmethod
    def _present(view, method_name: str, args: tuple[object, ...]) -> None:
        method = getattr(view, method_name, None)
        if callable(method):
            method(*args)


_ANDROID_PRESENTER = _AndroidViewPresenter()


def _log(message: str) -> None:
    print(message, flush=True)


def import_probe() -> str:
    import luvatrix_core  # noqa: F401
    _import_configured_app_main()

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
    global _ANDROID_VIEW, _RUNTIME_RUNNING, _RUNTIME_VIEW_GENERATION
    with _RUNTIME_LOCK:
        if view is not None:
            _ANDROID_VIEW = view
            _ANDROID_PRESENTER.bind(view)
            _RUNTIME_VIEW_GENERATION += 1
        owner_generation = _RUNTIME_VIEW_GENERATION
        if _RUNTIME_RUNNING:
            return _mark("luvatrix visual reattached")
        _RUNTIME_RUNNING = True
    try:
        while True:
            configure_android_tls()
            import_probe()
            result = _run_visual_runtime(_ANDROID_PRESENTER if view is not None else None)
            _log(f"luvatrix visual ticks={result.ticks_run} frames={result.frames_presented}")
            with _RUNTIME_LOCK:
                if owner_generation == _RUNTIME_VIEW_GENERATION:
                    return _mark("luvatrix visual ok")
                owner_generation = _RUNTIME_VIEW_GENERATION
            _log("restarting visual runtime for replacement Android view")
    except Exception as exc:
        _log(f"luvatrix run_app_vulkan failed: {type(exc).__name__}: {exc}")
        raise
    finally:
        with _RUNTIME_LOCK:
            _RUNTIME_RUNNING = False


def detach_android_view(view) -> None:
    global _ANDROID_VIEW
    _ANDROID_PRESENTER.unbind(view)
    if _ANDROID_VIEW is view:
        _ANDROID_VIEW = None


def configure_android_tls() -> str:
    import certifi

    ca_bundle = certifi.where()
    os.environ["SSL_CERT_FILE"] = ca_bundle
    return ca_bundle


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


def read_secure_secret(key: str):
    view = _ANDROID_VIEW
    method = getattr(view, "readSecureSecret", None) if view is not None else None
    if not callable(method):
        return None
    value = method(str(key))
    return str(value) if value is not None else None


def write_secure_secret(key: str, value: str) -> None:
    view = _ANDROID_VIEW
    method = getattr(view, "writeSecureSecret", None) if view is not None else None
    if not callable(method):
        raise RuntimeError("Android secure storage is unavailable")
    method(str(key), str(value))


def delete_secure_secret(key: str) -> None:
    view = _ANDROID_VIEW
    method = getattr(view, "deleteSecureSecret", None) if view is not None else None
    if not callable(method):
        raise RuntimeError("Android secure storage is unavailable")
    method(str(key))


def download_image_rgba(url: str, size: int):
    url = str(url)
    size = int(size)
    if urlparse(url).scheme.lower() != "https":
        raise ValueError("Android image downloads require an HTTPS URL")
    if not 1 <= size <= 512:
        raise ValueError("image size must be between 1 and 512")
    view = _ANDROID_VIEW
    method = getattr(view, "downloadImageRgba", None) if view is not None else None
    if not callable(method):
        return None
    encoded = method(url, size)
    if encoded is None:
        return None
    rgba = base64.b64decode(str(encoded), validate=True)
    if len(rgba) != size * size * 4:
        raise RuntimeError("Android image bridge returned an invalid RGBA payload")
    return rgba


def android_telemetry() -> dict[str, object]:
    from luvatrix_core.platform.android.hdi_source import android_input_telemetry

    camera = {}
    try:
        bridge = _ANDROID_VIEW
        if bridge is not None and hasattr(bridge, "cameraTelemetryJson"):
            camera = json.loads(str(bridge.cameraTelemetryJson()))
    except Exception:
        camera = {}

    return {
        "marker": _LAST_MARKER,
        "frames": _FRAME_COUNT,
        "input": android_input_telemetry(),
        "sensors": ["thermal.temperature", "power.voltage_current", "motion.accelerometer", "camera.device"],
        "camera": camera,
    }


def camera_inventory_json() -> str:
    view = _ANDROID_VIEW
    if view is None:
        return "{}"
    method = getattr(view, "cameraInventoryJson", None) or getattr(view, "camera_inventory_json", None)
    if not callable(method):
        return "{}"
    return str(method())


def set_primary_camera(camera_id: str) -> str:
    view = _ANDROID_VIEW
    if view is None:
        return "unavailable"
    method = getattr(view, "setPrimaryCamera", None) or getattr(view, "set_primary_camera", None)
    if not callable(method):
        return "unavailable"
    method(str(camera_id))
    return "ok"


def set_dual_preview_enabled(enabled: bool) -> str:
    view = _ANDROID_VIEW
    if view is None:
        return "unavailable"
    method = getattr(view, "setDualPreviewEnabled", None) or getattr(view, "set_dual_preview_enabled", None)
    if not callable(method):
        return "unavailable"
    method(bool(enabled))
    return "ok"


def capture_raw_still() -> str:
    view = _ANDROID_VIEW
    if view is None:
        return "unavailable"
    method = getattr(view, "captureRawStill", None) or getattr(view, "capture_raw_still", None)
    if not callable(method):
        return "unavailable"
    return str(method())


def capture_yuv_burst(frame_count: int = 10) -> str:
    return _call_view_raw_control("captureYuvBurst", "capture_yuv_burst", int(frame_count))


def capture_raw_burst(frame_count: int = 10) -> str:
    return _call_view_raw_control("captureRawBurst", "capture_raw_burst", int(frame_count))


def capture_raw_comparison_burst(frame_count: int = 10) -> str:
    return _call_view_raw_control("captureRawComparisonBurst", "capture_raw_comparison_burst", int(frame_count))


def register_processed_output(output_path: str, preview_path: str = "") -> str:
    return _call_view_raw_control("registerProcessedOutput", "register_processed_output", str(output_path), str(preview_path))


def process_last_yuv_burst() -> str:
    return _call_view_raw_control("processLastYuvBurst", "process_last_yuv_burst")


def process_last_raw_burst() -> str:
    return _call_view_raw_control("processLastRawBurst", "process_last_raw_burst")


def process_last_raw_comparison() -> str:
    return _call_view_raw_control("processLastRawComparison", "process_last_raw_comparison")


def set_raw_capture_mode(mode: str) -> str:
    return _call_view_raw_control("setRawCaptureMode", "set_raw_capture_mode", str(mode))


def set_raw_quality_mode(mode: str) -> str:
    return _call_view_raw_control("setRawQualityMode", "set_raw_quality_mode", str(mode))


def set_raw_demosaic_mode(mode: str) -> str:
    return _call_view_raw_control("setRawDemosaicMode", "set_raw_demosaic_mode", str(mode))


def set_raw_merge_mode(mode: str) -> str:
    return _call_view_raw_control("setRawMergeMode", "set_raw_merge_mode", str(mode))


def set_raw_render_style(style: str) -> str:
    return _call_view_raw_control("setRawRenderStyle", "set_raw_render_style", str(style))


def set_preview_manual_mode(mode: str) -> str:
    return _call_view_raw_control("setPreviewManualMode", "set_preview_manual_mode", str(mode))


def adjust_raw_iso(delta_steps: int) -> str:
    return _call_view_raw_control("adjustRawIso", "adjust_raw_iso", int(delta_steps))


def adjust_raw_shutter(delta_steps: int) -> str:
    return _call_view_raw_control("adjustRawShutter", "adjust_raw_shutter", int(delta_steps))


def adjust_raw_focus(delta_steps: int) -> str:
    return _call_view_raw_control("adjustRawFocus", "adjust_raw_focus", int(delta_steps))


def reset_raw_capture_controls() -> str:
    return _call_view_raw_control("resetRawCaptureControls", "reset_raw_capture_controls")


def set_preview_quality_mode(mode: str) -> str:
    return _call_view_raw_control("setPreviewQualityMode", "set_preview_quality_mode", str(mode))


def set_preview_target_mode(mode: str) -> str:
    return _call_view_raw_control("setPreviewTargetMode", "set_preview_target_mode", str(mode))


def set_preview_sharpness_mode(mode: str) -> str:
    return _call_view_raw_control("setPreviewSharpnessMode", "set_preview_sharpness_mode", str(mode))


def set_preview_convolution_layers(layers: int) -> str:
    return _call_view_raw_control("setPreviewConvolutionLayers", "set_preview_convolution_layers", int(layers))


def set_preview_white_balance_mode(mode: str) -> str:
    return _call_view_raw_control("setPreviewWhiteBalanceMode", "set_preview_white_balance_mode", str(mode))


def set_preview_pipeline_mode(mode: str) -> str:
    return _call_view_raw_control("setPreviewPipelineMode", "set_preview_pipeline_mode", str(mode))


def set_refresh_hint_mode(mode: str) -> str:
    return _call_view_raw_control("setRefreshHintMode", "set_refresh_hint_mode", str(mode))


def _call_view_raw_control(camel: str, snake: str, *args) -> str:
    view = _ANDROID_VIEW
    if view is None:
        return "unavailable"
    method = getattr(view, camel, None) or getattr(view, snake, None)
    if not callable(method):
        return "unavailable"
    return str(method(*args))


def full_suite_emulator_acceptance(view=None) -> str:
    run_app_vulkan(view)
    telemetry = android_telemetry()
    if int(telemetry["frames"]) < 30:
        raise RuntimeError(f"expected at least 30 frames, got {telemetry['frames']}")
    return _mark("luvatrix full_suite emulator ok")


def _run_visual_runtime(view):
    global _FRAME_COUNT, _ANDROID_VIEW

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
    render_mode = _runtime_render_mode(config)
    if view is not None and _truthy(config.get("low_latency_mode"), default=True):
        _apply_low_latency_mode(view, target_fps=target_fps, present_fps=present_fps)
    clear_android_input_events()
    if view is not None and _should_start_camera_preview(config):
        _start_camera_preview(view)

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
        sensor_manager=SensorManagerThread(providers=make_android_sensor_providers(view)),
        capability_decider=lambda cap: True,
        logical_width_px=float(width),
        logical_height_px=float(height),
        scene_target=scene_target,
        render_mode=render_mode,
    )
    app_dir = _app_dir()
    _log(f"luvatrix configured app_dir={app_dir}")
    result = runtime.run_app(
        app_dir,
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
    if _should_start_camera_preview(config) and explicit_present is None:
        refresh_hz = max(refresh_hz, 120.0)
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


def _truthy(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return default


def _apply_low_latency_mode(view, *, target_fps: int, present_fps: int) -> None:
    method = getattr(view, "applyLowLatencyMode", None) or getattr(view, "apply_low_latency_mode", None)
    if not callable(method):
        return
    try:
        method(int(target_fps), int(present_fps))
    except Exception as exc:
        _log(f"luvatrix Android low-latency mode unavailable: {type(exc).__name__}: {exc}")


def _should_start_camera_preview(config: dict[str, object]) -> bool:
    source = str(config.get("source_app_dir", "") or "")
    app_dir = str(config.get("app_dir", "") or "")
    if "camera" in source.split("/"):
        return True
    return app_dir.endswith("camera") or source.endswith("examples/camera")


def _start_camera_preview(view) -> None:
    starter = getattr(view, "startCameraPreview", None) or getattr(view, "start_camera_preview", None)
    if not callable(starter):
        return
    try:
        starter()
    except Exception as exc:
        _log(f"luvatrix Android camera preview unavailable: {type(exc).__name__}: {exc}")


def _launch_config() -> dict[str, object]:
    config_path = _ROOT / "luvatrix_launch_config.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def _runtime_render_mode(config: dict[str, object]) -> str:
    render_mode = str(config.get("render_mode") or "auto")
    if render_mode != "auto":
        return render_mode
    return _app_manifest_render_mode() or render_mode


def _app_manifest_render_mode() -> str | None:
    try:
        raw = tomllib.loads((_app_dir() / "app.toml").read_text(encoding="utf-8"))
    except Exception:
        return None
    render = raw.get("render")
    if not isinstance(render, dict):
        return None
    preferred = str(render.get("preferred") or "").strip()
    if preferred in ("auto", "matrix", "scene"):
        return preferred
    return None


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
    config = _launch_config()
    configured_name = str(config.get("app_dir", "luvatrix_app"))
    configured = (_ROOT / configured_name).resolve()
    if (configured / "app.toml").exists() and any(
        (configured / name).exists() for name in ("app_main.py", "app_main.pyc")
    ):
        return configured

    materialized_configured = _materialize_configured_app(configured_name)
    if materialized_configured is not None:
        return materialized_configured

    source = str(config.get("source_app_dir", "") or "")
    if source:
        packaged = (_ROOT / "examples" / Path(source).name).resolve()
        if (packaged / "app.toml").exists() and (packaged / "app_main.py").exists():
            return packaged
        materialized = _materialize_packaged_app(source)
        if materialized is not None:
            return materialized
        raise RuntimeError(f"configured Android app is missing: app_dir={configured} source={source}")

    materialized = _materialize_packaged_app(source)
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

    return configured


def _import_configured_app_main() -> None:
    app_dir = _app_dir()
    app_main = app_dir / "app_main.py"
    if not app_main.exists():
        app_main = app_dir / "app_main.pyc"
    module_name = "luvatrix_configured_app_main"
    spec = importlib.util.spec_from_file_location(module_name, app_main)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load configured app module from {app_main}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def _materialize_configured_app(package_name: str) -> Path | None:
    try:
        from importlib import resources

        package = importlib.import_module(package_name)
        package_root = resources.files(package)
        app_toml = package_root.joinpath("app.toml").read_text(encoding="utf-8")
        app_main = package_root.joinpath("app_main.pyc").read_bytes()
    except Exception:
        return None

    return _write_materialized_bytecode_app(package_name, app_toml, app_main)


def _materialize_packaged_app(source_app_dir: str = "") -> Path | None:
    package_name = _configured_example_package(source_app_dir)
    try:
        bundle = importlib.import_module(f"{package_name}._luvatrix_bundle")

        app_toml = str(bundle.APP_TOML)
        app_main = str(bundle.APP_MAIN)
        return _write_materialized_app(package_name, app_toml, app_main)
    except Exception:
        pass

    try:
        from importlib import resources

        package_root = resources.files(package_name)
        app_toml = package_root.joinpath("app.toml").read_text(encoding="utf-8")
        app_main = package_root.joinpath("app_main.py").read_text(encoding="utf-8")
    except Exception:
        return None

    return _write_materialized_app(package_name, app_toml, app_main)


def _configured_example_package(source_app_dir: str) -> str:
    name = Path(source_app_dir).name if source_app_dir else "full_suite_interactive"
    if not name or name in (".", ".."):
        name = "full_suite_interactive"
    return f"examples.{name}"


def _write_materialized_app(package_name: str, app_toml: str, app_main: str) -> Path:
    dest = Path(tempfile.gettempdir()) / f"luvatrix_{package_name.replace('.', '_')}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "app.toml").write_text(app_toml, encoding="utf-8")
    (dest / "app_main.py").write_text(app_main, encoding="utf-8")
    (dest / "app_main.pyc").unlink(missing_ok=True)
    return dest


def _write_materialized_bytecode_app(package_name: str, app_toml: str, app_main: bytes) -> Path:
    dest = Path(tempfile.gettempdir()) / f"luvatrix_{package_name.replace('.', '_')}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "app.toml").write_text(app_toml, encoding="utf-8")
    (dest / "app_main.pyc").write_bytes(app_main)
    (dest / "app_main.py").unlink(missing_ok=True)
    return dest


def _mark(marker: str) -> str:
    global _LAST_MARKER
    _LAST_MARKER = marker
    _log(marker)
    return marker
