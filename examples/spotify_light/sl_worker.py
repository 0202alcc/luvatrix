"""Single background worker thread with a result queue.

The render loop never blocks on network: jobs are submitted with a label,
executed FIFO on one daemon thread, and drained on the next ``update()`` tick
via ``poll()``. Exceptions are captured as results so a failed fetch can
surface as UI state instead of crashing the app loop.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable


class Worker:
    def __init__(self) -> None:
        self._jobs: queue.Queue[tuple[str, Callable[[], Any]]] = queue.Queue()
        self._results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="spotify-light-worker", daemon=True)
        self._thread.start()

    def submit(self, label: str, fn: Callable[[], Any]) -> None:
        if self._closed:
            return
        self._jobs.put((label, fn))

    def poll(self) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        while True:
            try:
                out.append(self._results.get_nowait())
            except queue.Empty:
                return out

    def shutdown(self) -> None:
        self._closed = True
        # Unblock the worker loop so the thread can exit promptly.
        self._jobs.put(("__shutdown__", lambda: None))
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._closed:
            try:
                label, fn = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if label == "__shutdown__":
                return
            try:
                result = fn()
            except Exception as exc:  # surfaced to the UI as data
                result = exc
            self._results.put((label, result))
