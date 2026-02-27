from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FrameRateController:
    """Controls simulation cadence and optional present cadence."""

    target_fps: int
    present_fps: int | None = None
    _next_present_at: float | None = None

    def __post_init__(self) -> None:
        if self.target_fps <= 0:
            raise ValueError("target_fps must be > 0")
        if self.present_fps is not None and self.present_fps <= 0:
            raise ValueError("present_fps must be > 0 when provided")
        if self.present_fps is not None and self.present_fps > self.target_fps:
            self.present_fps = self.target_fps

    @property
    def target_dt(self) -> float:
        return 1.0 / float(self.target_fps)

    @property
    def present_dt(self) -> float:
        fps = self.target_fps if self.present_fps is None else self.present_fps
        return 1.0 / float(fps)

    def should_present(self, now: float) -> bool:
        if self._next_present_at is None:
            self._next_present_at = now
        if now < self._next_present_at:
            return False
        dt = self.present_dt
        while self._next_present_at <= now:
            self._next_present_at += dt
        return True

    def compute_sleep(self, loop_started_at: float, loop_finished_at: float, throttle_multiplier: float = 1.0) -> float:
        if throttle_multiplier <= 0:
            raise ValueError("throttle_multiplier must be > 0")
        elapsed = max(0.0, loop_finished_at - loop_started_at)
        return max(0.0, (self.target_dt * throttle_multiplier) - elapsed)
