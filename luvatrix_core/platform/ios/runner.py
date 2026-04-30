from __future__ import annotations

import logging
import json
import os
import os as _os
import platform as _platform
import re
import shutil
import subprocess
import sys as _sys
import tempfile
import threading
import time
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

    # Create a pipe for VSYNC-aligned present pacing when running in scene
    # mode.  The write end fd is published via env var for Swift's CADisplayLink
    # tick() to write one byte per refresh; the Python present thread blocks on
    # select() on the read end instead of sleeping on a software timer.
    vsync_read_fd: int | None = None
    _vsync_write_fd: int | None = None
    if render_mode in ("auto", "scene") and scene_target is not None:
        from luvatrix_core.core.scene_display_runtime import (
            create_vsync_pipe as _create_vsync_pipe,
            destroy_vsync_pipe as _destroy_vsync_pipe,
        )
        pipe_fds = _create_vsync_pipe()
        if pipe_fds is not None:
            vsync_read_fd, _vsync_write_fd = pipe_fds
            _os.environ["LUVATRIX_IOS_VSYNC_WRITE_FD"] = str(_vsync_write_fd)
            print(f"[ios] vsync pipe ready read_fd={vsync_read_fd} write_fd={_vsync_write_fd}", file=_sys.stderr, flush=True)
        else:
            print("[ios] vsync pipe unavailable; using software timer", file=_sys.stderr, flush=True)

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
        vsync_read_fd=vsync_read_fd,
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
    if vsync_read_fd is not None and _vsync_write_fd is not None:
        _destroy_vsync_pipe(vsync_read_fd, _vsync_write_fd)
        _os.environ.pop("LUVATRIX_IOS_VSYNC_WRITE_FD", None)
def _run_ios_simulator(
    app_dir: Path,
    simulator_name: str,
    render_scale: float = 1.0,
    render_mode: str = "auto",
    target_fps: int | None = None,
    present_fps: int | None = None,
) -> None:
    import shutil

    repo_root = Path(__file__).parent.resolve()
    ios_dir = repo_root / "ios"
    derived_data_dir = ios_dir / ".build"
    packages_dir = _ios_packages_dir(ios_dir, "simulator")
    _ensure_ios_numpy_available(ios_dir, "simulator")

    # Sync app dir into PyPackages under a fixed name so AppDelegate can find it.
    app_dest = packages_dir / "luvatrix_app"
    if app_dest.exists():
        shutil.rmtree(app_dest)
    shutil.copytree(app_dir, app_dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"[ios] synced {app_dir} → {app_dest}")

    # Copy app icon into the asset catalog if one exists at assets/icon.png.
    icon_src = repo_root / "assets" / "icon.png"
    icon_dst = ios_dir / "Luvatrix" / "Assets.xcassets" / "AppIcon.appiconset" / "icon.png"
    if icon_src.exists():
        shutil.copy2(icon_src, icon_dst)
        print(f"[ios] copied icon {icon_src} → {icon_dst}")
    elif not icon_dst.exists():
        print("[ios] warning: assets/icon.png not found; app will have no icon")

    # Regenerate the Xcode project so any new source files (e.g. Assets.xcassets) are included.
    subprocess.run(
        ["xcodegen", "generate", "--spec", "project.yml"],
        check=True,
        cwd=ios_dir,
    )

    # Build. The post-build script syncs luvatrix_core and copies PyPackages into the bundle.
    print(f"[ios] building for simulator: {simulator_name}")
    subprocess.run(
        [
            "xcodebuild", "build",
            "-project", str(ios_dir / "Luvatrix.xcodeproj"),
            "-scheme", "Luvatrix",
            "-destination", f"platform=iOS Simulator,name={simulator_name}",
            "-derivedDataPath", str(derived_data_dir),
            "-configuration", "Debug",
            "-quiet",
            "CODE_SIGN_IDENTITY=",
            "CODE_SIGNING_REQUIRED=NO",
            "CODE_SIGNING_ALLOWED=NO",
        ],
        check=True,
        cwd=ios_dir,
    )

    app_path = derived_data_dir / "Build" / "Products" / "Debug-iphonesimulator" / "Luvatrix.app"
    if not app_path.exists():
        raise RuntimeError(f"Built app not found at {app_path}")

    # Find the simulator UDID.
    result = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "--json"],
        capture_output=True, text=True, check=True,
    )
    udid = _find_simulator_udid(json.loads(result.stdout), simulator_name)
    if udid is None:
        raise RuntimeError(
            f"Simulator '{simulator_name}' not found or not available. "
            "Run: xcrun simctl list devices"
        )

    # Boot the simulator (no-op if already running).
    subprocess.run(["xcrun", "simctl", "boot", udid], capture_output=True)
    subprocess.run(["open", "-a", "Simulator"], check=True)
    subprocess.run(["xcrun", "simctl", "bootstatus", udid, "-b"], check=True)

    # Install and launch, streaming output to the terminal.
    subprocess.run(["xcrun", "simctl", "install", udid, str(app_path)], check=True)
    print(f"[ios] launching com.luvatrix.app on {simulator_name} ({udid})")
    try:
        launch_env = os.environ.copy()
        launch_env["SIMCTL_CHILD_LUVATRIX_IOS_RENDER_SCALE"] = f"{render_scale:.6g}"
        launch_env["SIMCTL_CHILD_LUVATRIX_RENDER_MODE"] = render_mode
        ios_fps_default = 60 if render_mode == "matrix" else 120
        launch_env["SIMCTL_CHILD_LUVATRIX_IOS_TARGET_FPS"] = str(target_fps or ios_fps_default)
        launch_env["SIMCTL_CHILD_LUVATRIX_IOS_PRESENT_FPS"] = str(present_fps or target_fps or ios_fps_default)
        if os.environ.get("LUVATRIX_IOS_ENABLE_HDI") == "1":
            launch_env["SIMCTL_CHILD_LUVATRIX_IOS_ENABLE_HDI"] = "1"
        subprocess.run(
            ["xcrun", "simctl", "launch", "--console", udid, "com.luvatrix.app"],
            check=True,
            env=launch_env,
        )
    except KeyboardInterrupt:
        subprocess.run(["xcrun", "simctl", "terminate", udid, "com.luvatrix.app"], capture_output=True)


