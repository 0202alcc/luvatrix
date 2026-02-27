from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from luvatrix_core.targets.base import RenderTarget

from .app_runtime import AppRuntime
from .display_runtime import DisplayRuntime
from .energy_safety import EnergySafetyController
from .frame_rate_controller import FrameRateController
from .hdi_thread import HDIThread
from .sensor_manager import SensorManagerThread
from .window_matrix import WindowMatrix


@dataclass(frozen=True)
class UnifiedRunResult:
    ticks_run: int
    frames_presented: int
    stopped_by_target_close: bool
    stopped_by_energy_safety: bool


class UnifiedRuntime:
    """Runs app lifecycle and display presentation in one loop."""

    def __init__(
        self,
        matrix: WindowMatrix,
        target: RenderTarget,
        hdi: HDIThread,
        sensor_manager: SensorManagerThread,
        capability_decider: Callable[[str], bool] | None = None,
        capability_audit_logger: Callable[[dict[str, object]], None] | None = None,
        energy_safety: EnergySafetyController | None = None,
    ) -> None:
        self._matrix = matrix
        self._target = target
        self._app_runtime = AppRuntime(
            matrix=matrix,
            hdi=hdi,
            sensor_manager=sensor_manager,
            capability_decider=capability_decider,
            capability_audit_logger=capability_audit_logger,
        )
        self._display_runtime = DisplayRuntime(matrix=matrix, target=target)
        self._energy_safety = energy_safety
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def run_app(
        self,
        app_dir: str | Path,
        *,
        max_ticks: int | None = 1,
        target_fps: int = 60,
        present_fps: int | None = None,
        display_timeout: float = 0.0,
    ) -> UnifiedRunResult:
        if max_ticks is not None and max_ticks <= 0:
            raise ValueError("max_ticks must be > 0")
        rate = FrameRateController(target_fps=target_fps, present_fps=present_fps)
        app_path = Path(app_dir).resolve()
        manifest = self._app_runtime.load_manifest(app_path)
        granted = self._app_runtime.resolve_capabilities(manifest)
        ctx = self._app_runtime.build_context(granted_capabilities=granted)
        resolved = self._app_runtime.resolve_variant(app_path, manifest)
        lifecycle = self._app_runtime.load_lifecycle(resolved.module_dir, resolved.entrypoint)
        self._enable_granted_sensors(ctx.sensor_manager, granted)

        ticks_run = 0
        frames_presented = 0
        stopped_by_target_close = False
        stopped_by_energy_safety = False
        started = False
        self._target.start()
        started = True
        ctx.hdi.start()
        ctx.sensor_manager.start()
        last = time.perf_counter()
        try:
            lifecycle.init(ctx)
            tick_idx = 0
            while max_ticks is None or tick_idx < max_ticks:
                self._target.pump_events()
                if self._target.should_close():
                    stopped_by_target_close = True
                    break
                now = time.perf_counter()
                dt = max(0.0, now - last)
                last = now
                throttle_multiplier = 1.0
                if self._energy_safety is not None:
                    decision = self._energy_safety.evaluate()
                    throttle_multiplier = max(1.0, decision.throttle_multiplier)
                    if decision.should_shutdown:
                        stopped_by_energy_safety = True
                        break
                lifecycle.loop(ctx, dt)
                ticks_run += 1
                tick_idx += 1
                if rate.should_present(now):
                    tick = self._display_runtime.run_once(timeout=display_timeout)
                    if tick is not None:
                        frames_presented += 1
                sleep_for = rate.compute_sleep(
                    loop_started_at=now,
                    loop_finished_at=time.perf_counter(),
                    throttle_multiplier=throttle_multiplier,
                )
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except Exception as exc:  # noqa: BLE001
            self._last_error = exc
            raise
        finally:
            try:
                lifecycle.stop(ctx)
            finally:
                ctx.hdi.stop()
                ctx.sensor_manager.stop()
                if started:
                    self._target.stop()
        return UnifiedRunResult(
            ticks_run=ticks_run,
            frames_presented=frames_presented,
            stopped_by_target_close=stopped_by_target_close,
            stopped_by_energy_safety=stopped_by_energy_safety,
        )

    def _enable_granted_sensors(self, sensor_manager: SensorManagerThread, granted_capabilities: set[str]) -> None:
        mapping = {
            "sensor.thermal": "thermal.temperature",
            "sensor.power": "power.voltage_current",
            "sensor.motion": "sensor.motion",
            "sensor.camera": "camera.device",
            "sensor.microphone": "microphone.device",
            "sensor.speaker": "speaker.device",
        }
        for cap, sensor_type in mapping.items():
            if cap in granted_capabilities:
                sensor_manager.set_sensor_enabled(sensor_type, True, actor="unified_runtime")
