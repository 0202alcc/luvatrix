from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import platform
import json
import os
import subprocess
import threading
import time

from luvatrix_core.core import (
    HDIEvent,
    HDIThread,
    EnergySafetyPolicy,
    JsonlAuditSink,
    SQLiteAuditSink,
    SensorEnergySafetyController,
    SensorManagerThread,
    UnifiedRuntime,
    WindowMatrix,
)
from luvatrix_core.platform.macos import MacOSVulkanPresenter
from luvatrix_core.platform.macos.hdi_source import MacOSWindowHDISource
from luvatrix_core.platform.macos.metal_presenter import MacOSMetalPresenter
from luvatrix_core.platform.macos.sensors import (
    make_default_macos_sensor_providers,
)
from luvatrix_core.platform.vulkan_setup import detect_vulkan_preflight_issue
from luvatrix_core.targets.base import DisplayFrame, RenderTarget
from luvatrix_core.targets.metal_target import MetalTarget
from luvatrix_core.targets.vulkan_target import VulkanTarget


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class _MacOSPresenterHDISource:
    """Lazily binds to the presenter window handle after target start."""

    def __init__(self, presenter: MacOSVulkanPresenter | MacOSMetalPresenter) -> None:
        self._presenter = presenter
        self._delegate: MacOSWindowHDISource | None = None
        self._window_handle = None

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        _ = window_active
        if self._delegate is None:
            backend = getattr(self._presenter, "backend", None)
            handle = getattr(backend, "_window_handle", None)
            if handle is not None:
                self._window_handle = handle
                self._delegate = MacOSWindowHDISource(handle)
        if self._delegate is None:
            return []
        return self._delegate.poll(window_active=window_active, ts_ns=ts_ns)

    def window_active(self) -> bool:
        handle = self._window_handle
        if handle is None:
            return True
        try:
            return bool(handle.window.isKeyWindow())
        except Exception:
            return True

    def window_geometry(self) -> tuple[float, float, float, float]:
        handle = self._window_handle
        if handle is None:
            return (0.0, 0.0, 1.0, 1.0)
        try:
            view = handle.window.contentView()
            bounds = view.bounds()
            return (0.0, 0.0, float(bounds.size.width), float(bounds.size.height))
        except Exception:
            return (0.0, 0.0, 1.0, 1.0)

    def close(self) -> None:
        if self._delegate is not None:
            self._delegate.close()


@dataclass
class _HeadlessTarget(RenderTarget):
    frames_presented: int = 0
    started: bool = False

    def start(self) -> None:
        self.started = True

    def present_frame(self, frame: DisplayFrame) -> None:
        if not self.started:
            raise RuntimeError("headless target not started")
        self.frames_presented += 1

    def stop(self) -> None:
        self.started = False