def _build_ios_device_app(
    ios_dir: Path,
    team_id: str | None = None,
    import_probe: bool = False,
) -> Path:
    derived_data_dir = ios_dir / ".build-device"

    subprocess.run(
        ["xcodegen", "generate", "--spec", "project.yml"],
        check=True,
        cwd=ios_dir,
    )

    print("[ios] building fresh signed device app")
    command = [
        "xcodebuild", "build",
        "-project", str(ios_dir / "Luvatrix.xcodeproj"),
        "-scheme", "Luvatrix",
        "-destination", "generic/platform=iOS",
        "-derivedDataPath", str(derived_data_dir),
        "-configuration", "Debug",
        "-allowProvisioningUpdates",
        "-quiet",
        f"LUVATRIX_IMPORT_PROBE={'1' if import_probe else '0'}",
    ]
    if team_id:
        command.append(f"DEVELOPMENT_TEAM={team_id}")
    subprocess.run(command, check=True, cwd=ios_dir)

    app_path = derived_data_dir / "Build" / "Products" / "Debug-iphoneos" / "Luvatrix.app"
    if not app_path.exists():
        raise RuntimeError(f"Built app not found at {app_path}")
    return app_path


def _sync_local_packages(repo_root: Path, packages_dir: Path) -> None:
    """Sync luvatrix_core and luvatrix_ui from source into the iOS PyPackages dir."""
    import shutil
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for pkg in ("luvatrix_core", "luvatrix_ui"):
        src = repo_root / pkg
        dst = packages_dir / pkg
        if not src.is_dir():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore)
        print(f"[ios] synced {src} → {dst}")


def _ios_packages_dir(ios_dir: Path, target: str) -> Path:
    if target == "device":
        target_dir = ios_dir / "PyPackages-device"
    elif target == "simulator":
        target_dir = ios_dir / "PyPackages-simulator"
    else:
        raise ValueError(f"unknown iOS package target: {target!r}")
    if target_dir.exists():
        return target_dir
    return ios_dir / "PyPackages"


def _ensure_ios_numpy_available(ios_dir: Path, target: str) -> None:
    packages_dir = _ios_packages_dir(ios_dir, target)
    if _has_ios_numpy_package(packages_dir, target):
        return
    message = (
        f"[ios] error: numpy is missing or incompatible in {packages_dir}, so "
        "the iOS app would fall back to the slow pure-Python accel backend.\n"
        "[ios] run: bash ios/scripts/setup_ios.sh\n"
        "[ios] to intentionally allow the slow fallback, set "
        "LUVATRIX_ALLOW_PURE_PYTHON_IOS=1."
    )
    if os.getenv("LUVATRIX_ALLOW_PURE_PYTHON_IOS") == "1":
        print(message.replace("[ios] error:", "[ios] warning:"))
        return
    raise SystemExit(message)


