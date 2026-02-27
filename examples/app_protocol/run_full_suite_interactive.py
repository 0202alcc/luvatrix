from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from luvatrix_core.core import (
    AppRuntime,
    FrameRateController,
    HDIEvent,
    HDIEventSource,
    HDIThread,
    SensorManagerThread,
    WindowMatrix,
)
from luvatrix_core.core.display_runtime import DisplayRuntime
from luvatrix_core.platform.macos import (
    MacOSCameraDeviceProvider,
    MacOSMicrophoneDeviceProvider,
    MacOSMotionProvider,
    MacOSPowerVoltageCurrentProvider,
    MacOSSpeakerDeviceProvider,
    MacOSThermalTemperatureProvider,
    MacOSVulkanPresenter,
    MacOSWindowHDISource,
)
from luvatrix_core.targets.vulkan_target import VulkanTarget

from examples.app_protocol.full_suite_interactive.app_main import select_sensors

APP_DIR = Path(__file__).resolve().parent / "full_suite_interactive"


class NullHDISource(HDIEventSource):
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


def _build_providers() -> dict[str, object]:
    return {
        "thermal.temperature": MacOSThermalTemperatureProvider(),
        "power.voltage_current": MacOSPowerVoltageCurrentProvider(),
        "sensor.motion": MacOSMotionProvider(),
        "camera.device": MacOSCameraDeviceProvider(),
        "microphone.device": MacOSMicrophoneDeviceProvider(),
        "speaker.device": MacOSSpeakerDeviceProvider(),
    }


def _known_sensor_types() -> list[str]:
    return list(_build_providers().keys())


def _probe_functional_sensors(providers: dict[str, object], requested: list[str]) -> list[str]:
    functional: list[str] = []
    for sensor in requested:
        provider = providers[sensor]
        try:
            provider.read()
        except Exception:
            continue
        functional.append(sensor)
    return functional


