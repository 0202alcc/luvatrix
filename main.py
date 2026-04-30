from __future__ import annotations

import argparse
import logging
import platform
import json
import os
import subprocess
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from luvatrix.app import MissingOptionalDependencyError, validate_app_install
from luvatrix_core.core import (
    HDIEvent,
    HDIThread,
    SensorEnergySafetyController,
    SensorManagerThread,
    EnergySafetyPolicy,
    UnifiedRuntime,
    WindowMatrix,
)
from luvatrix_core.platform import PresentationMode, normalize_presentation_mode
from luvatrix_core.targets.base import DisplayFrame, RenderTarget


LOGGER = logging.getLogger(__name__)


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class _HeadlessTarget(RenderTarget):
    def start(self) -> None:
        return

    def present_frame(self, frame: DisplayFrame) -> None:
        pass

    def stop(self) -> None:
        return


class _MacOSPresenterHDISource:
    """Stub HDI source that receives the real MacOSWindowHDISource via inject()
    once the window exists on the main thread."""

    def __init__(self) -> None:
        self._inner = None

    def inject(self, source) -> None:
        self._inner = source

    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        if self._inner is None:
            return []
        return self._inner.poll(window_active, ts_ns)


def _make_macos_window_geometry_provider(backend) -> tuple[float, float, float, float]:
    def _provider() -> tuple[float, float, float, float]:
        handle = getattr(backend, "_window_handle", None)
        if handle is None:
            return (0.0, 0.0, 1.0, 1.0)
        try:
            view = handle.window.contentView()
            bounds = view.bounds()
            return (0.0, 0.0, float(bounds.size.width), float(bounds.size.height))
        except Exception:
            return (0.0, 0.0, 1.0, 1.0)

    return _provider


def _detect_screen_size() -> tuple[int, int] | None:
    try:
        from luvatrix_core.platform.macos.window_system import AppKitWindowSystem
        return AppKitWindowSystem().get_main_screen_size()
    except Exception:
        return None