def _ios_expected_cpython_tag(packages_dir: Path, target: str) -> str | None:
    numpy_dir = packages_dir / "numpy"
    if not numpy_dir.is_dir():
        return None
    if target == "device":
        platform_part = "iphoneos"
    elif target == "simulator":
        platform_part = "iphonesimulator"
    else:
        raise ValueError(f"unknown iOS target: {target!r}")
    import re
    for path in sorted(numpy_dir.rglob("*.so")):
        match = re.search(r"\.cpython-(\d+)-" + re.escape(platform_part) + r"\.so$", path.name)
        if match:
            return match.group(1)
    return None


def _ios_python_version_from_cpython_tag(tag: str | None) -> str | None:
    if tag is None or len(tag) < 2:
        return None
    return f"{tag[0]}.{tag[1:]}"


def _has_ios_numpy_package(packages_dir: Path, target: str | None = None) -> bool:
    numpy_dir = packages_dir / "numpy"
    if not numpy_dir.is_dir():
        return False
    extension_files = list(numpy_dir.rglob("*.so"))
    if not extension_files:
        return False
    if target == "device":
        valid_tags = ("cpython-312-iphoneos",)
    elif target == "simulator":
        valid_tags = ("cpython-312-iphonesimulator",)
    else:
        valid_tags = ("cpython-312-iphonesimulator", "cpython-312-iphoneos")
    return any(any(tag in path.name for tag in valid_tags) for path in extension_files)


def _validate_ios_bundle_native_extensions(app_path: Path, target: str) -> None:
    so_files = list((app_path / "PyPackages").rglob("*.so"))
    if target == "device":
        required = "cpython-312-iphoneos"
        forbidden = "cpython-312-iphonesimulator"
    elif target == "simulator":
        required = "cpython-312-iphonesimulator"
        forbidden = "cpython-312-iphoneos"
    else:
        raise ValueError(f"unknown iOS target: {target!r}")
    bad = [path for path in so_files if forbidden in path.name]
    if bad:
        preview = "\n".join(f"  - {path.relative_to(app_path)}" for path in bad[:8])
        raise RuntimeError(
            f"iOS {target} bundle contains incompatible native extensions:\n"
            f"{preview}\n"
            "Run: bash ios/scripts/setup_ios.sh"
        )
    if not any(required in path.name for path in so_files):
        raise RuntimeError(
            f"iOS {target} bundle does not contain any {required} native extensions. "
            "Run: bash ios/scripts/setup_ios.sh"
        )


def _validate_ios_xcode_app_python_abi(src_app: Path, packages_dir: Path, target: str) -> None:
    expected_tag = _ios_expected_cpython_tag(packages_dir, target)
    expected_version = _ios_python_version_from_cpython_tag(expected_tag)
    if expected_version is None:
        return

    app_versions = _detect_ios_app_python_versions(src_app)
    mismatched = sorted(version for version in app_versions if version != expected_version)
    if not mismatched:
        return

    versions = ", ".join(sorted(app_versions))
    raise RuntimeError(
        "[ios] Xcode build embeds Python "
        f"{versions}, but {packages_dir} contains cp{expected_tag} "
        f"(Python {expected_version}) native wheels.\n"
        f"[ios] stale build: {src_app}\n"
        "[ios] Fix: rebuild the iOS app after running setup_ios.sh so Xcode "
        "links/copies the same PythonSupport.xcframework as the packages.\n"
        "[ios] Suggested commands:\n"
        "  cd ios && xcodegen generate\n"
        "  open Luvatrix.xcodeproj\n"
        "Then clean/build the Luvatrix scheme for your physical device in Xcode."
    )


def _detect_ios_app_python_versions(app_path: Path) -> set[str]:
    versions: set[str] = set()
    import re

    lib_dir = app_path / "python" / "lib"
    if lib_dir.exists():
        for child in lib_dir.iterdir():
            match = re.fullmatch(r"python(\d+\.\d+)", child.name)
            if match:
                versions.add(match.group(1))

    for binary in (app_path / "Luvatrix.debug.dylib", app_path / "Frameworks" / "Python.framework" / "Python"):
        if not binary.exists():
            continue
        result = subprocess.run(["otool", "-L", str(binary)], capture_output=True, text=True)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            if "Python.framework/Python" not in line:
                continue
            match = re.search(r"(?:compatibility|current) version (\d+\.\d+)\.", line)
            if match:
                versions.add(match.group(1))
    return versions


def _ios_extension_module_name(relative_path: Path) -> str:
    """Match Python-Apple-support's dotted module name derivation."""
    return relative_path.as_posix().split(".", 1)[0].replace("/", ".")


