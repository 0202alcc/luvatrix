from __future__ import annotations

from dataclasses import dataclass
import fcntl
import logging
import os
import select as _select
import threading
import time
from typing import Callable

from luvatrix_core.core.scene_graph import SceneBlitEvent, SceneFrame, SceneGraphBuffer
from luvatrix_core.targets.scene_target import SceneRenderTarget


# ---------------------------------------------------------------------------
# Pipe-based VSYNC pacing helpers.
# Python creates an os.pipe(); the write end fd is handed to Swift via an env
# var.  CADisplayLink's tick() writes one byte per display refresh; the Python
# present thread blocks on select() on the read end instead of time.sleep().
# select() releases the GIL, so the app loop thread runs freely while waiting.
# ---------------------------------------------------------------------------

def create_vsync_pipe() -> tuple[int, int] | None:
    """Create a pipe for VSYNC signalling.  Returns (read_fd, write_fd)."""
    try:
        r_fd, w_fd = os.pipe()
        # Non-blocking write so Swift never stalls if the pipe fills up.
        flags = fcntl.fcntl(w_fd, fcntl.F_GETFL)
        fcntl.fcntl(w_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        return (r_fd, w_fd)
    except Exception:
        return None


def destroy_vsync_pipe(read_fd: int, write_fd: int) -> None:
    for fd in (read_fd, write_fd):
        try:
            os.close(fd)
        except OSError:
            pass


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SceneRenderTick:
    event: SceneBlitEvent
    frame: SceneFrame


@dataclass(frozen=True)
class SceneDisplayTelemetry:
    present_attempt_fps: float
    present_success_fps: float
    last_present_ms: float
    frames_presented: int
    last_presented_revision: int
    coalesced_frames: int
    repeat_presents: int
    skipped_inactive: int
    present_attempts: int
    next_drawable_nil: int = 0
    next_drawable_slow: int = 0
    present_commits: int = 0
    app_active: int = 1
    last_error: str = ""
    last_nd_ms_x10: int = 0
    last_enc_ms_x10: int = 0
    last_txt_ms_x10: int = 0
    last_ovl_ms_x10: int = 0
    last_cmt_ms_x10: int = 0


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


class SceneDisplayRuntime:
    def __init__(
        self,
        scene_buffer: SceneGraphBuffer,
        target: SceneRenderTarget,
        *,
        active_provider: Callable[[], bool] | None = None,
        vsync_read_fd: int | None = None,
    ) -> None:
        self._scene_buffer = scene_buffer
        self._target = target
        self._active_provider = active_provider
        self._vsync_read_fd: int | None = vsync_read_fd
        self._last_error: Exception | None = None
        self._last_present_ns = 0
        self._coalesced_frames = 0
        self._frames_presented = 0
        self._last_presented_revision = 0
        self._repeat_presents = 0
        self._skipped_inactive = 0
        self._present_attempts = 0
        self._attempt_rate = _RollingRate()
        self._success_rate = _RollingRate()
        self._present_thread: threading.Thread | None = None
        self._present_stop = threading.Event()

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    @property
    def last_present_ns(self) -> int:
        return int(self._last_present_ns)

    @property
    def coalesced_frames(self) -> int:
        value = int(self._coalesced_frames)
        self._coalesced_frames = 0
        return value

    @property
    def frames_presented(self) -> int:
        return int(self._frames_presented)

    @property
    def last_presented_revision(self) -> int:
        return int(self._last_presented_revision)

    def is_active(self) -> bool:
        if self._active_provider is None:
            return True
        try:
            return bool(self._active_provider())
        except Exception:  # noqa: BLE001
            return True

    def telemetry(self) -> SceneDisplayTelemetry:
        target_telemetry: dict[str, int] = {}
        consumer = getattr(self._target, "consume_telemetry", None)
        if callable(consumer):
            raw = consumer()
            if isinstance(raw, dict):
                for key, value in raw.items():
                    try:
                        target_telemetry[str(key)] = int(value)
                    except (TypeError, ValueError):
                        continue
        return SceneDisplayTelemetry(
            present_attempt_fps=self._attempt_rate.rate,
            present_success_fps=self._success_rate.rate,
            last_present_ms=float(self._last_present_ns) / 1_000_000.0,
            frames_presented=int(self._frames_presented),
            last_presented_revision=int(self._last_presented_revision),
            coalesced_frames=int(self._coalesced_frames),
            repeat_presents=int(self._repeat_presents),
            skipped_inactive=int(self._skipped_inactive),
            present_attempts=int(self._present_attempts),
            next_drawable_nil=int(target_telemetry.get("next_drawable_nil", 0)),
            next_drawable_slow=int(target_telemetry.get("next_drawable_slow", 0)),
            present_commits=int(target_telemetry.get("present_commits", 0)),
            app_active=int(self.is_active()),
            last_error="" if self._last_error is None else repr(self._last_error),
            last_nd_ms_x10=int(target_telemetry.get("last_nd_ms_x10", 0)),
            last_enc_ms_x10=int(target_telemetry.get("last_enc_ms_x10", 0)),
            last_txt_ms_x10=int(target_telemetry.get("last_txt_ms_x10", 0)),
            last_ovl_ms_x10=int(target_telemetry.get("last_ovl_ms_x10", 0)),
            last_cmt_ms_x10=int(target_telemetry.get("last_cmt_ms_x10", 0)),
        )

    def run_once(self, timeout: float | None = None, *, repeat_latest: bool = False) -> SceneRenderTick | None:
        if not self.is_active():
            self._skipped_inactive += 1
            return None
        event = self._scene_buffer.pop_scene_blit(timeout=timeout)
        frame: SceneFrame | None = None
        if event is None and repeat_latest:
            frame = self._scene_buffer.latest_frame()
            if frame is not None:
                event = SceneBlitEvent(
                    event_id=0,
                    revision=frame.revision,
                    ts_ns=time.time_ns(),
                )
                self._repeat_presents += 1
        if event is None:
            return None

        while True:
            newer = self._scene_buffer.pop_scene_blit(timeout=None)
            if newer is None:
                break
            event = newer
            self._coalesced_frames += 1

        if frame is None:
            frame = self._scene_buffer.latest_frame(event.revision)
        if frame is None:
            return None
        self._present_attempts += 1
        self._attempt_rate.mark()
        started = time.perf_counter_ns()
        try:
            self._target.present_scene(frame)
        except Exception as exc:  # noqa: BLE001
            self._last_error = exc
            LOGGER.exception("SceneDisplayRuntime present failed: %s", exc)
            raise
        self._last_present_ns = time.perf_counter_ns() - started
        self._frames_presented += 1
        self._success_rate.mark()
        self._last_presented_revision = int(frame.revision)
        return SceneRenderTick(event=event, frame=frame)

    def start_present_loop(self, *, present_fps: int, repeat_latest: bool = True) -> None:
        if present_fps <= 0:
            raise ValueError("present_fps must be > 0")
        if self._present_thread is not None and self._present_thread.is_alive():
            return
        self._present_stop.clear()
        self._present_thread = threading.Thread(
            target=self._present_loop,
            kwargs={"present_fps": int(present_fps), "repeat_latest": bool(repeat_latest)},
            name="luvatrix-scene-present",
            daemon=True,
        )
        self._present_thread.start()

    def stop_present_loop(self) -> None:
        self._present_stop.set()
        if self._present_thread is not None:
            self._present_thread.join(timeout=1.0)
            self._present_thread = None

    def _present_loop(self, *, present_fps: int, repeat_latest: bool) -> None:
        interval = 1.0 / float(present_fps)
        vsync_fd = self._vsync_read_fd
        next_at = time.perf_counter()
        was_active = self.is_active()
        while not self._present_stop.is_set():
            now = time.perf_counter()
            active = self.is_active()
            if not active:
                self._skipped_inactive += 1
                was_active = False
                next_at = now + interval
                self._present_stop.wait(min(interval, 0.05))
                continue
            if not was_active:
                next_at = now
                was_active = True
            if vsync_fd is not None:
                # VSYNC mode: block on CADisplayLink pipe signal or timeout.
                # select() releases the GIL so the app loop runs freely.
                ready, _, _ = _select.select([vsync_fd], [], [], min(interval, 0.05))
                if self._present_stop.is_set():
                    break
                if ready:
                    # Drain accumulated bytes (one per CADisplayLink tick).
                    # Extra bytes mean we were late; count them as coalesced.
                    try:
                        data = os.read(vsync_fd, 4096)
                        extra = len(data) - 1
                        if extra > 0:
                            self._coalesced_frames += extra
                    except (BlockingIOError, OSError):
                        pass
            else:
                if now < next_at:
                    self._present_stop.wait(next_at - now)
                    continue
                next_at += interval
                if next_at < now - interval:
                    next_at = now + interval
            try:
                self.run_once(timeout=0.0, repeat_latest=repeat_latest)
            except Exception as exc:  # noqa: BLE001
                self._last_error = exc
                self._present_stop.set()
                return
