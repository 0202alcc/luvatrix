from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
import threading
import time
from typing import Any


@dataclass(frozen=True)
class _WorkItem:
    key: Hashable
    prepare: Callable[[], Any]
    on_complete: Callable[[Any], None] | None


class InteractionAwareWorkScheduler:
    """Run keyed preparation work only while user interaction is idle.

    Work and callbacks execute sequentially on one daemon thread. Running work
    is not preempted when interaction begins; the idle gate prevents queued
    work from starting until ``interaction_active`` returns false.

    Pair with ``SwipeMomentumController`` using
    ``interaction_active=lambda: swipe.active`` and call
    :meth:`notify_interaction_state_changed` after controller updates to wake
    queued work immediately when momentum stops.
    """

    def __init__(
        self,
        *,
        interaction_active: Callable[[], bool],
        request_render: Callable[[], None] | None = None,
        on_error: Callable[[Hashable, Exception], None] | None = None,
        idle_poll_interval: float = 1.0 / 120.0,
        thread_name: str = "luvatrix-interaction-work",
    ) -> None:
        self.interaction_active = interaction_active
        self.request_render = request_render
        self.on_error = on_error
        self.idle_poll_interval = max(0.001, float(idle_poll_interval))
        self.thread_name = str(thread_name)
        self._condition = threading.Condition()
        self._pending: deque[_WorkItem] = deque()
        self._keys: set[Hashable] = set()
        self._thread: threading.Thread | None = None
        self._closed = False

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._keys)

    def submit(
        self,
        key: Hashable,
        prepare: Callable[[], Any],
        *,
        on_complete: Callable[[Any], None] | None = None,
    ) -> bool:
        """Queue work unless the key is already queued or running."""
        with self._condition:
            if self._closed:
                raise RuntimeError("interaction-aware work scheduler is closed")
            if key in self._keys:
                return False
            self._keys.add(key)
            self._pending.append(_WorkItem(key, prepare, on_complete))
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name=self.thread_name,
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()
            return True

    def notify_interaction_state_changed(self) -> None:
        """Wake idle-gated work after a controller state update."""
        with self._condition:
            self._condition.notify_all()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait until queued/running work and its callbacks have completed."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._keys:
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, *, wait: bool = False) -> None:
        """Cancel queued work and optionally wait for running work to finish."""
        with self._condition:
            self._closed = True
            while self._pending:
                self._keys.discard(self._pending.popleft().key)
            thread = self._thread
            self._condition.notify_all()
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._closed and not self._pending:
                    self._condition.wait()
                if self._closed:
                    return
                pending_key = self._pending[0].key

            try:
                interaction_active = bool(self.interaction_active())
            except Exception as exc:
                self._report_error(pending_key, exc)
                interaction_active = False

            with self._condition:
                if self._closed:
                    return
                if not self._pending:
                    continue
                if interaction_active:
                    self._condition.wait(self.idle_poll_interval)
                    continue
                item = self._pending.popleft()

            try:
                value = item.prepare()
            except Exception as exc:
                self._report_error(item.key, exc)
            else:
                if item.on_complete is not None:
                    try:
                        item.on_complete(value)
                    except Exception as exc:
                        self._report_error(item.key, exc)
            try:
                if self.request_render is not None:
                    self.request_render()
            except Exception as exc:
                self._report_error(item.key, exc)
            finally:
                with self._condition:
                    self._keys.discard(item.key)
                    self._condition.notify_all()

    def _report_error(self, key: Hashable, error: Exception) -> None:
        if self.on_error is None:
            return
        try:
            self.on_error(key, error)
        except Exception:
            return