def _warn_if_not_free_threaded():
    if sysconfig.get_config_var("Py_GIL_DISABLED") != 1:
        print("WARNING: This build of Python is not free-threaded (GIL is enabled).")
        print("Performance and concurrency will be significantly degraded.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Luvatrix high-performance UI runtime")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run-app", help="Run a luvatrix app")
    run.add_argument("app_dir", type=Path, help="Path to the app directory (containing app.toml)")
    run.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Max app-loop ticks. Default: run until window close for macos/web render; 600 for headless render.",
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
    run.add_argument("--render", choices=["headless", "macos", "macos-metal", "ios-simulator", "ios-device", "web"], default="headless")
    run.add_argument(
        "--render-scale",
        type=float,
        default=1.0,
        help=(
            "Internal matrix scale before presenter/window scaling. "
            "Lower values trade sharpness for speed; default: 1.0."
        ),
    )
    run.add_argument(
        "--render-mode",
        choices=["auto", "matrix", "scene"],
        default="auto",
        help="Rendering contract to use. scene enables the retained SceneFrame path when supported.",
    )
    run.add_argument(
        "--presentation-mode",
        choices=[mode.value for mode in PresentationMode],
        default=None,
        help="Presentation fit mode. Default: pixel_preserve for macos, stretch for headless/web.",
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
        "--lock-window-size",
        action="store_true",
        help="Prevent the macOS window from being user-resizable; presentation fits inside the fixed window size.",
    )
    run.add_argument(
        "--width",
        type=int,
        default=None,
        help="Window/matrix width. Default: display-relative for macos render, 640 for headless/web.",
    )
    run.add_argument(
        "--height",
        type=int,
        default=None,
        help="Window/matrix height. Default: display-relative for macos render, 360 for headless/web.",
    )
    run.add_argument("--sensor-backend", choices=["none", "macos"], default="none")
    run.add_argument(
        "--energy-safety",
        choices=["off", "warn", "enforce"],
        default="off",
        help="Monitor thermal/power sensors and throttle or shutdown. Default: off.",
    )
    run.add_argument("--energy-thermal-warn-c", type=float, default=65.0)
    run.add_argument("--energy-thermal-critical-c", type=float, default=80.0)
    run.add_argument("--energy-power-warn-w", type=float, default=15.0)
    run.add_argument("--energy-power-critical-w", type=float, default=25.0)
    run.add_argument("--energy-critical-streak", type=int, default=30)
    run.add_argument("--audit-sqlite", type=Path, default=None, help="Path to write performance audit events.")

    args = parser.parse_args()

    if args.command == "run-app":
        try:
            validate_app_install(args.app_dir, render=args.render)
        except MissingOptionalDependencyError as exc:
            raise SystemExit(str(exc)) from exc

        _warn_if_not_free_threaded()

        if args.render == "ios-simulator":
            from luvatrix_core.platform.ios.runner import _run_ios_simulator
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
            from luvatrix_core.platform.ios.runner import _run_ios_device
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

        native_w, native_h, bar_color, display_title, display_icon = read_app_display_config(args.app_dir)
        has_native = native_w is not None and native_h is not None
        app_title = display_title or "Luvatrix App"
        icon_path = None
        if display_icon is not None:
            icon_candidate_path = Path(display_icon)
            icon_path = str(icon_candidate_path if icon_candidate_path.is_absolute() else Path(args.app_dir) / icon_candidate_path)

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
            from luvatrix_core.platform.macos.sensors import make_default_macos_sensor_providers
            providers = make_default_macos_sensor_providers()

        sensors = SensorManagerThread(providers=providers)
        audit_logger = _build_audit_sink(args.audit_sqlite)

        try:
            sensors.start()
            on_targets_started = None
            if args.render == "headless":
                target: RenderTarget = _HeadlessTarget()
                hdi = HDIThread(source=_NoopHDISource())
            elif args.render == "web":
                from luvatrix_core.platform.web.websocket_target import (
                    WebSessionServer,
                    _SingleClientTarget,
                )

                def _web_session(target: _SingleClientTarget) -> None:
                    _hdi = HDIThread(source=_NoopHDISource())
                    _matrix = WindowMatrix(height=matrix_height, width=matrix_width)
                    _energy = _build_energy_safety(args, sensors, audit_logger)
                    _runtime = UnifiedRuntime(
                        matrix=_matrix,
                        target=target,
                        hdi=_hdi,
                        sensor_manager=sensors,
                        capability_decider=lambda cap: True,
                        capability_audit_logger=audit_logger,
                        energy_safety=_energy,
                        logical_width_px=float(logical_width),
                        logical_height_px=float(logical_height),
                    )
                    _runtime.run_app(
                        args.app_dir,
                        max_ticks=args.ticks,
                        target_fps=_resolve_target_fps(args.fps),
                        present_fps=args.present_fps,
                    )

                server = WebSessionServer(
                    session_factory=_web_session, host="0.0.0.0", port=8765,
                )
                print("[luvatrix] Web server running - open http://localhost:8765")
                server.run()
                return
            elif args.render == "macos-metal":
                from luvatrix_core.platform.macos.metal_presenter import MacOSMetalPresenter
                from luvatrix_core.targets.metal_target import MetalTarget

                presenter = MacOSMetalPresenter(
                    width=width,
                    height=height,
                    title=app_title,
                    bar_color_rgba=bar_color,
                    resizable=not has_native,
                    icon_path=icon_path,
                )
                target = MetalTarget(presenter=presenter)
                _macos_backend = presenter.backend
                hdi_source = _MacOSPresenterHDISource()
                hdi = HDIThread(
                    source=hdi_source,
                    window_geometry_provider=_make_macos_window_geometry_provider(_macos_backend),
                    target_extent_provider=lambda: (float(width), float(height)),
                )

                def on_targets_started(_src=hdi_source, _backend=_macos_backend):  # type: ignore[misc]
                    handle = getattr(_backend, "_window_handle", None)
                    if handle is not None:
                        from luvatrix_core.platform.macos.hdi_source import MacOSWindowHDISource
                        _src.inject(MacOSWindowHDISource(handle))
            else:
                from luvatrix_core.platform.macos import MacOSVulkanPresenter
                from luvatrix_core.platform.vulkan_setup import detect_vulkan_preflight_issue
                from luvatrix_core.targets.vulkan_target import VulkanTarget

                # App protocol on macOS should prefer Vulkan by default.
                os.environ.setdefault("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", "1")
                preflight_issue = detect_vulkan_preflight_issue()
                if preflight_issue:
                    LOGGER.warning("Vulkan preflight failed: %s; falling back to Cocoa layer blitting.", preflight_issue)

                presenter = MacOSVulkanPresenter(
                    width=width,
                    height=height,
                    title=app_title,
                    bar_color_rgba=bar_color,
                    lock_window_size=has_native,
                    icon_path=icon_path,
                )
                target = VulkanTarget(presenter=presenter)
                _macos_backend = presenter.backend
                hdi_source = _MacOSPresenterHDISource()
                hdi = HDIThread(
                    source=hdi_source,
                    window_geometry_provider=_make_macos_window_geometry_provider(_macos_backend),
                    target_extent_provider=lambda: (float(width), float(height)),
                )

                def on_targets_started(_src=hdi_source, _backend=_macos_backend):  # type: ignore[misc]
                    handle = getattr(_backend, "_window_handle", None)
                    if handle is not None:
                        from luvatrix_core.platform.macos.hdi_source import MacOSWindowHDISource
                        _src.inject(MacOSWindowHDISource(handle))

            scene_target = None
            if args.render_mode == "scene":
                from luvatrix_core.targets.cpu_scene_target import CpuSceneTarget
                scene_target = CpuSceneTarget(target)

            energy_safety = _build_energy_safety(args, sensors, audit_logger)

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
            if max_ticks is None and args.render == "headless":
                max_ticks = 600
            target_fps = _resolve_target_fps(args.fps)
            result = runtime.run_app(
                args.app_dir,
                max_ticks=max_ticks,
                target_fps=target_fps,
                present_fps=args.present_fps,
                on_targets_started=on_targets_started,
            )
            print(
                f"run complete: ticks={result.ticks_run} frames={result.frames_presented} "
                f"stopped_by_target_close={result.stopped_by_target_close} "
                f"stopped_by_energy_safety={result.stopped_by_energy_safety}"
            )
        finally:
            sensors.stop()