def _sensor_capability(sensor_type: str) -> str:
    mapping = {
        "thermal.temperature": "sensor.thermal",
        "power.voltage_current": "sensor.power",
        "sensor.motion": "sensor.motion",
        "camera.device": "sensor.camera",
        "microphone.device": "sensor.microphone",
        "speaker.device": "sensor.speaker",
    }
    if sensor_type not in mapping:
        raise ValueError(f"unsupported sensor type: {sensor_type}")
    return mapping[sensor_type]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full-suite interactive app protocol example on macOS.")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument(
        "--present-fps",
        type=int,
        default=None,
        help="render presentation cadence cap; defaults to --fps",
    )
    parser.add_argument("--aspect", choices=["stretch", "preserve"], default="stretch")
    parser.add_argument("--coord-frame", choices=["screen_tl", "cartesian_bl", "cartesian_center"], default="screen_tl")
    parser.add_argument("--force-fallback", action="store_true")
    parser.add_argument("--dashboard-interval", type=float, default=0.35)
    parser.add_argument("--rewrite-delay", type=float, default=0.0)
    parser.add_argument(
        "--sensor",
        action="append",
        default=[],
        help="sensor to enable (repeatable). If omitted, auto-select machine-available sensors.",
    )
    args = parser.parse_args()

    if args.width <= 0 or args.height <= 0:
        raise ValueError("width and height must be > 0")
    if args.fps <= 0:
        raise ValueError("fps must be > 0")
    if args.dashboard_interval <= 0:
        raise ValueError("dashboard-interval must be > 0")
    if args.rewrite_delay < 0:
        raise ValueError("rewrite-delay must be >= 0")

    known_sensors = _known_sensor_types()
    requested_sensors = select_sensors(args.sensor, known_sensors) if args.sensor else list(known_sensors)
    if args.force_fallback:
        os.environ.pop("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", None)
    else:
        os.environ["LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN"] = "1"

    os.environ["LUVATRIX_FSI_ASPECT"] = args.aspect
    os.environ["LUVATRIX_FSI_COORD_FRAME"] = args.coord_frame
    os.environ["LUVATRIX_FSI_DASHBOARD_INTERVAL"] = str(args.dashboard_interval)
    os.environ["LUVATRIX_FSI_REWRITE_DELAY"] = str(args.rewrite_delay)
    os.environ["LUVATRIX_FSI_AVAILABLE_SENSORS"] = ",".join(requested_sensors)

    matrix = WindowMatrix(height=args.height, width=args.width)
    presenter = MacOSVulkanPresenter(
        width=args.width,
        height=args.height,
        title="Luvatrix Full Suite Interactive",
        preserve_aspect_ratio=args.aspect == "preserve",
    )
    target = VulkanTarget(presenter=presenter)
    display_runtime = DisplayRuntime(matrix=matrix, target=target)
    target.start()

    backend = presenter.backend
    window_handle = getattr(backend, "_window_handle", None)
    window_system = getattr(backend, "window_system", None)
    if window_handle is None or window_system is None:
        raise RuntimeError("presenter backend did not expose a window handle after start")

    hdi_source = MacOSWindowHDISource(window_handle)

    def geometry_provider() -> tuple[float, float, float, float]:
        view = window_handle.window.contentView()
        bounds = view.bounds()
        return (0.0, 0.0, float(bounds.size.width), float(bounds.size.height))

    def content_rect_provider() -> tuple[float, float, float, float]:
        _, _, view_w, view_h = geometry_provider()
        if args.aspect != "preserve":
            return (0.0, 0.0, view_w, view_h)
        target_w = max(1.0, float(args.width))
        target_h = max(1.0, float(args.height))
        scale = min(view_w / target_w, view_h / target_h)
        content_w = target_w * scale
        content_h = target_h * scale
        left = (view_w - content_w) / 2.0
        top = (view_h - content_h) / 2.0
        return (left, top, content_w, content_h)

    def active_provider() -> bool:
        try:
            return bool(window_handle.window.isKeyWindow()) and bool(window_system.is_window_open(window_handle))
        except Exception:
            return False

    hdi = HDIThread(
        source=hdi_source,
        poll_interval_s=1 / 240,
        window_active_provider=active_provider,
        window_geometry_provider=geometry_provider,
        target_extent_provider=lambda: (args.width, args.height),
        source_content_rect_provider=content_rect_provider,
    )
    providers = _build_providers()
    functional_sensors = _probe_functional_sensors(providers, requested_sensors)
    sensor_manager = SensorManagerThread(
        providers={sensor: providers[sensor] for sensor in requested_sensors},
        poll_interval_s=0.2,
    )
    runtime = AppRuntime(
        matrix=matrix,
        hdi=hdi,
        sensor_manager=sensor_manager,
        capability_decider=lambda capability: True,
    )

    manifest = runtime.load_manifest(APP_DIR)
    granted = runtime.resolve_capabilities(manifest)
    ctx = runtime.build_context(granted_capabilities=granted)
    lifecycle = runtime.load_lifecycle(APP_DIR, manifest.entrypoint)
    for sensor in requested_sensors:
        if _sensor_capability(sensor) in granted:
            sensor_manager.set_sensor_enabled(sensor, True, actor="full_suite_runner")

    hdi.start()
    sensor_manager.start()
    if args.sensor:
        selected_sensors = requested_sensors
    else:
        selected_sensors = functional_sensors
        if not selected_sensors:
            selected_sensors = requested_sensors
    os.environ["LUVATRIX_FSI_SENSORS"] = ",".join(selected_sensors)
    rate = FrameRateController(target_fps=args.fps, present_fps=args.present_fps)
    last = time.perf_counter()
    try:
        lifecycle.init(ctx)
        while not presenter.should_close():
            target.pump_events()
            now = time.perf_counter()
            dt = max(0.0, now - last)
            last = now
            lifecycle.loop(ctx, dt)
            if rate.should_present(now):
                display_runtime.run_once(timeout=0.0)
            sleep_for = rate.compute_sleep(loop_started_at=now, loop_finished_at=time.perf_counter())
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        try:
            lifecycle.stop(ctx)
        finally:
            hdi.stop()
            hdi_source.close()
            sensor_manager.stop()
            target.stop()


if __name__ == "__main__":
    main()
