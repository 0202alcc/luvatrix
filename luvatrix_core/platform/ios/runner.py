from __future__ import annotations

import logging
import json
import os as _os
import platform as _platform
import sys as _sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_metal_layer: object = None
_window: object = None
_vc: object = None
_layer_width: int = 0
_layer_height: int = 0
_logical_width: int = 0
_logical_height: int = 0
_layer_scale: float = 1.0
_PROBE_LINES: list[str] = []
_touch_view: object = None
_touch_view_class: object = None


def _setup_syslog_redirect() -> None:
    """Route Python stdout/stderr through POSIX syslog().

    Without an attached debugger, iOS apps have fd 1 and fd 2 connected to
    /dev/null. This replaces sys.stdout and sys.stderr with writers that call
    syslog() so output enters the OS unified log and becomes visible via
    `xcrun devicectl device syslog stream` on the Mac.
    """
    try:
        import ctypes as _ctypes
        _libc = _ctypes.CDLL("/usr/lib/libSystem.dylib")
        # syslog(int priority, const char *fmt, const char *msg)
        _libc.syslog.argtypes = [_ctypes.c_int, _ctypes.c_char_p, _ctypes.c_char_p]
        _libc.syslog.restype = None
        _LOG_NOTICE = 5

        class _SyslogWriter:
            def __init__(self) -> None:
                self._buf: str = ""

            def write(self, s: str) -> int:
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    if line:
                        try:
                            _libc.syslog(_LOG_NOTICE, b"%s", line.encode("utf-8", errors="replace"))
                        except Exception:
                            pass
                return len(s)

            def flush(self) -> None:
                if self._buf:
                    try:
                        _libc.syslog(_LOG_NOTICE, b"%s", self._buf.encode("utf-8", errors="replace"))
                    except Exception:
                        pass
                    self._buf = ""

            def fileno(self) -> int:
                return 2

        writer = _SyslogWriter()
        _sys.stdout = writer
        _sys.stderr = writer
    except Exception:
        pass


def setup_ui(width: int, height: int) -> None:
    """
    Called from Swift on the main thread before run_loop().
    Creates UIWindow → UIViewController → UIView → CAMetalLayer via rubicon-objc.
    Stores the layer in module globals for run_loop() to pick up.
    """
    global _metal_layer, _window, _vc, _layer_width, _layer_height, _logical_width, _logical_height, _layer_scale
    global _touch_view, _touch_view_class

    _setup_syslog_redirect()

    if _ios_import_probe_requested():
        _run_ios_import_probe()
        _os._exit(0)

    from rubicon.objc import ObjCClass

    UIScreen = ObjCClass("UIScreen")
    UIWindow = ObjCClass("UIWindow")
    UIViewController = ObjCClass("UIViewController")
    CAMetalLayer = ObjCClass("CAMetalLayer")

    screen = UIScreen.mainScreen
    bounds = screen.bounds
    scale = float(screen.scale)
    backing_width = max(1, int(round(float(width) * scale)))
    backing_height = max(1, int(round(float(height) * scale)))

    window = UIWindow.alloc().initWithFrame_(bounds)
    vc = UIViewController.alloc().init()
    window.rootViewController = vc
    window.makeKeyAndVisible()

    layer = CAMetalLayer.alloc().init()
    layer.frame = bounds
    layer.contentsScale = screen.scale
    vc.view.layer.addSublayer_(layer)

    # Commit Metal layer reference now so run_loop() can proceed even if HDI setup fails.
    _metal_layer = layer

    touch_view = None
    touch_view_class = None
    if _os.environ.get("LUVATRIX_IOS_ENABLE_HDI") == "1":
        try:
            UIView = ObjCClass("UIView")
            touch_view_class = _make_touch_view_class(UIView)
            touch_view = touch_view_class.alloc().initWithFrame_(bounds)
            touch_view.setMultipleTouchEnabled_(True)
            touch_view.setUserInteractionEnabled_(True)
            touch_view.setOpaque_(False)
            touch_view.setBackgroundColor_(ObjCClass("UIColor").clearColor)
            # Add to window (not vc.view) — vc.view.frame may be CGRectZero at
            # setup time since UIKit layout is deferred past makeKeyAndVisible().
            # The window always has correct bounds from initWithFrame_(bounds).
            window.addSubview_(touch_view)
        except Exception as _hdi_exc:
            print(f"[ios] HDI touch view setup failed, continuing without touch: {_hdi_exc}", file=_sys.stderr, flush=True)
            touch_view = None
            touch_view_class = None

    _window = window
    _vc = vc
    _touch_view = touch_view
    _touch_view_class = touch_view_class
    _logical_width = int(width)
    _logical_height = int(height)
    _layer_scale = scale
    _layer_width = backing_width
    _layer_height = backing_height
    LOGGER.info(
        "setup_ui done logical=%dx%d backing=%dx%d scale=%.2f",
        _logical_width,
        _logical_height,
        _layer_width,
        _layer_height,
        _layer_scale,
    )


