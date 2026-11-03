from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from luvatrix.app import App

from .document import BackAction, FigmaDocument, Hotspot, NavigateAction, UrlAction, node_size, walk
from .render import FigmaRenderer

TapHandler = Callable[["FigmaApp", str], Any]


class FigmaApp(App):
    """Runs a Figma prototype: renders the current frame and follows tap interactions.

    `design` is a FigmaDocument or a path to a Figma REST JSON export (images and
    fonts are looked up in `images/` and `fonts/` next to it). Tap handlers
    registered with `on_tap` run before the prototype action; returning False
    suppresses that action.
    """

    def __init__(
        self,
        design: FigmaDocument | str | Path,
        *,
        start: str | None = None,
        background: tuple[int, int, int, int] | None = None,
        font_dirs: tuple[str, ...] = (),
    ) -> None:
        self.document = design if isinstance(design, FigmaDocument) else FigmaDocument.load(design, start=start)
        self.current_frame_id = self.document.find_frame(start).id if start else self.document.start_frame_id
        self.history: list[str] = []
        self._background = background
        self._renderer = FigmaRenderer(self.document, font_dirs=font_dirs)
        self._handlers: dict[str, TapHandler] = {}
        self._targets: dict[str, list[Hotspot]] = {}
        self._cache: dict[tuple[str, int, int], np.ndarray] = {}
        self._layout: tuple[float, float, float] = (1.0, 0.0, 0.0)
        self._press: tuple[int, Hotspot | None] | None = None
        self._pointer = (0.0, 0.0)

    def setup(self) -> None:
        self.set_continuous_render(False)

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def current_frame_name(self) -> str:
        return self.document.frame(self.current_frame_id).name

    def on_tap(self, node_name: str, handler: TapHandler) -> None:
        self._handlers[node_name] = handler
        self._targets.clear()

    def navigate(self, frame: str) -> None:
        target = self.document.find_frame(frame).id
        if target != self.current_frame_id:
            self.history.append(self.current_frame_id)
            self.current_frame_id = target
        self._request_render()

    def back(self) -> None:
        if self.history:
            self.current_frame_id = self.history.pop()
            self._request_render()

    # ── app loop ─────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        _ = dt
        for event in self.input.raw_events():
            self._handle_event(event)

    def render(self) -> None:
        snap = self.ctx.read_matrix_snapshot()
        height, width = int(snap.shape[0]), int(snap.shape[1])
        frame = self.document.frame(self.current_frame_id)
        scale = min(width / frame.width, height / frame.height)
        key = (self.current_frame_id, width, height)
        image = self._cache.get(key)
        if image is None:
            design = self._renderer.render(self.current_frame_id, scale)
            image = np.empty((height, width, 4), dtype=np.uint8)
            image[...] = np.asarray(self._letterbox_color(frame), dtype=np.uint8)
            dh, dw = design.shape[:2]
            ox, oy = (width - dw) // 2, (height - dh) // 2
            image[oy : oy + dh, ox : ox + dw] = design
            self._cache[key] = image
        dh, dw = int(round(frame.height * scale)), int(round(frame.width * scale))
        self._layout = (scale, float((width - dw) // 2), float((height - dh) // 2))
        self._submit(image.copy())

    # ── internals ────────────────────────────────────────────────────────────

    def _request_render(self) -> None:
        if hasattr(self, "ctx"):
            self.invalidate()

    def _letterbox_color(self, frame: Any) -> tuple[int, int, int, int]:
        if self._background is not None:
            return tuple(int(c) for c in self._background)  # type: ignore[return-value]
        for paint in frame.node.get("fills") or ():
            if paint.get("type") == "SOLID" and paint.get("visible", True) is not False:
                c = paint.get("color") or {}
                return (int(round(c.get("r", 0) * 255)), int(round(c.get("g", 0) * 255)), int(round(c.get("b", 0) * 255)), 255)
        return (0, 0, 0, 255)

    def _submit(self, image: np.ndarray) -> None:
        from luvatrix_core import accel
        from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch

        tensor: Any = image
        if accel.BACKEND == "torch":
            import torch

            tensor = torch.from_numpy(image)
        self.ctx.submit_write_batch(WriteBatch([FullRewrite(tensor, take_ownership=True)]))

    def _to_design(self, x: float, y: float) -> tuple[float, float]:
        snap_w = getattr(self.ctx, "display_width_px", None)
        snap = self.ctx.read_matrix_snapshot()
        matrix_h, matrix_w = int(snap.shape[0]), int(snap.shape[1])
        display_w = float(snap_w or matrix_w) or float(matrix_w)
        display_h = float(getattr(self.ctx, "display_height_px", None) or matrix_h) or float(matrix_h)
        px, py = x * matrix_w / display_w, y * matrix_h / display_h
        scale, ox, oy = self._layout
        return (px - ox) / scale, (py - oy) / scale

    def _handle_event(self, event: Any) -> None:
        if getattr(event, "status", "OK") != "OK":
            return
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return
        device, kind = getattr(event, "device", None), getattr(event, "event_type", None)
        if "x" in payload and "y" in payload:
            self._pointer = (float(payload["x"]), float(payload["y"]))
        if device == "touch" and kind == "touch":
            pointer_id, phase = int(payload.get("touch_id", 0)), str(payload.get("phase", ""))
        elif device in {"mouse", "trackpad"} and kind == "click" and int(payload.get("button", 0)) == 0:
            pointer_id, phase = -1, str(payload.get("phase", ""))
        else:
            return
        x, y = self._to_design(*self._pointer)
        if phase == "down":
            self._press = (pointer_id, self._hit(x, y))
        elif phase == "cancel":
            self._press = None
        elif phase == "up" and self._press is not None and self._press[0] == pointer_id:
            pressed = self._press[1]
            self._press = None
            released = self._hit(x, y)
            if pressed is not None and released is not None and pressed.node_id == released.node_id:
                self._activate(released)

    def _hit(self, x: float, y: float) -> Hotspot | None:
        for spot in reversed(self._tap_targets()):
            if spot.contains(x, y):
                return spot
        return None

    def _tap_targets(self) -> list[Hotspot]:
        cached = self._targets.get(self.current_frame_id)
        if cached is not None:
            return cached
        spots = {spot.node_id: spot for spot in self.document.hotspots(self.current_frame_id)}
        targets: list[Hotspot] = []
        frame = self.document.frame(self.current_frame_id)
        for node, tf in walk(frame):
            node_id = str(node.get("id", ""))
            if node_id in spots:
                targets.append(spots[node_id])
            elif str(node.get("name", "")) in self._handlers:
                w, h = node_size(node)
                x0, y0, x1, y1 = tf.bounds(0.0, 0.0, w, h)
                targets.append(Hotspot(node_id, str(node.get("name", "")), x0, y0, x1 - x0, y1 - y0, None))
        self._targets[self.current_frame_id] = targets
        return targets

    def _activate(self, spot: Hotspot) -> None:
        handler = self._handlers.get(spot.node_name)
        if handler is not None and handler(self, spot.node_name) is False:
            return
        action = spot.action
        if isinstance(action, NavigateAction):
            self.navigate(action.destination_id)
        elif isinstance(action, BackAction):
            self.back()
        elif isinstance(action, UrlAction):
            print(f"[figma] open URL requested: {action.url}")