def main() -> None:
    parser = argparse.ArgumentParser(prog="luvatrix")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run-app", help="Run an app protocol folder (app.toml + entrypoint).")
    run.add_argument("app_dir", type=Path)
    run.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Max app-loop ticks. Default: run until window close for macos render; 600 for headless render.",
    )
    run.add_argument(
        "--fps",
        type=int,
        default=None,
        help="Target app-loop FPS. Default: 2x display refresh (Nyquist), fallback 120.",
    )
    run.add_argument(
        "--present-fps",
        type=int,
        default=None,
        help="Optional presentation FPS cap. Default: present every app-loop tick.",
    )
    run.add_argument(
        "--render-scale",
        type=float,
        default=1.0,
        help=(
            "Internal matrix scale before presenter/window scaling. "
            "Lower values trade sharpness for speed; default: 1.0."
        ),
    )
    run.add_argument("--render", choices=["headless", "macos", "macos-metal", "ios-simulator", "ios-device", "web"], default="headless")
    run.add_argument(
        "--render-mode",
        choices=["auto", "matrix", "scene"],
        default="auto",
        help="Rendering contract to use. scene enables the retained SceneFrame path when supported.",
    )
    run.add_argument("--simulator", default="iPhone 16", help="Simulator device name for --render ios-simulator.")
    run.add_argument("--device", default=None, help="Physical device name for --render ios-device (default: first connected device).")
    run.add_argument("--team-id", default=None, help="Apple Development Team ID for --render ios-device (or set DEVELOPMENT_TEAM env var).")
    run.add_argument(
        "--ios-import-probe",
        action="store_true",
        help="For --render ios-device, launch a minimal native import probe instead of the app runtime.",
    )
    run.add_argument(
        "--width",
        type=int,
        default=None,
        help="Window/matrix width. Default: display-relative for macos render, 640 for headless.",
    )
    run.add_argument(
        "--height",
        type=int,
        default=None,
        help="Window/matrix height. Default: display-relative for macos render, 360 for headless.",
    )
    run.add_argument("--sensor-backend", choices=["none", "macos"], default="none")
    run.add_argument(
        "--show-origin-refs",
        action="store_true",
        help="Enable Planes origin-reference debug overlay (camera, active planes, mounted components).",
    )
    run.add_argument("--audit-sqlite", type=Path, default=None)
    run.add_argument("--audit-jsonl", type=Path, default=None)
    run.add_argument("--energy-safety", choices=["off", "monitor", "enforce"], default="monitor")
    run.add_argument("--energy-thermal-warn-c", type=float, default=85.0)
    run.add_argument("--energy-thermal-critical-c", type=float, default=95.0)
    run.add_argument("--energy-power-warn-w", type=float, default=45.0)
    run.add_argument("--energy-power-critical-w", type=float, default=65.0)
    run.add_argument("--energy-critical-streak", type=int, default=3)

    report = sub.add_parser("audit-report", help="Print audit summary from SQLite or JSONL sink.")
    report.add_argument("--audit-sqlite", type=Path, default=None)
    report.add_argument("--audit-jsonl", type=Path, default=None)

    prune = sub.add_parser("audit-prune", help="Prune old audit rows to max row count.")
    prune.add_argument("--audit-sqlite", type=Path, default=None)
    prune.add_argument("--audit-jsonl", type=Path, default=None)
    prune.add_argument("--max-rows", type=int, required=True)
    args = parser.parse_args()

    if args.command == "run-app":
        if args.render == "ios-simulator":
            _run_ios_simulator(
                args.app_dir.resolve(),
                simulator_name=args.simulator,
                render_scale=_resolve_render_scale(args.render_scale),
                render_mode=args.render_mode,
                target_fps=_resolve_target_fps(args.fps) if args.fps is not None else None,
                present_fps=args.present_fps,
            )
            return
        if args.render == "ios-device":
            _run_ios_device(
                args.app_dir.resolve(),
                device_name=args.device,
                team_id=args.team_id,
                import_probe=args.ios_import_probe,
                render_scale=_resolve_render_scale(args.render_scale),
                render_mode=args.render_mode,
                target_fps=_resolve_target_fps(args.fps) if args.fps is not None else None,
                present_fps=args.present_fps,
            )
            return

        from luvatrix_core.core.app_runtime import read_app_display_config
        native_w, native_h, bar_color = read_app_display_config(args.app_dir)
        has_native = native_w is not None and native_h is not None

        if has_native and args.render in ("macos", "macos-metal"):
            screen = _detect_screen_size() or (2560, 1440)
            raw_scale = min(screen[0] * 0.82 / native_w, screen[1] * 0.82 / native_h)
            scale = max(1, int(raw_scale))
            width, height = native_w * scale, native_h * scale
        else:
            width, height = _resolve_run_dimensions(args.render, args.width, args.height)
        render_scale = _resolve_render_scale(args.render_scale)
        logical_width = int(native_w if has_native else width)
        logical_height = int(native_h if has_native else height)
        matrix_width = max(1, int(round(float(logical_width) * render_scale)))
        matrix_height = max(1, int(round(float(logical_height) * render_scale)))
        matrix = WindowMatrix(height=matrix_height, width=matrix_width)
        providers = {}
        hdi_source = None
        if args.sensor_backend == "macos":
            if platform.system() != "Darwin":
                raise RuntimeError("sensor-backend=macos is only supported on macOS")
            providers = make_default_macos_sensor_providers()
        audit_sink = _build_audit_sink(args.audit_sqlite, args.audit_jsonl)
        try:
            os.environ["LUVATRIX_SHOW_ORIGIN_REFS"] = "1" if bool(args.show_origin_refs) else "0"
            audit_logger = audit_sink.log if audit_sink is not None else None
            sensors = SensorManagerThread(providers=providers, audit_logger=audit_logger)
            if args.render in ("macos", "macos-metal"):
                _icon = Path(__file__).parent / "assets" / "icon.png"
                if _icon.exists():
                    _set_macos_app_icon(_icon)

            if args.render == "headless":
                target: RenderTarget = _HeadlessTarget()
                hdi_source = _NoopHDISource()
            elif args.render == "web":
                from luvatrix_core.platform.web.websocket_target import (
                    WebSessionServer,
                    _SingleClientTarget,
                )
                _logical_w = logical_width
                _logical_h = logical_height
                _matrix_w = matrix_width
                _matrix_h = matrix_height
                _app_dir = args.app_dir
                _max_ticks = args.ticks
                _target_fps = _resolve_target_fps(args.fps)
                _present_fps = args.present_fps
                _audit_logger = audit_logger

                def _web_session(target: _SingleClientTarget) -> None:
                    _hdi = HDIThread(source=_NoopHDISource())
                    _matrix = WindowMatrix(height=_matrix_h, width=_matrix_w)
                    _energy = None
                    if args.energy_safety != "off":
                        _energy = SensorEnergySafetyController(
                            sensor_manager=sensors,
                            policy=EnergySafetyPolicy(
                                thermal_warn_c=args.energy_thermal_warn_c,
                                thermal_critical_c=args.energy_thermal_critical_c,
                                power_warn_w=args.energy_power_warn_w,
                                power_critical_w=args.energy_power_critical_w,
                                critical_streak_for_shutdown=args.energy_critical_streak,
                            ),
                            audit_logger=_audit_logger,
                            enforce_shutdown=args.energy_safety == "enforce",
                        )
                    _runtime = UnifiedRuntime(
                        matrix=_matrix,
                        target=target,
                        hdi=_hdi,
                        sensor_manager=sensors,
                        capability_decider=lambda cap: True,
                        capability_audit_logger=_audit_logger,
                        energy_safety=_energy,
                        logical_width_px=float(_logical_w),
                        logical_height_px=float(_logical_h),
                    )
                    _hdi.start()
                    try:
                        _runtime.run_app(
                            _app_dir,
                            max_ticks=_max_ticks,
                            target_fps=_target_fps,
                            present_fps=_present_fps,
                        )
                    finally:
                        _hdi.stop()

                server = WebSessionServer(
                    session_factory=_web_session, host="0.0.0.0", port=8765,
                )
                print("[luvatrix] Web server running — open http://localhost:8765")
                server.run()
                return
            elif args.render == "macos-metal":
                presenter = MacOSMetalPresenter(
                    width=width, height=height, title="Luvatrix App",
                    bar_color_rgba=bar_color, resizable=not has_native,
                )
                target = MetalTarget(presenter=presenter)
                hdi_source = _MacOSPresenterHDISource(presenter)
            else:
                # App protocol on macOS should prefer Vulkan by default.
                os.environ.setdefault("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", "1")
                preflight_issue = detect_vulkan_preflight_issue()
                if preflight_issue is not None:
                    print("[luvatrix] Vulkan preflight notice:")
                    print(preflight_issue)
                    print("[luvatrix] Falling back to layer-blit mode if Vulkan cannot initialize.")
                presenter = MacOSVulkanPresenter(width=width, height=height, title="Luvatrix App")
                target = VulkanTarget(presenter=presenter)
                hdi_source = _MacOSPresenterHDISource(presenter)
            if isinstance(hdi_source, _MacOSPresenterHDISource):
                hdi = HDIThread(
                    source=hdi_source,
                    window_active_provider=hdi_source.window_active,
                    window_geometry_provider=hdi_source.window_geometry,
                )
            else:
                hdi = HDIThread(source=hdi_source)

            scene_target = None
            if args.render_mode == "scene":
                from luvatrix_core.targets.cpu_scene_target import CpuSceneTarget
                scene_target = CpuSceneTarget(target)

            energy_safety = None
            if args.energy_safety != "off":
                energy_safety = SensorEnergySafetyController(
                    sensor_manager=sensors,
                    policy=EnergySafetyPolicy(
                        thermal_warn_c=args.energy_thermal_warn_c,
                        thermal_critical_c=args.energy_thermal_critical_c,
                        power_warn_w=args.energy_power_warn_w,
                        power_critical_w=args.energy_power_critical_w,
                        critical_streak_for_shutdown=args.energy_critical_streak,
                    ),
                    audit_logger=audit_logger,
                    enforce_shutdown=args.energy_safety == "enforce",
                )

            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda capability: True,
                capability_audit_logger=audit_logger,
                energy_safety=energy_safety,
                logical_width_px=float(logical_width),
                logical_height_px=float(logical_height),
                scene_target=scene_target,
                render_mode=args.render_mode,
            )
            max_ticks = args.ticks
            if max_ticks is None and args.render in ("headless",):
                max_ticks = 600
            target_fps = _resolve_target_fps(args.fps)
            result = runtime.run_app(
                args.app_dir,
                max_ticks=max_ticks,
                target_fps=target_fps,
                present_fps=args.present_fps,
            )
            print(
                f"run complete: ticks={result.ticks_run} frames={result.frames_presented} "
                f"stopped_by_target_close={result.stopped_by_target_close} "
                f"stopped_by_energy_safety={result.stopped_by_energy_safety}"
            )
        finally:
            if hdi_source is not None and hasattr(hdi_source, "close"):
                hdi_source.close()
            if audit_sink is not None and hasattr(audit_sink, "close"):
                audit_sink.close()
        return

    if args.command == "audit-report":
        audit_sink = _build_audit_sink(args.audit_sqlite, args.audit_jsonl)
        if audit_sink is None:
            raise RuntimeError("one of --audit-sqlite/--audit-jsonl is required")
        try:
            print(json.dumps(audit_sink.summarize(), indent=2, sort_keys=True))
        finally:
            if hasattr(audit_sink, "close"):
                audit_sink.close()
        return

    if args.command == "audit-prune":
        audit_sink = _build_audit_sink(args.audit_sqlite, args.audit_jsonl)
        if audit_sink is None:
            raise RuntimeError("one of --audit-sqlite/--audit-jsonl is required")
        try:
            deleted = audit_sink.prune(max_rows=args.max_rows)
            print(f"pruned rows={deleted}")
        finally:
            if hasattr(audit_sink, "close"):
                audit_sink.close()
        return

    raise RuntimeError(f"unsupported command: {args.command}")