def restore_metal_layer_after_foreground() -> dict[str, int]:
    """Refresh CAMetalLayer properties from the UIKit/main thread after foreground.

    iOS can reconnect the compositor with CAMetalLayer defaults restored. In
    particular, allowsNextDrawableTimeout can become blocking again, producing
    an ~83ms nextDrawable cadence after Home-screen resume. Swift calls this
    function from applicationDidBecomeActive, on the main thread.
    """
    if _metal_layer is None:
        return {"restored": 0, "reason": 0}
    try:
        _metal_layer.setAllowsNextDrawableTimeout_(False)
    except Exception as exc:  # noqa: BLE001
        print(f"[ios] foreground layer timeout restore failed: {exc}", file=_sys.stderr, flush=True)
        return {"restored": 0, "reason": 1}
    try:
        import ctypes as _ctypes

        class _CGSize(_ctypes.Structure):
            _fields_ = [("width", _ctypes.c_double), ("height", _ctypes.c_double)]

        set_size = _metal_layer.setDrawableSize_
        expected = set_size.method.method_argtypes[0]
        size = expected.from_buffer_copy(bytes(_CGSize(float(_layer_width), float(_layer_height))))
        _metal_layer.setDrawableSize_(size)
    except Exception as exc:  # noqa: BLE001
        print(f"[ios] foreground layer drawableSize restore failed: {exc}", file=_sys.stderr, flush=True)
        return {"restored": 0, "reason": 2}
    print("[ios] restored CAMetalLayer after foreground", file=_sys.stderr, flush=True)
    return {"restored": 1, "reason": 0}


def _apply_bundled_launch_config() -> dict[str, str]:
    try:
        bundle_dir = Path(str(_sys.executable)).parent
        path = bundle_dir / "PyPackages" / "luvatrix_ios_launch_config.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        text = str(value)
        out[key] = text
        _os.environ.setdefault(key, text)
    return out


def _make_touch_view_class(UIView):
    from rubicon.objc import objc_method
    from rubicon.objc.api import ObjCInstance

    existing = getattr(_make_touch_view_class, "_cached", None)
    if existing is not None:
        return existing

    class LuvatrixTouchView(UIView, auto_rename=True):
        @objc_method
        def touchesBegan_withEvent_(self, touches: ObjCInstance, event: ObjCInstance) -> None:
            _ = event
            print("[ios-hdi] touchesBegan fired", file=_sys.stderr, flush=True)
            _enqueue_touches(self, touches, "click", "down")
            _enqueue_touches(self, touches, "pointer_move", "move")

        @objc_method
        def touchesMoved_withEvent_(self, touches: ObjCInstance, event: ObjCInstance) -> None:
            _ = event
            print("[ios-hdi] touchesMoved fired", file=_sys.stderr, flush=True)
            _enqueue_touches(self, touches, "pointer_move", "move")

        @objc_method
        def touchesEnded_withEvent_(self, touches: ObjCInstance, event: ObjCInstance) -> None:
            _ = event
            _enqueue_touches(self, touches, "pointer_move", "move")
            _enqueue_touches(self, touches, "click", "up")

        @objc_method
        def touchesCancelled_withEvent_(self, touches: ObjCInstance, event: ObjCInstance) -> None:
            _ = event
            _enqueue_touches(self, touches, "click", "cancel")

    _make_touch_view_class._cached = LuvatrixTouchView
    return LuvatrixTouchView


