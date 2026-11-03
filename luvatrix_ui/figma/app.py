from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from luvatrix.app import App

from .document import BackAction, FigmaDocument, Frame, Hotspot, NavigateAction, UrlAction
from .render import FigmaRenderer
from .transitions import Transition

TapHandler = Callable[["FigmaApp", str], Any]
DRAG_THRESHOLD_PT = 6.0


@dataclass
class _Screen:
    """A frame rasterized for one matrix size: scrolling content plus a fixed overlay."""

    scale: float
    offset_x: int
    offset_y: int
    viewport_h: float
    max_scroll: float
    content: np.ndarray
    overlay: np.ndarray | None
    overlay_rows: tuple[int, int]
    letterbox: tuple[int, int, int, int]


@dataclass
class _Press:
    pointer_id: int
    start: tuple[float, float]
    start_scroll: float
    target: Hotspot | None
    dragging: bool = False


class FigmaApp(App):
    """Runs a Figma prototype: renders the current frame and follows tap interactions.

    `design` is a FigmaDocument or a path to a Figma REST JSON export (images and
    fonts are looked up in `images/` and `fonts/` next to it). Frames with
    vertical overflow scroll by drag or wheel while their fixed children stay
    pinned. Tap handlers registered with `on_tap` run before the prototype
    action; returning False suppresses that action.
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
        self.scroll_y = 0.0
        self.history: list[tuple[str, float, dict[str, Any] | None]] = []
        self._background = background
        self._renderer = FigmaRenderer(self.document, font_dirs=font_dirs)
        self._handlers: dict[str, TapHandler] = {}
        self._targets: dict[str, list[Hotspot]] = {}
        self._fixed_bounds: dict[str, list[tuple[float, float, float, float]]] = {}
        self._screens: dict[tuple[str, int, int], _Screen] = {}
        self._press: _Press | None = None
        self._pointer = (0.0, 0.0)
        self._transition: Transition | None = None
        self._last_image: np.ndarray | None = None

    def setup(self) -> None:
        self.set_continuous_render(False)

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def current_frame_name(self) -> str:
        return self.document.frame(self.current_frame_id).name

    def on_tap(self, node_name: str, handler: TapHandler) -> None:
        self._handlers[node_name] = handler
        self._targets.clear()

    def navigate(self, frame: str, transition: dict[str, Any] | None = None) -> None:
        target = self.document.find_frame(frame).id
        if target == self.current_frame_id:
            return
        self.history.append((self.current_frame_id, self.scroll_y, transition))
        self._go(target, 0.0, transition, reverse=False)

    def back(self) -> None:
        if not self.history:
            return
        frame_id, scroll, transition = self.history.pop()
        self._go(frame_id, scroll, transition, reverse=True)

    # ── app loop ─────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        for event in self.input.raw_events():
            self._handle_event(event)
        if self._transition is not None:
            self._transition.advance(dt)
            self.invalidate()

    def render(self) -> None:
        if self._transition is not None:
            image = self._transition.frame()
            if self._transition.done:
                self._transition = None
                self.set_continuous_render(False)
                image = self._compose(self.current_frame_id, self.scroll_y)
        else:
            image = self._compose(self.current_frame_id, self.scroll_y)
        self._last_image = image
        self._submit(image)

    # ── rendering ────────────────────────────────────────────────────────────

    def _matrix_size(self) -> tuple[int, int]:
        snap = self.ctx.read_matrix_snapshot()
        return int(snap.shape[1]), int(snap.shape[0])

    def _screen(self, frame_id: str) -> _Screen:
        width, height = self._matrix_size()
        key = (frame_id, width, height)
        screen = self._screens.get(key)
        if screen is not None:
            return screen
        frame = self.document.frame(frame_id)
        fit_width = width / frame.width
        scrolls = frame.scrolls_vertically and frame.height * fit_width > height + 0.5
        scale = fit_width if scrolls else min(fit_width, height / frame.height)
        fixed = self.document.fixed_child_ids(frame_id) if scrolls else set()
        content = self._renderer.render(frame_id, scale, skip_ids=fixed)
        overlay = None
        rows = (0, 0)
        if fixed:
            overlay = self._renderer.render(frame_id, scale, only_ids=fixed, transparent=True)
            visible = np.nonzero(overlay[..., 3].any(axis=1))[0]
            rows = (int(visible.min()), int(visible.max()) + 1) if len(visible) else (0, 0)
        dh, dw = content.shape[:2]
        viewport_h = height / scale
        screen = _Screen(
            scale=scale,
            offset_x=(width - dw) // 2,
            offset_y=0 if scrolls else (height - dh) // 2,
            viewport_h=viewport_h,
            max_scroll=max(0.0, frame.height - viewport_h) if scrolls else 0.0,
            content=content,
            overlay=overlay,
            overlay_rows=rows,
            letterbox=self._letterbox_color(frame),
        )
        self._screens[key] = screen
        return screen

    def _compose(self, frame_id: str, scroll: float) -> np.ndarray:
        width, height = self._matrix_size()
        screen = self._screen(frame_id)
        image = np.empty((height, width, 4), dtype=np.uint8)
        image[...] = np.asarray(screen.letterbox, dtype=np.uint8)
        top = int(round(scroll * screen.scale))
        content = screen.content[top : top + height]
        ch, cw = content.shape[:2]
        image[screen.offset_y : screen.offset_y + ch, screen.offset_x : screen.offset_x + cw] = content
        if screen.overlay is not None:
            r0, r1 = screen.overlay_rows
            r1 = min(r1, height - screen.offset_y)
            if r1 > r0:
                src = screen.overlay[r0:r1].astype(np.float32)
                region = image[screen.offset_y + r0 : screen.offset_y + r1, screen.offset_x : screen.offset_x + cw]
                alpha = src[..., 3:4] / 255.0
                mixed = src[..., :3] * alpha + region[..., :3].astype(np.float32) * (1 - alpha)
                region[..., :3] = np.rint(mixed).astype(np.uint8)
        return image

    def _letterbox_color(self, frame: Frame) -> tuple[int, int, int, int]:
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

    # ── navigation ───────────────────────────────────────────────────────────

    def _go(self, frame_id: str, scroll: float, transition: dict[str, Any] | None, *, reverse: bool) -> None:
        source = self._last_image
        self.current_frame_id = frame_id
        self.scroll_y = scroll
        self._press = None
        if not hasattr(self, "ctx"):
            return
        self._transition = None
        if source is not None and transition:
            target = self._compose(frame_id, scroll)
            if target.shape == source.shape:
                self._transition = Transition.from_figma(transition, source, target, reverse=reverse)
        if self._transition is not None:
            self.set_continuous_render(True)
        self.invalidate()

    def _activate(self, spot: Hotspot) -> None:
        handler = self._handlers.get(spot.node_name)
        if handler is not None and handler(self, spot.node_name) is False:
            return
        action = spot.action
        if isinstance(action, NavigateAction):
            self.navigate(action.destination_id, action.transition)
        elif isinstance(action, BackAction):
            self.back()
        elif isinstance(action, UrlAction):
            print(f"[figma] open URL requested: {action.url}")

    # ── input ────────────────────────────────────────────────────────────────

    def _display_to_matrix(self) -> tuple[float, float]:
        width, height = self._matrix_size()
        display_w = float(getattr(self.ctx, "display_width_px", 0) or width)
        display_h = float(getattr(self.ctx, "display_height_px", 0) or height)
        return width / display_w, height / display_h

    def _to_view(self, x: float, y: float) -> tuple[float, float]:
        """Display point -> design units within the viewport (before scrolling)."""
        kx, ky = self._display_to_matrix()
        screen = self._screen(self.current_frame_id)
        return (x * kx - screen.offset_x) / screen.scale, (y * ky - screen.offset_y) / screen.scale

    def _scroll_to(self, value: float) -> None:
        screen = self._screen(self.current_frame_id)
        clamped = min(max(0.0, value), screen.max_scroll)
        if clamped != self.scroll_y:
            self.scroll_y = clamped
            self.invalidate()

    def _handle_event(self, event: Any) -> None:
        if getattr(event, "status", "OK") != "OK":
            return
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return
        device, kind = getattr(event, "device", None), getattr(event, "event_type", None)
        if "x" in payload and "y" in payload:
            self._pointer = (float(payload["x"]), float(payload["y"]))
        if device in {"mouse", "trackpad"} and kind == "scroll":
            _, ky = self._display_to_matrix()
            self._scroll_to(self.scroll_y - float(payload.get("delta_y", 0.0) or 0.0) * ky / self._screen(self.current_frame_id).scale)
            return
        if device == "touch" and kind == "touch":
            pointer_id, phase = int(payload.get("touch_id", 0)), str(payload.get("phase", ""))
        elif device in {"mouse", "trackpad"} and kind == "click" and int(payload.get("button", 0)) == 0:
            pointer_id, phase = -1, str(payload.get("phase", ""))
        elif device in {"mouse", "trackpad"} and kind == "pointer_move" and self._press is not None:
            pointer_id, phase = -1, "move"
        else:
            return
        self._pointer_phase(pointer_id, phase)

    def _pointer_phase(self, pointer_id: int, phase: str) -> None:
        if self._transition is not None:
            return
        press = self._press
        if phase == "down":
            self._press = _Press(pointer_id, self._pointer, self.scroll_y, self._hit(*self._to_view(*self._pointer)))
            return
        if press is None or press.pointer_id != pointer_id:
            return
        dx, dy = self._pointer[0] - press.start[0], self._pointer[1] - press.start[1]
        if not press.dragging and max(abs(dx), abs(dy)) > DRAG_THRESHOLD_PT:
            press.dragging = True
        if press.dragging:
            _, ky = self._display_to_matrix()
            self._scroll_to(press.start_scroll - dy * ky / self._screen(self.current_frame_id).scale)
        if phase == "cancel":
            self._press = None
        elif phase == "up":
            self._press = None
            if press.dragging or press.target is None:
                return
            released = self._hit(*self._to_view(*self._pointer))
            if released is not None and released.node_id == press.target.node_id:
                self._activate(released)

    def _hit(self, vx: float, vy: float) -> Hotspot | None:
        targets = self._tap_targets()
        scrolling = self._screen(self.current_frame_id).max_scroll > 0
        if scrolling and any(x0 <= vx <= x1 and y0 <= vy <= y1 for x0, y0, x1, y1 in self._fixed_regions()):
            return next((t for t in reversed(targets) if t.fixed and t.contains(vx, vy)), None)
        y = vy + self.scroll_y
        return next((t for t in reversed(targets) if not (scrolling and t.fixed) and t.contains(vx, y)), None)

    def _fixed_regions(self) -> list[tuple[float, float, float, float]]:
        frame_id = self.current_frame_id
        if frame_id not in self._fixed_bounds:
            ids = self.document.fixed_child_ids(frame_id)
            self._fixed_bounds[frame_id] = list(self.document.node_bounds(frame_id, ids).values())
        return self._fixed_bounds[frame_id]

    def _tap_targets(self) -> list[Hotspot]:
        cached = self._targets.get(self.current_frame_id)
        if cached is None:
            cached = self.document.targets(self.current_frame_id, frozenset(self._handlers))
            self._targets[self.current_frame_id] = cached
        return cached