def _build_audit_sink(audit_sqlite: Path | None, audit_jsonl: Path | None):
    if audit_sqlite is not None:
        return SQLiteAuditSink(audit_sqlite)
    if audit_jsonl is not None:
        return JsonlAuditSink(audit_jsonl)
    return None


def _resolve_run_dimensions(render: str, width: int | None, height: int | None) -> tuple[int, int]:
    aspect = 16.0 / 9.0
    if width is not None and width <= 0:
        raise ValueError("width must be > 0")
    if height is not None and height <= 0:
        raise ValueError("height must be > 0")

    if width is not None and height is not None:
        return width, height
    if width is not None:
        return width, max(1, int(round(width / aspect)))
    if height is not None:
        return max(1, int(round(height * aspect))), height

    if render in ("macos", "macos-metal"):
        display_size = _detect_screen_size()
        if display_size is not None:
            return _fit_aspect(display_size[0], display_size[1], scale=0.82, aspect_ratio=aspect)
        return (1280, 720)
    return (640, 360)


def _resolve_render_scale(explicit_scale: float | None) -> float:
    if explicit_scale is None:
        return 1.0
    try:
        scale = float(explicit_scale)
    except (TypeError, ValueError) as exc:
        raise ValueError("render-scale must be a finite number") from exc
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("render-scale must be > 0")
    return max(0.25, min(4.0, scale))