def _enqueue_touches(view, touches, event_type: str, phase: str) -> None:
    try:
        from luvatrix_core.platform.ios.hdi_source import enqueue_touch_event

        touch_list = _iter_touches(touches)
        print(f"[ios-hdi] _enqueue_touches: {event_type}/{phase} touches={len(touch_list)}", file=_sys.stderr, flush=True)
        for touch in touch_list:
            point = touch.locationInView_(view)
            try:
                raw_hash = touch.hash
                touch_id = int(raw_hash() if callable(raw_hash) else raw_hash)
            except Exception:
                touch_id = 0
            x, y = float(point.x), float(point.y)
            print(f"[ios-hdi]   enqueue x={x:.1f} y={y:.1f} touch_id={touch_id}", file=_sys.stderr, flush=True)
            enqueue_touch_event(
                event_type,
                x,
                y,
                phase=phase,
                touch_id=touch_id,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[ios] touch HDI bridge error: {exc}", file=_sys.stderr, flush=True)


def _iter_touches(touches):
    try:
        return list(touches)
    except Exception:
        pass
    try:
        all_objects = touches.allObjects
        return list(all_objects)
    except Exception:
        pass
    try:
        touch = touches.anyObject()
        return [] if touch is None else [touch]
    except Exception:
        return []


def _ios_import_probe_requested() -> bool:
    if _os.environ.get("LUVATRIX_IMPORT_PROBE") == "1":
        return True
    bundle_dir = Path(str(_sys.executable)).parent
    return (bundle_dir / "LuvatrixImportProbe").exists()


def _probe_log(value: str = "") -> None:
    _PROBE_LINES.append(str(value))
    print(value, file=_sys.stderr, flush=True)


def _write_probe_report() -> None:
    home = Path(_os.path.expanduser("~"))
    candidates = [
        home / "Documents" / "luvatrix_import_probe.txt",
        Path("/tmp") / "luvatrix_import_probe.txt",
    ]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(_PROBE_LINES) + "\n", encoding="utf-8")
            print(f"[ios] wrote import probe report: {path}", file=_sys.stderr, flush=True)
            return
        except BaseException as exc:
            print(f"[ios] failed to write probe report {path}: {exc}", file=_sys.stderr, flush=True)


