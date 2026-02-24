from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Optional

import torch

from .window_matrix import CallBlitEvent, WindowMatrix
from luvatrix_core.targets.base import DisplayFrame, RenderTarget

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderTick:
    event: CallBlitEvent
    frame: DisplayFrame


class DisplayRuntime:
    """Consumes call_blit events and forwards committed frames to a render target."""

    def __init__(self, matrix: WindowMatrix, target: RenderTarget) -> None:
        self._matrix = matrix
        self._target = target
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._target_started = False
        self._last_error: Exception | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._target.start()
        self._target_started = True
        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, name="luvatrix-display", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._target_started:
            self._target.stop()
            self._target_started = False

    def run_main_thread(self, timeout: float = 0.0, idle_sleep: float = 1 / 240) -> None:
        """Run render loop on the caller thread, pumping target events and stopping on close."""
        if idle_sleep < 0:
            raise ValueError("idle_sleep must be >= 0")
        if self._target_started:
            raise RuntimeError("runtime target is already started")
        self._target.start()
        self._target_started = True
        self._running.set()
        try:
            while self._running.is_set():
                self._pump_target_events()
                if self._target_should_close():
                    self._running.clear()
                    break
                tick = self.run_once(timeout=timeout)
                if tick is None and idle_sleep > 0:
                    time.sleep(idle_sleep)
        finally:
            self.stop()

    def run_once(self, timeout: float | None = None) -> RenderTick | None:
        event = self._matrix.pop_call_blit(timeout=timeout)
        if event is None:
            return None

        # Coalesce queued blits to newest revision so frame data and revision stay aligned.
        while True:
            newer = self._matrix.pop_call_blit(timeout=None)
            if newer is None:
                break
            event = newer

        snapshot = self._matrix.read_snapshot()
        frame = _build_frame(snapshot=snapshot, revision=event.revision)
        self._target.present_frame(frame)
        return RenderTick(event=event, frame=frame)

    def _run_loop(self) -> None:
        while self._running.is_set():
            try:
                self._pump_target_events()
                if self._target_should_close():
                    self._running.clear()
                    break
                self.run_once(timeout=0.1)
            except Exception as exc:  # noqa: BLE001
                self._last_error = exc
                LOGGER.exception("DisplayRuntime render loop failed: %s", exc)
                self._running.clear()
                break

    def _pump_target_events(self) -> None:
        self._target.pump_events()

    def _target_should_close(self) -> bool:
        return self._target.should_close()

    @property
    def last_error(self) -> Exception | None:
        return self._last_error


def _build_frame(snapshot: torch.Tensor, revision: int) -> DisplayFrame:
    if snapshot.ndim != 3 or snapshot.shape[2] != 4:
        raise ValueError(f"invalid snapshot shape: {tuple(snapshot.shape)}")
    if snapshot.dtype != torch.uint8:
        raise ValueError(f"invalid snapshot dtype: {snapshot.dtype}")
    height, width, _ = snapshot.shape
    return DisplayFrame(
        revision=revision,
        width=int(width),
        height=int(height),
        rgba=snapshot,
    )
