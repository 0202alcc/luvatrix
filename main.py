from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import platform
import json

from luvatrix_core.core import (
    HDIEvent,
    HDIThread,
    JsonlAuditSink,
    SQLiteAuditSink,
    SensorManagerThread,
    UnifiedRuntime,
    WindowMatrix,
)
from luvatrix_core.platform.macos import MacOSVulkanPresenter
from luvatrix_core.platform.macos.sensors import (
    MacOSMotionProvider,
    MacOSPowerVoltageCurrentProvider,
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
    run.add_argument("--ticks", type=int, default=600)
    run.add_argument("--fps", type=int, default=60)
    run.add_argument("--render", choices=["headless", "macos"], default="headless")
    run.add_argument("--width", type=int, default=640)
    run.add_argument("--height", type=int, default=360)
    run.add_argument("--sensor-backend", choices=["none", "macos"], default="none")
    run.add_argument("--audit-sqlite", type=Path, default=None)
    run.add_argument("--audit-jsonl", type=Path, default=None)

    report = sub.add_parser("audit-report", help="Print audit summary from SQLite or JSONL sink.")
    report.add_argument("--audit-sqlite", type=Path, default=None)
    report.add_argument("--audit-jsonl", type=Path, default=None)

    prune = sub.add_parser("audit-prune", help="Prune old audit rows to max row count.")
    prune.add_argument("--audit-sqlite", type=Path, default=None)
    prune.add_argument("--audit-jsonl", type=Path, default=None)
    prune.add_argument("--max-rows", type=int, required=True)
    args = parser.parse_args()

    if args.command == "run-app":
        matrix = WindowMatrix(height=args.height, width=args.width)
        hdi = HDIThread(source=_NoopHDISource())
        providers = {}
        if args.sensor_backend == "macos":
            if platform.system() != "Darwin":
                raise RuntimeError("sensor-backend=macos is only supported on macOS")
            providers = {
                "thermal.temperature": MacOSThermalTemperatureProvider(),
                "power.voltage_current": MacOSPowerVoltageCurrentProvider(),
                "sensor.motion": MacOSMotionProvider(),
            }
        audit_sink = _build_audit_sink(args.audit_sqlite, args.audit_jsonl)
        try:
            audit_logger = audit_sink.log if audit_sink is not None else None
            sensors = SensorManagerThread(providers=providers, audit_logger=audit_logger)
            if args.render == "headless":
                target: RenderTarget = _HeadlessTarget()
            else:
                presenter = MacOSVulkanPresenter(width=args.width, height=args.height, title="Luvatrix App")
                target = VulkanTarget(presenter=presenter)

            runtime = UnifiedRuntime(
                matrix=matrix,
                target=target,
                hdi=hdi,
                sensor_manager=sensors,
                capability_decider=lambda capability: True,
                capability_audit_logger=audit_logger,
            )
            result = runtime.run_app(args.app_dir, max_ticks=args.ticks, target_fps=args.fps)
            print(
                f"run complete: ticks={result.ticks_run} frames={result.frames_presented} "
                f"stopped_by_target_close={result.stopped_by_target_close}"
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


if __name__ == "__main__":
    main()