def _run_ios_import_probe() -> None:
    import importlib
    import importlib.machinery
    import importlib.util
    import traceback

    def inspect_module(name: str) -> None:
        _probe_log("")
        _probe_log(f"=== PROBE {name} ===")
        try:
            spec = importlib.util.find_spec(name)
            _probe_log(f"spec={spec!r}")
            if spec is not None:
                origin = getattr(spec, "origin", None)
                _probe_log(f"origin={origin!r}")
                _probe_log(f"loader={type(getattr(spec, 'loader', None)).__name__}")
                if isinstance(origin, str) and origin.endswith(".fwork"):
                    try:
                        with open(origin, "r", encoding="utf-8") as fh:
                            target = fh.read().strip()
                        bundle = Path(str(_sys.executable)).parent
                        _probe_log(f"fwork_target={target}")
                        _probe_log(f"framework_exists={(bundle / target).exists()}")
                    except BaseException:
                        traceback.print_exc(file=_sys.stderr)
        except BaseException:
            _probe_log("find_spec failed")
            traceback.print_exc(file=_sys.stderr)
        _sys.stderr.flush()

        _probe_log(f"importing {name}")
        try:
            module = importlib.import_module(name)
            _probe_log(f"imported {name} file={getattr(module, '__file__', None)!r}")
        except BaseException:
            _probe_log(f"import failed {name}")
            traceback.print_exc(file=_sys.stderr)
        _sys.stderr.flush()

    bundle = Path(str(_sys.executable)).parent
    _probe_log("=== LUVATRIX IOS IMPORT PROBE ===")
    _probe_log("source=luvatrix_core.platform.ios.runner.setup_ui")
    _probe_log(f"sys.version={_sys.version.replace(chr(10), ' ')}")
    _probe_log(f"sys.platform={_sys.platform}")
    _probe_log(f"sys.executable={_sys.executable}")
    _probe_log(f"sys.path={_sys.path!r}")
    _probe_log(f"EXTENSION_SUFFIXES={importlib.machinery.EXTENSION_SUFFIXES!r}")
    for rel in (
        "PyPackages/numpy/core/_multiarray_umath.cpython-312-iphoneos.fwork",
        "PyPackages/numpy/core/_multiarray_umath.cpython-312-ios.fwork",
        "PyPackages/numpy/_core/_multiarray_umath.cpython-312-iphoneos.fwork",
        "Frameworks/numpy.core._multiarray_umath.framework/numpy.core._multiarray_umath",
    ):
        path = bundle / rel
        _probe_log(f"path {rel} exists={path.exists()}")
        if path.suffix == ".fwork" and path.exists():
            try:
                _probe_log(f"  content={path.read_text(encoding='utf-8').strip()}")
            except BaseException:
                traceback.print_exc(file=_sys.stderr)

    for name in (
        "numpy.core._multiarray_umath",
        "numpy.core.multiarray",
        "numpy",
        "PIL._imaging",
        "PIL.Image",
    ):
        inspect_module(name)
    _probe_log("=== PROBE COMPLETE ===")
    _write_probe_report()


class _IOSMetalPresenter:
    """
    Minimal presenter wrapping IOSMetalBackend.
    Unlike MacOSMetalPresenter this has no torch dependency — safe on iOS.
    """

    def __init__(
        self,
        width: int,
        height: int,
        backend: object,
        bar_color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255),
    ) -> None:
        self._width = width
        self._height = height
        self._backend = backend
        self._bar_color_rgba = bar_color_rgba
        self._context = None
        self._ready = False

    def initialize(self) -> None:
        from luvatrix_core.targets.metal_target import MetalContext
        self._backend.bar_color_rgba = self._bar_color_rgba
        self._context = self._backend.initialize(self._width, self._height, "Luvatrix")
        self._ready = True

    def present_rgba(self, rgba: object, revision: int) -> None:
        if not self._ready:
            raise RuntimeError("presenter not initialized")
        self._backend.present(self._context, rgba, revision)

    def shutdown(self) -> None:
        if self._context is not None:
            try:
                self._backend.shutdown(self._context)
            finally:
                self._context = None
        self._ready = False

    def pump_events(self) -> None:
        if self._ready:
            self._backend.pump_events()

    def should_close(self) -> bool:
        if not self._ready:
            return False
        return self._backend.should_close()