def _write_framework_info_plist(framework_dir: Path, executable: str, identifier: str) -> None:
    import plistlib

    template = (
        Path(__file__).parent
        / "ios"
        / "Python"
        / "PythonSupport.xcframework"
        / "build"
        / "iOS-dylib-Info-template.plist"
    )
    if template.exists():
        with template.open("rb") as fh:
            payload = plistlib.load(fh)
    else:
        payload = {
            "CFBundleDevelopmentRegion": "en",
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleSupportedPlatforms": ["iPhoneOS"],
            "CFBundleVersion": "1",
            "MinimumOSVersion": "13.0",
        }
    payload["CFBundleExecutable"] = executable
    payload["CFBundleIdentifier"] = identifier
    with (framework_dir / "Info.plist").open("wb") as fh:
        plistlib.dump(payload, fh)


def _prepare_ios_extension_frameworks(app_path: Path) -> list[Path]:
    """Expose iOS extension modules through CPython's AppleFrameworkLoader.

    On iOS, CPython's FileFinder prefers `.fwork` marker files that point to
    signed framework binaries in the app bundle. Plain `.so` files in
    site-packages are not enough for third-party packages on physical devices.
    """
    packages_dir = app_path / "PyPackages"
    frameworks_dir = app_path / "Frameworks"
    frameworks_dir.mkdir(parents=True, exist_ok=True)
    framework_dirs: list[Path] = []
    for so_path in sorted(packages_dir.rglob("*.so")):
        rel = so_path.relative_to(packages_dir)
        module_name = _ios_extension_module_name(rel)
        framework_name = f"{module_name}.framework"
        executable = module_name
        framework_dir = frameworks_dir / framework_name
        framework_dir.mkdir(parents=True, exist_ok=True)
        bundle_id = f"com.luvatrix.app.{module_name}".replace("_", "-")
        _write_framework_info_plist(framework_dir, executable, bundle_id)
        framework_binary = framework_dir / executable
        if framework_binary.exists():
            framework_binary.unlink()
        so_path.rename(framework_binary)

        relative_framework_binary = framework_binary.relative_to(app_path).as_posix()
        markers = _write_ios_extension_markers(so_path, relative_framework_binary)

        origin = framework_dir / f"{executable}.origin"
        origin.write_text(
            f"{markers[0].relative_to(app_path).as_posix()}\n",
            encoding="utf-8",
        )

        privacy_file = so_path.with_name(f"{so_path.name.split('.', 1)[0]}.xcprivacy")
        if privacy_file.exists():
            privacy_file.rename(framework_dir / "PrivacyInfo.xcprivacy")
        framework_dirs.append(framework_dir)
    print(f"[ios] prepared {len(framework_dirs)} Python extension frameworks")
    return framework_dirs


def _ios_extension_marker_names(source_name: str) -> list[str]:
    return [source_name.removesuffix(".so") + ".fwork"]


def _write_ios_extension_markers(
    extension_path: Path,
    relative_framework_binary: str,
) -> list[Path]:
    markers: list[Path] = []
    for marker_name in _ios_extension_marker_names(extension_path.name):
        marker = extension_path.with_name(marker_name)
        marker.write_text(f"{relative_framework_binary}\n", encoding="utf-8")
        markers.append(marker)
    return markers

def _validate_ios_extension_framework_layout(app_path: Path) -> None:
    marker = (
        app_path
        / "PyPackages"
        / "numpy"
        / "core"
        / "_multiarray_umath.cpython-312-iphoneos.fwork"
    )
    if not marker.exists():
        raise RuntimeError(f"iOS bundle is missing NumPy framework marker: {marker.relative_to(app_path)}")
    framework_rel = marker.read_text(encoding="utf-8").strip()
    framework_binary = app_path / framework_rel
    origin = framework_binary.with_name(f"{framework_binary.name}.origin")
    if not framework_binary.exists():
        raise RuntimeError(
            f"iOS NumPy marker points to missing framework binary: {framework_rel}"
        )
    if not origin.exists():
        raise RuntimeError(
            f"iOS NumPy framework is missing origin backlink: {origin.relative_to(app_path)}"
        )
    print(f"[ios] verified NumPy framework marker → {framework_rel}")


