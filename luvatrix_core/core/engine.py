from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import queue
import threading
import time
from typing import Optional

from .events import InputEvent
from luvatrix_core.render.framebuffer import FrameBuffer
from luvatrix_core.render.svg import SvgDocument
from luvatrix_core.ui.element import Element
from luvatrix_core.ui.page_loader import Page


@dataclass
class FrameSnapshot:
    frame_id: int
    width: int
    height: int
    data: bytes


class Engine:
    def __init__(self, page: Page, fps: int = 30) -> None:
        self.page = page
        self.fps = fps
        self.framebuffer = FrameBuffer(page.width, page.height, background=page.background)
        self._lock = threading.Lock()
        self._frame_id = 0
        self._frame_bytes = b""
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._input_queue: "queue.SimpleQueue[InputEvent]" = queue.SimpleQueue()
        self._svg_cache: dict[Path, SvgDocument] = {}
        self._start_time = time.perf_counter()
        self._time = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="luvatrix-main", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=1.0)

    def push_input(self, event: InputEvent) -> None:
        self._input_queue.put(event)

    def get_frame(self) -> FrameSnapshot:
        with self._lock:
            return FrameSnapshot(
                frame_id=self._frame_id,
                width=self.page.width,
                height=self.page.height,
                data=self._frame_bytes,
            )

    def _run(self) -> None:
        target_dt = 1.0 / max(1, self.fps)
        last = time.perf_counter()
        while self._running.is_set():
            now = time.perf_counter()
            dt = now - last
            last = now
            self._time += dt
            self._drain_inputs()
            self._render()
            elapsed = time.perf_counter() - now
            sleep_for = target_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def _drain_inputs(self) -> None:
        while True:
            try:
                _ = self._input_queue.get_nowait()
            except queue.Empty:
                break

    def _render(self) -> None:
        fb = self.framebuffer
        fb.clear(self.page.background)
        for element in self.page.elements:
            self._render_element(fb, element)
        frame_bytes = fb.to_bytes()
        with self._lock:
            self._frame_id += 1
            self._frame_bytes = frame_bytes

    def _render_element(self, fb: FrameBuffer, element: Element) -> None:
        doc = self._svg_cache.get(element.svg_path)
        if doc is None:
            doc = SvgDocument.from_file(element.svg_path)
            self._svg_cache[element.svg_path] = doc
        x = element.x
        y = element.y
        scale = element.scale
        opacity = element.opacity
        if element.animation:
            anim_type = element.animation.get("type")
            if anim_type == "float":
                amp = float(element.animation.get("amp", 6.0))
                speed = float(element.animation.get("speed", 1.0))
                y += (amp * (0.5 + 0.5 * math.sin(self._time * speed)))
        doc.render(fb, x, y, scale, opacity)