def run_loop(app_dir: str) -> None:
    """
    Called from Swift on a background thread. Blocks until the app exits.
    setup_ui() must be called first on the main thread.
    """
    if _metal_layer is None:
        raise RuntimeError("run_loop() called before setup_ui() — call setup_ui() on the main thread first")

    from luvatrix_core.platform.ios.window_system import UIKitWindowSystem
    from luvatrix_core.platform.ios.metal_backend import IOSMetalBackend
    from luvatrix_core.targets.metal_target import MetalTarget
    # Import directly from source modules to avoid luvatrix_core.core.__init__,
    # which eagerly imports torch-dependent modules that don't exist on iOS.
    from luvatrix_core.core.hdi_thread import HDIThread
    from luvatrix_core.platform.ios.hdi_source import IOSUIKitHDISource
    from luvatrix_core.core.sensor_manager import SensorManagerThread
    from luvatrix_core.core.unified_runtime import UnifiedRuntime
    from luvatrix_core.core.window_matrix import WindowMatrix
    from luvatrix_core.core.app_runtime import read_app_display_config
    from luvatrix_core import accel
    from luvatrix_core.platform.ios.lifecycle import is_app_active, set_app_active
    from luvatrix_core.platform.ios.scene_target import IOSMetalSceneBackend, IOSMetalSceneTarget

    launch_config = _apply_bundled_launch_config()
    set_app_active(True)
    _os.environ["LUVATRIX_IOS_SYS_PLATFORM"] = str(_sys.platform)
    _os.environ["LUVATRIX_IOS_SYS_EXECUTABLE"] = str(_sys.executable)
    _os.environ["LUVATRIX_IOS_ACCEL_IMPORT_ERROR"] = str(accel.BACKEND_IMPORT_ERROR or "")
    bundle_dir = Path(str(_sys.executable)).parent
    numpy_marker = (
        bundle_dir
        / "PyPackages"
        / "numpy"
        / "core"
        / "_multiarray_umath.cpython-312-iphoneos.fwork"
    )
    numpy_framework = (
        bundle_dir
        / "Frameworks"
        / "numpy.core._multiarray_umath.framework"
        / "numpy.core._multiarray_umath"
    )
    try:
        import _imp
        ext_suffixes = ",".join(str(s) for s in _imp.extension_suffixes()[:3])
    except Exception as exc:
        ext_suffixes = f"{type(exc).__name__}:{exc}"
    try:
        framework_count = len(list((bundle_dir / "Frameworks").glob("*.framework")))
    except Exception:
        framework_count = -1
    _os.environ["LUVATRIX_IOS_NATIVE_DIAG"] = (
        f"marker:{int(numpy_marker.exists())} "
        f"framework:{int(numpy_framework.exists())} "
        f"fwcount:{framework_count} "
        f"suffix:{ext_suffixes}"
    )

    native_w, native_h, bar_color = read_app_display_config(app_dir)
    logical_w = native_w if native_w else _logical_width
    logical_h = native_h if native_h else _logical_height
    if accel.BACKEND == "pure":
        # The pure-Python backend is a diagnostic fallback; rendering a full
        # Retina backing store through Python loops can make the app look stuck
        # on its first color frame. Keep logical resolution so the failure mode
        # remains visible and interactive enough to report.
        render_scale = 1.0
    else:
        # Default to logical-resolution rendering and let Metal scale to the
        # device drawable. Full Retina backing stores can be 9x the pixels on
        # iPhone, which overwhelms CPU-side UI/background generation.
        try:
            render_scale = float(_os.environ.get("LUVATRIX_IOS_RENDER_SCALE", "1.0"))
        except ValueError:
            render_scale = 1.0
        render_scale = max(0.25, min(float(_layer_scale), render_scale))
    matrix_w = max(1, int(round(float(logical_w) * render_scale)))
    matrix_h = max(1, int(round(float(logical_h) * render_scale)))

    ws = UIKitWindowSystem(layer=_metal_layer)
    backend = IOSMetalBackend(window_system=ws)
    presenter = _IOSMetalPresenter(
        width=_layer_width,
        height=_layer_height,
        backend=backend,
        bar_color_rgba=bar_color,
    )
    target = MetalTarget(presenter=presenter)
    matrix = WindowMatrix(height=matrix_h, width=matrix_w)
    hdi = HDIThread(
        source=IOSUIKitHDISource(),
        window_active_provider=is_app_active,
        window_geometry_provider=lambda: (0.0, 0.0, float(logical_w), float(logical_h)),
    )
    sensors = SensorManagerThread(providers={})
    render_mode = _os.environ.get("LUVATRIX_RENDER_MODE", launch_config.get("LUVATRIX_RENDER_MODE", "auto")).strip().lower()
    if render_mode not in ("auto", "matrix", "scene"):
        render_mode = "auto"
    scene_target = (
        IOSMetalSceneTarget(
            width=_layer_width,
            height=_layer_height,
            backend=IOSMetalSceneBackend(window_system=ws, bar_color_rgba=bar_color),
        )
        if render_mode == "scene"
        else None
    )
    ios_fps_default = "60" if render_mode == "matrix" else "120"
    try:
        target_fps = int(_os.environ.get("LUVATRIX_IOS_TARGET_FPS", launch_config.get("LUVATRIX_IOS_TARGET_FPS", ios_fps_default)))
    except ValueError:
        target_fps = 60 if render_mode == "matrix" else 120
    try:
        present_fps = int(_os.environ.get("LUVATRIX_IOS_PRESENT_FPS", launch_config.get("LUVATRIX_IOS_PRESENT_FPS", str(target_fps))))
    except ValueError:
        present_fps = target_fps

    # iOS platform.machine() returns device model IDs like "iPhone15,4", not "arm64".
    # Patch before AppRuntime reads it so _normalize_arch_name doesn't raise.
    _platform.machine = lambda: "arm64"

    runtime = UnifiedRuntime(
        matrix=matrix,
        target=target,
        hdi=hdi,
        sensor_manager=sensors,
        capability_decider=lambda cap: True,
        logical_width_px=float(logical_w),
        logical_height_px=float(logical_h),
        scene_target=scene_target,
        render_mode=render_mode,
        active_provider=is_app_active,
    )

    print(f"[ios] luvatrix accel backend: {accel.BACKEND}", file=_sys.stderr, flush=True)
    if launch_config:
        print(f"[ios] bundled launch config keys: {','.join(sorted(launch_config))}", file=_sys.stderr, flush=True)
    print(f"[ios] render_mode={render_mode} target_fps={target_fps} present_fps={present_fps}", file=_sys.stderr, flush=True)
    print(
        "[ios] display fps "
        f"screen_max={_os.environ.get('LUVATRIX_IOS_SCREEN_MAX_FPS', '?')} "
        f"requested={present_fps} "
        f"low_power={_os.environ.get('LUVATRIX_IOS_LOW_POWER_MODE', '?')} "
        f"telemetry={_os.environ.get('LUVATRIX_IOS_DISPLAY_LINK_TELEMETRY_PATH', '') or 'unavailable'}",
        file=_sys.stderr,
        flush=True,
    )
    print(f"[ios] sys.platform={_sys.platform} sys.executable={_sys.executable}", file=_sys.stderr, flush=True)
    print(f"[ios] native diag: {_os.environ['LUVATRIX_IOS_NATIVE_DIAG']}", file=_sys.stderr, flush=True)
    if accel.BACKEND_IMPORT_ERROR:
        print(f"[ios] accel import error: {accel.BACKEND_IMPORT_ERROR}", file=_sys.stderr, flush=True)
    print(
        f"[ios] logical={logical_w}x{logical_h} backing={matrix_w}x{matrix_h} scale={_layer_scale:.2f}",
        file=_sys.stderr,
        flush=True,
    )
    if accel.BACKEND == "pure":
        print(
            "[ios] warning: falling back to pure-Python arrays; install numpy in "
            "ios/PyPackages for the accelerated iOS path.",
            file=_sys.stderr,
            flush=True,
        )

    LOGGER.info("Starting luvatrix app loop: %s", app_dir)
    result = runtime.run_app(
        Path(app_dir),
        max_ticks=None,
        target_fps=target_fps,
        present_fps=present_fps,
    )
    LOGGER.info(
        "App loop exited: ticks=%d frames=%d",
        result.ticks_run,
        result.frames_presented,
    )