def _validate_ios_bundle_symlinks(app_path: Path) -> None:
    broken: list[str] = []
    for path in app_path.rglob("*"):
        if path.is_symlink() and not path.exists():
            broken.append(str(path.relative_to(app_path)))
    if broken:
        preview = "\n  - ".join(broken[:10])
        extra = "" if len(broken) <= 10 else f"\n  ... {len(broken) - 10} more"
        raise RuntimeError(
            "[ios] built app contains broken symlinks, which can invalidate "
            f"the bundle signature:\n  - {preview}{extra}"
        )


def _detect_team_id() -> str | None:
    """Extract Team ID from the first Apple Development certificate in the keychain."""
    import re
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "Apple Development" in line or "iPhone Developer" in line:
            m = re.search(r"\(([A-Z0-9]{10})\)", line)
            if m:
                return m.group(1)
    return None


def _decode_ios_mobileprovision(path: Path) -> dict | None:
    import plistlib

    result = subprocess.run(
        ["security", "cms", "-D", "-i", str(path)],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        return plistlib.loads(result.stdout)
    except Exception:
        return None


def _ios_mobileprovision_matches(profile: dict, team_id: str, bundle_id: str) -> bool:
    entitlements = profile.get("Entitlements", {})
    app_identifier = entitlements.get("application-identifier", "")
    team_ids = profile.get("TeamIdentifier", [])
    prefixes = profile.get("ApplicationIdentifierPrefix", [])
    return (
        app_identifier == f"{team_id}.{bundle_id}"
        or (
            app_identifier.endswith(f".{bundle_id}")
            and (team_id in team_ids or team_id in prefixes)
        )
    )


def _find_ios_mobileprovision(team_id: str, bundle_id: str) -> tuple[Path, dict] | None:
    import glob

    candidates: list[Path] = []
    candidates.extend(
        Path(path)
        for path in glob.glob(
            os.path.expanduser(
                "~/Library/Developer/Xcode/DerivedData/Luvatrix-*/Build/Products/Debug-iphoneos/Luvatrix.app/embedded.mobileprovision"
            )
        )
    )
    candidates.extend(
        Path(path)
        for path in glob.glob(
            os.path.expanduser("~/Library/MobileDevice/Provisioning Profiles/*.mobileprovision")
        )
    )
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        profile = _decode_ios_mobileprovision(path)
        if profile is not None and _ios_mobileprovision_matches(profile, team_id, bundle_id):
            return path, profile
    return None


def _describe_ios_mobileprovision_candidates(bundle_id: str) -> str:
    import glob

    lines: list[str] = []
    candidates = [
        Path(path)
        for path in glob.glob(
            os.path.expanduser(
                "~/Library/Developer/Xcode/DerivedData/Luvatrix-*/Build/Products/Debug-iphoneos/Luvatrix.app/embedded.mobileprovision"
            )
        )
    ]
    candidates.extend(
        Path(path)
        for path in glob.glob(
            os.path.expanduser("~/Library/MobileDevice/Provisioning Profiles/*.mobileprovision")
        )
    )
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        profile = _decode_ios_mobileprovision(path)
        if profile is None:
            continue
        app_identifier = profile.get("Entitlements", {}).get("application-identifier", "")
        if not app_identifier.endswith(f".{bundle_id}"):
            continue
        team_ids = ",".join(profile.get("TeamIdentifier", []))
        lines.append(
            f"  - {path} (team={team_ids or 'unknown'}, app={app_identifier})"
        )
    return "\n".join(lines) if lines else "  - none"


def _write_ios_app_entitlements(app_path: Path, team_id: str, profile: dict | None = None) -> Path:
    import plistlib

    bundle_id = "com.luvatrix.app"
    entitlements = dict((profile or {}).get("Entitlements", {}))
    if not entitlements:
        entitlements = {
            "application-identifier": f"{team_id}.{bundle_id}",
            "com.apple.developer.team-identifier": team_id,
            "get-task-allow": True,
            "keychain-access-groups": [f"{team_id}.{bundle_id}"],
        }
    entitlements_path = app_path.parent / "Luvatrix.xcent"
    with entitlements_path.open("wb") as fh:
        plistlib.dump(entitlements, fh)
    return entitlements_path


def _find_xcode_app_bundle() -> Path:
    """Locate the device .app Xcode most recently built in DerivedData."""
    import glob
    pattern = os.path.expanduser(
        "~/Library/Developer/Xcode/DerivedData/Luvatrix-*/Build/Products/Debug-iphoneos/Luvatrix.app"
    )
    candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not candidates:
        raise RuntimeError(
            "No Xcode-built Luvatrix.app found in DerivedData.\n"
            "Build once from Xcode (⌘B) with a physical device destination, then retry."
        )
    return Path(candidates[0])


def _find_signing_identity(team_id: str | None = None) -> str:
    """Return the first 'Apple Development' certificate name from the keychain."""
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    )
    fallback: str | None = None
    for line in result.stdout.splitlines():
        if "Apple Development" in line or "iPhone Developer" in line:
            # Line format: "  1) <hash> "<name>""
            import re
            m = re.search(r'"(Apple Development[^"]*|iPhone Developer[^"]*)"', line)
            if m:
                identity = m.group(1)
                if team_id is None or f"({team_id})" in identity:
                    return identity
                fallback = fallback or identity
    if team_id is not None and fallback is not None:
        raise RuntimeError(
            f"No Apple Development certificate found for team {team_id}. "
            f"Available certificate: {fallback}"
        )
    raise RuntimeError(
        "No 'Apple Development' certificate found in keychain.\n"
        "Open Xcode → Settings → Accounts and add your Apple ID."
    )