def _fit_aspect(screen_w: int, screen_h: int, *, scale: float, aspect_ratio: float) -> tuple[int, int]:
    max_w = max(1, int(screen_w * scale))
    max_h = max(1, int(screen_h * scale))
    w = max_w
    h = int(round(w / aspect_ratio))
    if h > max_h:
        h = max_h
        w = int(round(h * aspect_ratio))
    w = max(w, 960)
    h = max(h, 540)
    return (max(1, int(math.floor(w))), max(1, int(math.floor(h))))


def _detect_screen_size() -> tuple[int, int] | None:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
        root.destroy()
        if width > 0 and height > 0:
            return (width, height)
    except Exception:
        return None
    return None


def _resolve_target_fps(explicit_fps: int | None) -> int:
    if explicit_fps is not None:
        if explicit_fps <= 0:
            raise ValueError("fps must be > 0")
        return int(explicit_fps)
    refresh_hz = _detect_display_refresh_hz()
    if refresh_hz is None or refresh_hz <= 0:
        refresh_hz = 60.0
    return max(1, int(round(refresh_hz * 2.0)))


def _detect_display_refresh_hz() -> float | None:
    env = os.getenv("LUVATRIX_DISPLAY_REFRESH_HZ")
    if env:
        try:
            value = float(env)
            if value > 0:
                return value
        except ValueError:
            pass
    if platform.system() != "Darwin":
        return None
    try:
        proc = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=4.0,
        )
        payload = json.loads(proc.stdout)
        displays = payload.get("SPDisplaysDataType", [])
        for entry in displays:
            if not isinstance(entry, dict):
                continue
            for key in ("spdisplays_display_refresh_rate", "spdisplays_refresh_rate"):
                raw = entry.get(key)
                if raw is None:
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    return value
    except Exception:
        pass
    return None


def _set_macos_app_icon(icon_path: Path) -> None:
    try:
        from AppKit import NSApplication, NSImage  # type: ignore
        img = NSImage.imageWithContentsOfFile_(str(icon_path))
        if img is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass


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


if __name__ == "__main__":
    main()