def _resolve_target_fps(fps_arg: int | None) -> int:
    if fps_arg is not None:
        return int(fps_arg)
    # TODO: Detect display refresh and use 2x (Nyquist).
    return 120


def _resolve_render_scale(scale_arg: float) -> float:
    return max(0.01, min(2.0, float(scale_arg)))


def _resolve_presentation_mode(render: str, mode: str | None) -> PresentationMode:
    if mode is not None:
        return PresentationMode(mode)
    if render == "macos":
        return PresentationMode.PIXEL_PRESERVE
    return PresentationMode.STRETCH


def _build_audit_sink(audit_sqlite: Path | None):
    if audit_sqlite is not None:
        from luvatrix_core.core.audit import SQLiteAuditSink
        return SQLiteAuditSink(audit_sqlite).append
    return None


def _build_energy_safety(args, sensors: SensorManagerThread, audit_logger):
    if args.energy_safety == "off":
        return None
    return SensorEnergySafetyController(
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


def _resolve_run_dimensions(render: str, width: int | None, height: int | None) -> tuple[int, int]:
    aspect = 16.0 / 9.0
    if width is not None and width <= 0:
        width = None
    if height is not None and height <= 0:
        height = None

    if render in ("macos", "macos-metal") and width is None and height is None:
        screen = _detect_screen_size()
        if screen:
            w, h = screen
            return (int(w * 0.8), int(h * 0.8))
        return (1600, 1000)

    if width is not None and height is not None:
        return (width, height)
    if width is not None:
        return (width, int(width / aspect))
    if height is not None:
        return (int(height * aspect), height)
    return (640, 360)


if __name__ == "__main__":
    main()
