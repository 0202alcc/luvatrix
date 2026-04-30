from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from luvatrix_core.targets.base import RenderTarget
from luvatrix_core.targets.scene_target import SceneRenderTarget

from .app_runtime import AppRuntime
from .display_runtime import DisplayRuntime
from .energy_safety import EnergySafetyController
from .frame_rate_controller import FrameRateController
from .hdi_thread import HDIThread
from .scene_display_runtime import SceneDisplayRuntime
from .scene_graph import SceneGraphBuffer
from .sensor_manager import SensorManagerThread
from .window_matrix import WindowMatrix


@dataclass(frozen=True)
class UnifiedRunResult:
    ticks_run: int
    frames_presented: int
    stopped_by_target_close: bool
    stopped_by_energy_safety: bool


class _RollingRate:
    def __init__(self) -> None:
        self._window_start = time.perf_counter()
        self._window_count = 0
        self._last_rate = 0.0

    def mark(self) -> None:
        self._window_count += 1
        now = time.perf_counter()
        elapsed = now - self._window_start
        if elapsed >= 0.5:
            self._last_rate = self._window_count / max(1e-6, elapsed)
            self._window_count = 0
            self._window_start = now

    @property
    def rate(self) -> float:
        return float(self._last_rate)


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
        logical_width_px: float | None = None,
        logical_height_px: float | None = None,
        scene_target: SceneRenderTarget | None = None,
        render_mode: str = "auto",
        active_provider: Callable[[], bool] | None = None,
        vsync_read_fd: int | None = None,
    ) -> None:
        if render_mode not in ("auto", "matrix", "scene"):
            raise ValueError("render_mode must be one of: auto, matrix, scene")
        self._render_mode = render_mode
        self._scene_target = scene_target
        self._active_provider = active_provider
        self._app_loop_rate = _RollingRate()
        self._app_loop_ticks = 0
        self._scene_buffer = SceneGraphBuffer() if scene_target is not None and render_mode in ("auto", "scene") else None
        if render_mode == "scene" and scene_target is None:
            raise ValueError("render_mode='scene' requires a scene_target")
        self._matrix = matrix
        self._target = target
        self._app_runtime = AppRuntime(
            matrix=matrix,
            hdi=hdi,
            sensor_manager=sensor_manager,
            capability_decider=capability_decider,
            capability_audit_logger=capability_audit_logger,
            logical_width_px=logical_width_px,
            logical_height_px=logical_height_px,
            scene_buffer=self._scene_buffer,
        )
        self._display_runtime = DisplayRuntime(matrix=matrix, target=target)
        self._scene_display_runtime = (
            SceneDisplayRuntime(
                scene_buffer=self._scene_buffer,
                target=scene_target,
                active_provider=active_provider,
                vsync_read_fd=vsync_read_fd,
            )
            if self._scene_buffer is not None and scene_target is not None
            else None
        )
        self._energy_safety = energy_safety
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def _is_active(self) -> bool:
        if self._active_provider is None:
            return True
        try:
            return bool(self._active_provider())
        except Exception:  # noqa: BLE001
            return True

    def _runtime_telemetry(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "app_loop_fps": self._app_loop_rate.rate,
            "app_loop_ticks": int(self._app_loop_ticks),
            "app_active": int(self._is_active()),
        }
        if self._scene_display_runtime is not None:
            scene = self._scene_display_runtime.telemetry()
            payload.update(
                {
                    "present_attempt_fps": scene.present_attempt_fps,
                    "present_success_fps": scene.present_success_fps,
                    "last_present_ms": scene.last_present_ms,
                    "frames_presented": scene.frames_presented,
                    "last_presented_revision": scene.last_presented_revision,
                    "coalesced_frames": scene.coalesced_frames,
                    "repeat_presents": scene.repeat_presents,
                    "skipped_inactive": scene.skipped_inactive,
                    "present_attempts": scene.present_attempts,
                    "next_drawable_nil": scene.next_drawable_nil,
                    "next_drawable_slow": scene.next_drawable_slow,
                    "present_commits": scene.present_commits,
                    "scene_last_error": scene.last_error,
                    "last_nd_ms_x10": scene.last_nd_ms_x10,
                    "last_enc_ms_x10": scene.last_enc_ms_x10,
                    "last_txt_ms_x10": scene.last_txt_ms_x10,
                    "last_ovl_ms_x10": scene.last_ovl_ms_x10,
                    "last_cmt_ms_x10": scene.last_cmt_ms_x10,
                }
            )
        return payload

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
        debug_policy_profile = self._app_runtime.resolve_debug_policy_profile(manifest)
        granted = self._app_runtime.resolve_capabilities(manifest)
        ctx = self._app_runtime.build_context(granted_capabilities=granted)
        ctx.runtime_telemetry_provider = self._runtime_telemetry
        resolved = self._app_runtime.resolve_variant(app_path, manifest)
        if manifest.runtime_kind == "process":
            from .process_runtime import ProcessLifecycleClient  # noqa: PLC0415
            lifecycle = ProcessLifecycleClient(
                manifest.process_command,
                cwd=resolved.module_dir,
                protocol_version=manifest.protocol_version,
            )
        else:
            lifecycle = self._app_runtime.load_lifecycle(resolved.module_dir, resolved.entrypoint)
        runtime_state_setter = self._build_origin_refs_state_setter(lifecycle)
        self._configure_target_debug_menu(
            manifest.app_id,
            debug_policy_profile,
            runtime_origin_refs_state_setter=runtime_state_setter,
        )
        self._enable_granted_sensors(ctx.sensor_manager, granted)

        ticks_run = 0
        frames_presented = 0
        stopped_by_target_close = False
        stopped_by_energy_safety = False
        started = False
        active_targets: list[object] = []
        if self._scene_target is not None and self._render_mode in ("auto", "scene"):
            active_targets.append(self._scene_target)
        if self._render_mode == "matrix" or (self._render_mode == "auto" and self._scene_target is None):
            active_targets.append(self._target)
        for active_target in active_targets:
            active_target.start()
        started = True
        scene_present_loop_started = False
        ctx.hdi.start()
        ctx.sensor_manager.start()
        last = time.perf_counter()
        was_active = self._is_active()
        try:
            lifecycle.init(ctx)
            if self._scene_display_runtime is not None and self._scene_target in active_targets:
                self._scene_display_runtime.start_present_loop(
                    present_fps=present_fps or target_fps,
                    repeat_latest=True,
                )
                scene_present_loop_started = True

            tick_idx = 0
            while max_ticks is None or tick_idx < max_ticks:
                for active_target in active_targets:
                    active_target.pump_events()
                if self._scene_display_runtime is not None and self._scene_display_runtime.last_error is not None:
                    raise self._scene_display_runtime.last_error
                if any(bool(active_target.should_close()) for active_target in active_targets):
                    stopped_by_target_close = True
                    break
                now = time.perf_counter()
                active = self._is_active()
                if not active:
                    was_active = False
                    last = now
                    time.sleep(0.02)
                    continue
                if not was_active:
                    last = now
                    was_active = True
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
                self._app_loop_ticks += 1
                self._app_loop_rate.mark()
                ticks_run += 1
                tick_idx += 1
                if self._scene_display_runtime is None and rate.should_present(now):
                    tick = None
                    matrix_tick = self._display_runtime.run_once(timeout=display_timeout)
                    if matrix_tick is not None:
                        frames_presented += 1
                sleep_for = rate.compute_sleep(
                    loop_started_at=now,
                    loop_finished_at=time.perf_counter(),
                    throttle_multiplier=throttle_multiplier,
                )
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except KeyboardInterrupt:
            # Treat Ctrl+C the same way as a normal target-close stop so callers
            # get a graceful exit path instead of a traceback.
            stopped_by_target_close = True
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
                    if scene_present_loop_started and self._scene_display_runtime is not None:
                        self._scene_display_runtime.stop_present_loop()
                        if self._scene_display_runtime.frames_presented == 0:
                            self._scene_display_runtime.run_once(timeout=0.0, repeat_latest=True)
                    for active_target in reversed(active_targets):
                        active_target.stop()
        if self._scene_display_runtime is not None:
            frames_presented = self._scene_display_runtime.frames_presented
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

    def _build_origin_refs_state_setter(self, lifecycle) -> Callable[[], bool] | None:
        if not hasattr(lifecycle, "state"):
            return None

        def _toggle() -> bool:
            raw_state = getattr(lifecycle, "state", None)
            if not isinstance(raw_state, dict):
                raise RuntimeError("runtime lifecycle has no mutable state dictionary")
            current = bool(raw_state.get("origin_refs_enabled", False))
            next_value = not current
            raw_state["origin_refs_enabled"] = next_value
            raw_state["force_full_invalidation"] = True
            raw_state["force_full_invalidation_reason"] = "debug-menu-origin-refs-toggle"
            return next_value

        return _toggle

    def _configure_target_debug_menu(
        self,
        app_id: str,
        profile: dict[str, object],
        *,
        runtime_origin_refs_state_setter: Callable[[], bool] | None = None,
    ) -> None:
        configure = getattr(self._target, "configure_debug_menu", None)
        if configure is None or not callable(configure):
            return
        try:
            configure(
                app_id=app_id,
                profile=profile,
                artifact_dir="artifacts/debug_menu/runtime",
                runtime_origin_refs_state_setter=runtime_origin_refs_state_setter,
            )
        except TypeError:
            configure(
                app_id=app_id,
                profile=profile,
                artifact_dir="artifacts/debug_menu/runtime",
            )