def _collect_existing_code_sign_targets(paths: list[str]) -> list[str]:
    targets: list[str] = []
    skipped: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.exists() and not path.is_symlink():
            targets.append(str(path))
        else:
            skipped.append(str(path))
    if skipped:
        print(f"[ios] skipped {len(skipped)} broken/symlinked signing paths")
    return targets


def _ios_framework_sign_targets(app_path: Path, extension_frameworks: list[Path]) -> list[Path]:
    framework_root = app_path / "Frameworks"
    targets: dict[Path, Path] = {}
    if framework_root.exists():
        for path in framework_root.glob("*.framework"):
            if path.is_dir():
                targets[path.resolve()] = path
    for path in extension_frameworks:
        if path.exists():
            targets[path.resolve()] = path
    # Sign nested frameworks first if that ever appears.
    return sorted(targets.values(), key=lambda path: len(path.parts), reverse=True)


def _run_ios_device(
    app_dir: Path,
    device_name: str | None,
    team_id: str | None,
    import_probe: bool = False,
    render_scale: float = 1.0,
    render_mode: str = "auto",
    target_fps: int | None = None,
    present_fps: int | None = None,
) -> None:
    import shutil

    repo_root = Path(__file__).parent.resolve()
    ios_dir = repo_root / "ios"
    packages_dir = _ios_packages_dir(ios_dir, "device")
    _ensure_ios_numpy_available(ios_dir, "device")

    # Find the connected device before building. If CoreDevice cannot open the
    # developer tunnel, install will fail no matter how clean the bundle is.
    device_id, display_name = _find_device_id(device_name)
    print(f"[ios] target device: {display_name} ({device_id})")

    app_dest = packages_dir / "luvatrix_app"
    if app_dest.exists():
        shutil.rmtree(app_dest)
    shutil.copytree(app_dir, app_dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"[ios] synced {app_dir} → {app_dest}")

    launch_config = {
        "LUVATRIX_IOS_RENDER_SCALE": f"{render_scale:.6g}",
        "LUVATRIX_RENDER_MODE": render_mode,
        "LUVATRIX_IOS_TARGET_FPS": str(target_fps or (60 if render_mode == "matrix" else 120)),
        "LUVATRIX_IOS_PRESENT_FPS": str(present_fps or target_fps or (60 if render_mode == "matrix" else 120)),
    }
    if import_probe:
        launch_config["LUVATRIX_IMPORT_PROBE"] = "1"
    if os.environ.get("LUVATRIX_IOS_ENABLE_HDI") == "1":
        launch_config["LUVATRIX_IOS_ENABLE_HDI"] = "1"
    if os.environ.get("LUVATRIX_FSI_DEBUG"):
        launch_config["LUVATRIX_FSI_DEBUG"] = os.environ["LUVATRIX_FSI_DEBUG"]
    (packages_dir / "luvatrix_ios_launch_config.json").write_text(
        json.dumps(launch_config, sort_keys=True),
        encoding="utf-8",
    )

    _sync_local_packages(repo_root, packages_dir)

    # Build into repo-local DerivedData so stale global Xcode builds cannot
    # mismatch PythonSupport.xcframework and the bundled native wheels.
    app_path = _build_ios_device_app(ios_dir, team_id=team_id, import_probe=import_probe)
    print(f"[ios] using fresh Xcode build: {app_path}")
    _validate_ios_xcode_app_python_abi(app_path, packages_dir, "device")
    _validate_ios_extension_framework_layout(app_path)
    _validate_ios_bundle_symlinks(app_path)
    if import_probe:
        print("[ios] import probe enabled; app runtime will not start")
    print(f"[ios] using Python packages: {packages_dir}")

    print(f"[ios] installing on {display_name}…")
    install_command = [
        "xcrun", "devicectl", "device", "install", "app",
        "--device", device_id, str(app_path),
    ]
    try:
        subprocess.run(install_command, check=True)
    except subprocess.CalledProcessError:
        print("[ios] install failed; uninstalling existing app and retrying once…")
        subprocess.run(
            ["xcrun", "devicectl", "device", "uninstall", "app",
             "--device", device_id, "com.luvatrix.app"],
            capture_output=True,
        )
        subprocess.run(install_command, check=True)

    # Start the syslog stream BEFORE the launch command so early app output
    # isn't missed and so the devicectl connection is already established.
    log_proc: subprocess.Popen | None = None
    log_thread: threading.Thread | None = None
    if not import_probe:
        log_proc, log_thread = _start_device_log_stream(device_id)
        if log_proc is not None:
            print("[ios] streaming device logs — Ctrl+C to stop", flush=True)
            time.sleep(0.5)  # Let the stream connect before we launch

    print(f"[ios] launching com.luvatrix.app on {display_name}")
    launch_ok = False
    launch_command = [
        "xcrun", "devicectl", "device", "process", "--timeout", "20", "launch",
        "--device", device_id, "--terminate-existing",
    ]
    launch_env = dict(launch_config)
    if launch_env:
        launch_command.extend(["--environment-variables", json.dumps(launch_env)])
    launch_command.append("com.luvatrix.app")
    if import_probe:
        launch_command.append("--luvatrix-import-probe")
    try:
        try:
            subprocess.run(
                launch_command,
                check=True,
                timeout=25,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired as exc:
            timeout_output = "\n".join(
                part.decode("utf-8", errors="replace") if isinstance(part, bytes) else part
                for part in (getattr(exc, "stdout", None), getattr(exc, "stderr", None))
                if part
            )
            if timeout_output.strip():
                print("[ios] launch output before timeout:")
                print(timeout_output.strip())
            if import_probe:
                print("[ios] launch command timed out; checking for import probe report anyway")
            else:
                print("[ios] launch command timed out after starting app; leaving app running")
        except subprocess.CalledProcessError as exc:
            launch_output = "\n".join(
                part for part in (exc.stdout, exc.stderr) if part
            )
            if "profile has not been explicitly trusted" in launch_output:
                print(
                    "[ios] app installed, but iOS refused to launch it because "
                    "the development profile/certificate is not trusted on the "
                    "phone yet.\n"
                    "[ios] On the phone: Settings → General → VPN & Device "
                    "Management → Apple Development: 0202alcc@gmail.com → Trust."
                )
            elif launch_output.strip():
                print("[ios] launch output:")
                print(launch_output.strip())
            if import_probe:
                print(
                    f"[ios] launch command exited {exc.returncode}; "
                    "checking for import probe report anyway"
                )
            else:
                print(
                    f"[ios] launch command exited {exc.returncode}; "
                    "app is installed, leaving device state unchanged"
                )
        if import_probe:
            time.sleep(3.0)
            _copy_ios_import_probe_report(device_id, ios_dir / ".build-device")
        launch_ok = True
        if log_thread is not None:
            log_thread.join()  # Block until stream exits or Ctrl+C
    except KeyboardInterrupt:
        if log_proc is not None and log_proc.poll() is None:
            log_proc.terminate()
        subprocess.run(
            ["xcrun", "devicectl", "device", "process", "terminate",
             "--device", device_id, "--bundle-id", "com.luvatrix.app"],
            capture_output=True,
        )
    finally:
        if log_proc is not None and log_proc.poll() is None:
            log_proc.terminate()
        if not launch_ok:
            print(f"[ios] preserved failed launch bundle for inspection: {app_path}")


def _start_device_log_stream(
    device_id: str,
) -> tuple["subprocess.Popen[str] | None", "threading.Thread | None"]:
    """Start a background thread that streams device syslog to stdout.

    Returns (proc, thread). The thread runs until the process exits or is
    terminated externally. Caller must call proc.terminate() and thread.join()
    on cleanup.  Returns (None, None) if the stream could not be started.
    """
    _TAGS = (
        "luvatrix",
        "[ios]",
        "[ios-metal]",
        "[ios-hdi]",
        "[ios-displaylink]",
        "[full_suite]",
        "run_loop",
        "setup_ui",
        "python error",
        "traceback",
    )

    cmd = [
        "xcrun", "devicectl", "device", "syslog", "stream",
        "--device", device_id,
    ]
    print(f"[ios] syslog cmd: {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so connection errors appear in the stream
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print("[ios] xcrun not found — cannot stream logs; use Xcode console instead")
        return None, None
    except OSError as exc:
        print(f"[ios] failed to start log stream: {exc}")
        return None, None

    def _read() -> None:
        assert proc.stdout is not None
        start = time.monotonic()
        captured: list[str] = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            captured.append(line)
            if any(tag in line.lower() for tag in _TAGS):
                print(line, flush=True)
        elapsed = time.monotonic() - start
        rc = proc.wait()
        if elapsed < 3.0:
            print(
                f"[ios] syslog stream exited after {elapsed:.1f}s "
                f"(rc={rc}, lines={len(captured)}) — devicectl output:",
                flush=True,
            )
            for ln in captured:
                print(f"  {ln}", flush=True)

    t = threading.Thread(target=_read, daemon=True, name="ios-syslog")
    t.start()
    return proc, t


def _copy_ios_import_probe_report(device_id: str, tmp_dir: Path) -> None:
    report_dst = tmp_dir / "luvatrix_import_probe.txt"
    result = subprocess.run(
        [
            "xcrun", "devicectl", "device", "copy", "from",
            "--device", device_id,
            "--domain-type", "appDataContainer",
            "--domain-identifier", "com.luvatrix.app",
            "--source", "Documents/luvatrix_import_probe.txt",
            "--destination", str(report_dst),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("[ios] warning: could not copy import probe report from app container")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        return
    if report_dst.exists():
        print("\n[ios] import probe report:")
        print(report_dst.read_text(encoding="utf-8"))
    else:
        print(f"[ios] warning: import probe copy succeeded but report not found at {report_dst}")


def _find_device_id(device_name: str | None) -> tuple[str, str]:
    """Return (devicectl_identifier, display_name) for the first connected iPhone/iPad."""
    import tempfile

    with tempfile.NamedTemporaryFile(prefix="luvatrix_devicectl_", suffix=".json", delete=False) as fh:
        device_json = Path(fh.name)
    result = subprocess.run(
        ["xcrun", "devicectl", "list", "devices", "--json-output", str(device_json)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        try:
            data = json.loads(device_json.read_text(encoding="utf-8"))
            devices = data.get("result", {}).get("devices", [])
            for dev in devices:
                name = dev.get("deviceProperties", {}).get("name", "")
                hardware = dev.get("hardwareProperties", {})
                connection = dev.get("connectionProperties", {})
                identifier = hardware.get("udid") or dev.get("identifier", "")
                if device_name and name != device_name:
                    continue
                if identifier:
                    state = dev.get("state", "unknown")
                    tunnel_state = connection.get("tunnelState", "unknown")
                    ddi_available = dev.get("deviceProperties", {}).get("ddiServicesAvailable")
                    print(f"[ios] devicectl device state: {state}, tunnel: {tunnel_state}")
                    if tunnel_state == "unavailable" or ddi_available is False:
                        raise RuntimeError(
                            "[ios] device is paired and visible, but CoreDevice cannot "
                            "open the developer services tunnel.\n"
                            f"[ios] device: {name} ({identifier})\n"
                            f"[ios] tunnelState={tunnel_state}, "
                            f"ddiServicesAvailable={ddi_available}\n"
                            "[ios] Unlock the phone, keep it awake, reconnect USB, "
                            "accept any Trust/Developer prompt, then retry. If it stays "
                            "unavailable, reboot the phone or restart Xcode/CoreDevice."
                        )
                    return identifier, name
        except (json.JSONDecodeError, KeyError):
            pass
        finally:
            device_json.unlink(missing_ok=True)
        raise RuntimeError(
            "No connected iOS device found through devicectl. Connect and unlock "
            "your iPhone/iPad, trust this computer, and confirm Developer Mode is enabled."
        )
    device_json.unlink(missing_ok=True)

    raise RuntimeError(
        "devicectl could not list connected iOS devices. Connect and unlock "
        "your iPhone/iPad, trust this computer, and enable Developer Mode "
        "(Settings → Privacy & Security → Developer Mode).\n"
        f"[ios] devicectl stderr: {result.stderr.strip() or result.stdout.strip()}"
    )


def _find_simulator_udid(devices_json: dict, name: str) -> str | None:
    booted_udid = None
    available_udid = None
    for devices in devices_json.get("devices", {}).values():
        for device in devices:
            if device.get("name") != name or not device.get("isAvailable", False):
                continue
            if device.get("state") == "Booted":
                booted_udid = device["udid"]
            elif available_udid is None:
                available_udid = device["udid"]
    return booted_udid or available_udid


