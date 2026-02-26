from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import platform
import json
import os

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
from luvatrix_core.platform.macos.sensors import (
    MacOSCameraDeviceProvider,
    MacOSMicrophoneDeviceProvider,
    MacOSMotionProvider,
    MacOSPowerVoltageCurrentProvider,
    MacOSSpeakerDeviceProvider,
    MacOSThermalTemperatureProvider,
)
from luvatrix_core.targets.base import DisplayFrame, RenderTarget
from luvatrix_core.targets.vulkan_target import VulkanTarget


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


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
    run.add_argument("--fps", type=int, default=60)
    run.add_argument("--render", choices=["headless", "macos"], default="headless")
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
        width, height = _resolve_run_dimensions(args.render, args.width, args.height)
        matrix = WindowMatrix(height=height, width=width)
        hdi = HDIThread(source=_NoopHDISource())
        providers = {}
        if args.sensor_backend == "macos":
            if platform.system() != "Darwin":
                raise RuntimeError("sensor-backend=macos is only supported on macOS")
            providers = {
                "thermal.temperature": MacOSThermalTemperatureProvider(),
                "power.voltage_current": MacOSPowerVoltageCurrentProvider(),
                "sensor.motion": MacOSMotionProvider(),
                "camera.device": MacOSCameraDeviceProvider(),
                "microphone.device": MacOSMicrophoneDeviceProvider(),
                "speaker.device": MacOSSpeakerDeviceProvider(),
            }
        audit_sink = _build_audit_sink(args.audit_sqlite, args.audit_jsonl)
        try:
            audit_logger = audit_sink.log if audit_sink is not None else None
            sensors = SensorManagerThread(providers=providers, audit_logger=audit_logger)
            if args.render == "headless":
                target: RenderTarget = _HeadlessTarget()
            else:
                # App protocol on macOS should prefer Vulkan by default.
                os.environ.setdefault("LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN", "1")
                presenter = MacOSVulkanPresenter(width=width, height=height, title="Luvatrix App")
                target = VulkanTarget(presenter=presenter)

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
            )
            max_ticks = args.ticks
            if max_ticks is None and args.render == "headless":
                max_ticks = 600
            result = runtime.run_app(args.app_dir, max_ticks=max_ticks, target_fps=args.fps)
            print(
                f"run complete: ticks={result.ticks_run} frames={result.frames_presented} "
                f"stopped_by_target_close={result.stopped_by_target_close} "
                f"stopped_by_energy_safety={result.stopped_by_energy_safety}"
            )
        finally:
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

    if render == "macos":
        display_size = _detect_screen_size()
        if display_size is not None:
            return _fit_aspect(display_size[0], display_size[1], scale=0.82, aspect_ratio=aspect)
        return (1280, 720)
    return (640, 360)


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


if __name__ == "__main__":
    main()
