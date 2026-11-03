from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from luvatrix.app import App

from .document import (
    BackAction,
    FigmaDocument,
    Frame,
    Hotspot,
    NavigateAction,
    OverlayAction,
    UrlAction,
    VariantAction,
)
from .render import FigmaRenderer
from .smart_animate import layer_geometry, match_layers, walk_with_parent
from .tour import Tour
from .transitions import SmartAnimateTransition, Transition, TweenLayer

TapHandler = Callable[["FigmaApp", str], Any]
DRAG_THRESHOLD_PT = 6.0
_SCRIPTED_POINTER = -2
DEFAULT_SCRIM = (0.0, 0.0, 0.0, 0.4)


@dataclass
class _Screen:
    """A frame rasterized for one matrix size: scrolling content plus a fixed overlay."""

    scale: float
    offset_x: int
    offset_y: int
    viewport_h: float
    viewport_w: float
    max_scroll: float
    max_scroll_x: float
    content: np.ndarray
    overlay: np.ndarray | None
    overlay_window: tuple[int, int, int, int]
    letterbox: tuple[int, int, int, int]


@dataclass
class _Overlay:
    """An open modal layer over the base frame."""

    frame_id: str
    position: str
    background: tuple[float, float, float, float] | None
    dismiss_on_click_outside: bool
    scroll_y: float = 0.0


@dataclass
class _OverlaySurface:
    """The overlay frame rasterized and placed for one matrix size."""

    scale: float
    origin_x: int
    origin_y: int
    box_w: int
    box_h: int
    content: np.ndarray
    max_scroll: float


@dataclass
class _Press:
    pointer_id: int
    start: tuple[float, float]
    start_scroll: float
    target: Hotspot | None
    start_scroll_x: float = 0.0
    overlay: int = -1
    outside: bool = False
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
        self.scroll_x = 0.0
        self.history: list[tuple[str, float, float, dict[str, Any] | None]] = []
        self._background = background
        self._variant_overrides: dict[str, str] = {}
        self._renderer = FigmaRenderer(self.document, font_dirs=font_dirs, variant_overrides=self._variant_overrides)
        self._handlers: dict[str, TapHandler] = {}
        self._targets: dict[str, list[Hotspot]] = {}
        self._fixed_bounds: dict[str, list[tuple[float, float, float, float]]] = {}
        self._screens: dict[tuple[str, int, int], _Screen] = {}
        self._overlays: list[_Overlay] = []
        self._overlay_cache: dict[tuple[str, int, int], _OverlaySurface] = {}
        self._press: _Press | None = None
        self._pointer = (0.0, 0.0)
        self._transition: Transition | None = None
        self._last_image: np.ndarray | None = None
        self._tour: Tour | None = None

    def setup(self) -> None:
        self.set_continuous_render(False)
        self._tour = Tour.from_env()

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def current_frame_name(self) -> str:
        return self.document.frame(self.current_frame_id).name

    @property
    def overlay_frame_name(self) -> str | None:
        """Name of the topmost open overlay frame, or None when none is open."""
        return self.document.frame(self._overlays[-1].frame_id).name if self._overlays else None

    @property
    def overlay_scroll_y(self) -> float:
        return self._overlays[-1].scroll_y if self._overlays else 0.0

    @property
    def busy(self) -> bool:
        """True while a transition plays or the latest state has not been rendered yet."""
        return self._transition is not None or self._render_requested

    def on_tap(self, node_name: str, handler: TapHandler) -> None:
        self._handlers[node_name] = handler
        self._targets.clear()

    def navigate(self, frame: str, transition: dict[str, Any] | None = None) -> None:
        target = self.document.find_frame(frame).id
        if target == self.current_frame_id:
            return
        self._overlays.clear()
        self.history.append((self.current_frame_id, self.scroll_y, self.scroll_x, transition))
        self._go(target, 0.0, 0.0, transition, reverse=False)

    def open_overlay(
        self,
        frame: str,
        *,
        position: str = "CENTER",
        background: tuple[float, float, float, float] | None = None,
        dismiss_on_click_outside: bool = False,
    ) -> None:
        """Open `frame` as a modal layer over the current screen without navigating."""
        self._overlays.append(
            _Overlay(
                self.document.find_frame(frame).id,
                str(position).upper(),
                background,
                dismiss_on_click_outside,
            )
        )
        self._press = None
        self.invalidate()

    def close_overlay(self) -> bool:
        """Dismiss the topmost overlay; returns True when one was open."""
        if not self._overlays:
            return False
        self._overlays.pop()
        self._press = None
        self.invalidate()
        return True

    def switch_variant(self, variant_id: str, instance_id: str | None = None) -> bool:
        """Render an instance (or every instance) of the variant's set as that variant."""
        set_id = self.document.component_set_of(variant_id)
        if set_id is None:
            return False
        instances = self.document.instances_of_set(self.current_frame_id, set_id)
        if instance_id is not None:
            instances = [i for i in instances if str(i.get("id", "")) == instance_id]
        if not instances:
            return False
        for instance in instances:
            self._variant_overrides[str(instance.get("id", ""))] = variant_id
        for key in [k for k in self._screens if k[0] == self.current_frame_id]:
            del self._screens[key]
        self._press = None
        self.invalidate()
        return True

    def back(self) -> None:
        if self._overlays:
            self.close_overlay()
            return
        if not self.history:
            return
        frame_id, scroll, scroll_x, transition = self.history.pop()
        self._go(frame_id, scroll, scroll_x, transition, reverse=True)

    def tap(self, node: str) -> None:
        """Tap the center of a tappable layer (by name or id) through normal hit testing.

        A layer outside the viewport is scrolled into view first. While an
        overlay is open only its own layers are tappable. Raises KeyError when
        there is no visible tappable layer with that name on the active surface.
        """
        if self._overlays:
            overlay = self._overlays[-1]
            spot = next(
                (t for t in reversed(self._tap_targets(overlay.frame_id)) if node in (t.node_name, t.node_id)), None
            )
            if spot is None:
                raise KeyError(node)
            surface = self._overlay_surface(overlay)
            cx, cy = spot.x + spot.width / 2, spot.y + spot.height / 2
            viewport_h = surface.box_h / surface.scale
            if not (0.0 <= cy - overlay.scroll_y and cy - overlay.scroll_y <= viewport_h):
                overlay.scroll_y = min(max(0.0, cy - viewport_h / 2), surface.max_scroll)
                self.invalidate()
            vy = cy - overlay.scroll_y
            kx, ky = self._display_to_matrix()
            self._pointer = (
                (cx * surface.scale + surface.origin_x) / kx,
                (vy * surface.scale + surface.origin_y) / ky,
            )
            self._pointer_phase(_SCRIPTED_POINTER, "down")
            self._pointer_phase(_SCRIPTED_POINTER, "up")
            return
        spot = next((t for t in reversed(self._tap_targets()) if node in (t.node_name, t.node_id)), None)
        if spot is None:
            raise KeyError(node)
        screen = self._screen(self.current_frame_id)
        cx, cy = spot.x + spot.width / 2, spot.y + spot.height / 2
        pinned = spot.fixed and (screen.max_scroll > 0 or screen.max_scroll_x > 0)
        if not pinned:
            if not (spot.y >= self.scroll_y and spot.y + spot.height <= self.scroll_y + screen.viewport_h):
                self._scroll_to(cy - screen.viewport_h / 2)
            if not (spot.x >= self.scroll_x and spot.x + spot.width <= self.scroll_x + screen.viewport_w):
                self._scroll_to(self.scroll_y, cx - screen.viewport_w / 2)
        vx = cx if pinned and screen.max_scroll_x > 0 else cx - self.scroll_x
        vy = cy if pinned and screen.max_scroll > 0 else cy - self.scroll_y
        kx, ky = self._display_to_matrix()
        self._pointer = ((vx * screen.scale + screen.offset_x) / kx, (vy * screen.scale + screen.offset_y) / ky)
        self._pointer_phase(_SCRIPTED_POINTER, "down")
        self._pointer_phase(_SCRIPTED_POINTER, "up")

    def scroll_by(self, dy: float, dx: float = 0.0) -> None:
        """Scroll the current frame by `dy`/`dx` design units, clamped to its content."""
        self._scroll_to(self.scroll_y + dy, self.scroll_x + dx)

    def text(self, node: str) -> str:
        return str(self._text_nodes(node)[0].get("characters", ""))

    def set_text(self, node: str, text: str) -> None:
        """Replace the characters of every TEXT layer with this name (or id) and re-render."""
        nodes = self._text_nodes(node)
        for target in nodes:
            target["characters"] = str(text)
            target["characterStyleOverrides"] = []
            owner = self.document.owner_frame_id(str(target.get("id", "")))
            for key in [k for k in self._screens if k[0] == owner]:
                del self._screens[key]
        self.invalidate()

    def _text_nodes(self, key: str) -> list[dict[str, Any]]:
        nodes = self.document.find_nodes(key, node_type="TEXT")
        if not nodes:
            raise KeyError(key)
        return nodes

    # ── app loop ─────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        for event in self.input.raw_events():
            self._handle_event(event)
        if self._transition is not None:
            self._transition.advance(dt)
            self.invalidate()
        if self._tour is not None:
            self._tour.tick(self, dt)

    def render(self) -> None:
        if self._transition is not None:
            image = self._transition.frame()
            if self._transition.done:
                self._transition.restore()
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

    def _screen(self, frame_id: str, skip_ids: frozenset[str] = frozenset()) -> _Screen:
        width, height = self._matrix_size()
        key = (frame_id, width, height, tuple(sorted(skip_ids)))
        screen = self._screens.get(key)
        if screen is not None:
            return screen
        frame = self.document.frame(frame_id)
        fit_width = width / frame.width
        fit_height = height / frame.height
        scrolls_v = frame.scrolls_vertically and frame.height * fit_width > height + 0.5
        scrolls_h = frame.scrolls_horizontally and frame.width * fit_height > width + 0.5
        if scrolls_v:
            scale = fit_width
        elif scrolls_h:
            scale = fit_height
        else:
            scale = min(fit_width, fit_height)
        scrolls = scrolls_v or scrolls_h
        fixed = self.document.fixed_child_ids(frame_id) if scrolls else set()
        content = self._renderer.render(frame_id, scale, skip_ids=fixed | skip_ids)
        overlay = None
        window = (0, 0, 0, 0)
        if fixed:
            overlay = self._renderer.render(frame_id, scale, only_ids=fixed, transparent=True)
            rows = np.nonzero(overlay[..., 3].any(axis=1))[0]
            cols = np.nonzero(overlay[..., 3].any(axis=0))[0]
            r = (int(rows.min()), int(rows.max()) + 1) if len(rows) else (0, 0)
            c = (int(cols.min()), int(cols.max()) + 1) if len(cols) else (0, 0)
            window = (r[0], r[1], c[0], c[1])
        dh, dw = content.shape[:2]
        viewport_h = height / scale
        viewport_w = width / scale
        screen = _Screen(
            scale=scale,
            offset_x=0 if scrolls_h else (width - dw) // 2,
            offset_y=0 if scrolls_v else (height - dh) // 2,
            viewport_h=viewport_h,
            viewport_w=viewport_w,
            max_scroll=max(0.0, frame.height - viewport_h) if scrolls_v else 0.0,
            max_scroll_x=max(0.0, frame.width - viewport_w) if scrolls_h else 0.0,
            content=content,
            overlay=overlay,
            overlay_window=window,
            letterbox=self._letterbox_color(frame),
        )
        self._screens[key] = screen
        return screen

    def _compose(self, frame_id: str, scroll: float, *, skip_ids: frozenset[str] = frozenset()) -> np.ndarray:
        width, height = self._matrix_size()
        screen = self._screen(frame_id, skip_ids)
        image = np.empty((height, width, 4), dtype=np.uint8)
        image[...] = np.asarray(screen.letterbox, dtype=np.uint8)
        top = int(round(self.scroll_y * screen.scale))
        left = int(round(self.scroll_x * screen.scale))
        content = screen.content[top : top + height, left : left + width]
        ch, cw = content.shape[:2]
        image[screen.offset_y : screen.offset_y + ch, screen.offset_x : screen.offset_x + cw] = content
        if screen.overlay is not None:
            r0, r1, c0, c1 = screen.overlay_window
            r1 = min(r1, height - screen.offset_y)
            c1 = min(c1, width - screen.offset_x)
            if r1 > r0 and c1 > c0:
                src = screen.overlay[r0:r1, c0:c1].astype(np.float32)
                region = image[screen.offset_y + r0 : screen.offset_y + r1, screen.offset_x + c0 : screen.offset_x + c1]
                alpha = src[..., 3:4] / 255.0
                mixed = src[..., :3] * alpha + region[..., :3].astype(np.float32) * (1 - alpha)
                region[..., :3] = np.rint(mixed).astype(np.uint8)
        for overlay in self._overlays:
            surface = self._overlay_surface(overlay)
            self._draw_scrim(image, overlay.background or DEFAULT_SCRIM)
            top = int(round(overlay.scroll_y * surface.scale))
            region = surface.content[top : top + surface.box_h]
            rh, rw = region.shape[:2]
            dst = image[surface.origin_y : surface.origin_y + rh, surface.origin_x : surface.origin_x + rw]
            alpha = region[..., 3:4].astype(np.float32) / 255.0
            mixed = region[..., :3].astype(np.float32) * alpha + dst[..., :3].astype(np.float32) * (1 - alpha)
            dst[..., :3] = np.rint(mixed).astype(np.uint8)
            dst[..., 3:4] = 255
        return image

    def _draw_scrim(self, image: np.ndarray, scrim: tuple[float, float, float, float]) -> None:
        r, g, b, a = scrim
        if a <= 0.0:
            return
        tint = np.array([r * 255.0, g * 255.0, b * 255.0], dtype=np.float32)
        image[..., :3] = np.rint(image[..., :3].astype(np.float32) * (1.0 - a) + tint * a).astype(np.uint8)

    def _overlay_surface(self, overlay: _Overlay) -> _OverlaySurface:
        base_scale = self._screen(self.current_frame_id).scale
        key = (overlay.frame_id, *self._matrix_size(), round(base_scale, 4))
        surface = self._overlay_cache.get(key)
        if surface is not None:
            return surface
        frame = self.document.frame(overlay.frame_id)
        width, height = self._matrix_size()
        # Overlays render at the prototype scale of the screen beneath them and
        # scroll when taller than the viewport, like Figma's modal sheets.
        scale = min(base_scale, width / frame.width)
        content = self._renderer.render(overlay.frame_id, scale, transparent=True)
        dh, dw = content.shape[:2]
        box_w, box_h = min(dw, width), min(dh, height)
        origin_x, origin_y = self._overlay_origin(overlay.position, box_w, box_h, width, height)
        surface = _OverlaySurface(
            scale=scale,
            origin_x=origin_x,
            origin_y=origin_y,
            box_w=box_w,
            box_h=box_h,
            content=content,
            max_scroll=max(0.0, (dh - box_h) / scale),
        )
        self._overlay_cache[key] = surface
        return surface

    def _overlay_origin(self, position: str, box_w: int, box_h: int, width: int, height: int) -> tuple[int, int]:
        corners = {
            "TOP_LEFT": (0, 0),
            "TOP_RIGHT": (width - box_w, 0),
            "BOTTOM_LEFT": (0, height - box_h),
            "BOTTOM_RIGHT": (width - box_w, height - box_h),
        }
        return corners.get(position, ((width - box_w) // 2, (height - box_h) // 2))

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

    def _go(self, frame_id: str, scroll: float, scroll_x: float, transition: dict[str, Any] | None, *, reverse: bool) -> None:
        source_frame_id = self.current_frame_id
        source = self._last_image
        self.current_frame_id = frame_id
        self.scroll_y = scroll
        self.scroll_x = scroll_x
        self._press = None
        if not hasattr(self, "ctx"):
            return
        if self._transition is not None:
            self._transition.restore()
            self._transition = None
        if source is not None and transition:
            target = self._compose(frame_id, scroll)
            if target.shape == source.shape:
                self._transition = self._build_transition(
                    transition, source, target, source_frame_id, frame_id, scroll, scroll_x, reverse=reverse
                )
        if self._transition is not None:
            self.set_continuous_render(True)
        self.invalidate()

    def _build_transition(
        self,
        transition: dict[str, Any],
        source: np.ndarray,
        target: np.ndarray,
        source_frame_id: str,
        frame_id: str,
        scroll: float,
        scroll_x: float,
        *,
        reverse: bool,
    ) -> Transition | None:
        if str(transition.get("type", "")).upper() == "SMART_ANIMATE" and not reverse:
            built = self._build_smart_animate(transition, source_frame_id, frame_id, scroll, scroll_x)
            if built is not None:
                return built
        return Transition.from_figma(transition, source, target, reverse=reverse)

    def _build_smart_animate(
        self,
        transition: dict[str, Any],
        source_frame_id: str,
        frame_id: str,
        scroll: float,
        scroll_x: float,
    ) -> SmartAnimateTransition | None:
        duration = float(transition.get("duration", 0.0) or 0.0)
        if duration <= 0:
            return None
        src_frame = self.document.frame(source_frame_id)
        dst_frame = self.document.frame(frame_id)
        src_info = {str(n.get("id")): (n, tf, container) for n, tf, container in walk_with_parent(src_frame)}
        dst_info = {str(n.get("id")): (n, tf, container) for n, tf, container in walk_with_parent(dst_frame)}
        scale = self._screen(frame_id).scale
        screen = self._screen(frame_id)
        fixed = self.document.fixed_child_ids(frame_id)
        layers: list[TweenLayer] = []
        skip: set[str] = set()
        for pair in match_layers(src_frame, dst_frame):
            if pair.target_id in fixed:
                continue
            src_entry, dst_entry = src_info.get(pair.source_id), dst_info.get(pair.target_id)
            if src_entry is None or dst_entry is None:
                continue
            src_node, src_tf, _ = src_entry
            dst_node, dst_tf, dst_container = dst_entry
            src_geom = layer_geometry(src_node, src_tf)
            dst_geom = layer_geometry(dst_node, dst_tf)
            if not src_geom.differs(dst_geom):
                continue
            skip.add(pair.target_id)
            raster_frame_id, raster_scale, raster_only = frame_id, scale, pair.target_id
            layers.append(
                TweenLayer(
                    node=dst_node,
                    parent_inv=dst_container.inverse(),
                    src=src_geom,
                    dst=dst_geom,
                    render=lambda: self._renderer.render(raster_frame_id, raster_scale, only_ids=(raster_only,), transparent=True),
                    paste_x=screen.offset_x - int(round(scroll_x * scale)),
                    paste_y=screen.offset_y - int(round(scroll * scale)),
                )
            )
        if not layers:
            return None
        base = self._compose(frame_id, scroll, skip_ids=frozenset(skip))
        easing = str((transition.get("easing") or {}).get("type", "EASE_OUT"))
        return SmartAnimateTransition(duration=duration, easing=easing, base=base, layers=layers)

    def _activate(self, spot: Hotspot) -> None:
        handler = self._handlers.get(spot.node_name)
        if handler is not None and handler(self, spot.node_name) is False:
            return
        action = spot.action
        if isinstance(action, NavigateAction):
            self.navigate(action.destination_id, action.transition)
        elif isinstance(action, OverlayAction):
            self.open_overlay(
                action.destination_id,
                position=action.position,
                background=action.background,
                dismiss_on_click_outside=action.dismiss_on_click_outside,
            )
        elif isinstance(action, BackAction):
            self.back()
        elif isinstance(action, VariantAction):
            self.switch_variant(action.destination_id, spot.node_id)
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

    def _scroll_to(self, y: float, x: float | None = None) -> None:
        screen = self._screen(self.current_frame_id)
        clamped_y = min(max(0.0, y), screen.max_scroll)
        clamped_x = min(max(0.0, self.scroll_x if x is None else x), screen.max_scroll_x)
        if clamped_y != self.scroll_y or clamped_x != self.scroll_x:
            self.scroll_y = clamped_y
            self.scroll_x = clamped_x
            self.invalidate()

    def _scroll_surface(self, overlay_idx: int, y: float, x: float | None = None) -> None:
        if overlay_idx < 0:
            self._scroll_to(y, x)
            return
        overlay = self._overlays[overlay_idx]
        surface = self._overlay_surface(overlay)
        clamped = min(max(0.0, y), surface.max_scroll)
        if clamped != overlay.scroll_y:
            overlay.scroll_y = clamped
            self.invalidate()

    def _surface_scale(self, overlay_idx: int) -> float:
        if overlay_idx >= 0:
            return self._overlay_surface(self._overlays[overlay_idx]).scale
        return self._screen(self.current_frame_id).scale

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
            kx, ky = self._display_to_matrix()
            idx = len(self._overlays) - 1 if self._overlays else -1
            scale = self._surface_scale(idx)
            if idx >= 0:
                current_y = self._overlays[-1].scroll_y
                current_x = 0.0
            else:
                current_y, current_x = self.scroll_y, self.scroll_x
            self._scroll_surface(
                idx,
                current_y - float(payload.get("delta_y", 0.0) or 0.0) * ky / scale,
                current_x - float(payload.get("delta_x", 0.0) or 0.0) * kx / scale,
            )
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
            spot, overlay_idx, outside, start_scroll, start_scroll_x = self._press_target()
            self._press = _Press(pointer_id, self._pointer, start_scroll, spot, start_scroll_x, overlay_idx, outside)
            return
        if press is None or press.pointer_id != pointer_id:
            return
        dx, dy = self._pointer[0] - press.start[0], self._pointer[1] - press.start[1]
        if not press.dragging and max(abs(dx), abs(dy)) > DRAG_THRESHOLD_PT:
            press.dragging = True
        if press.dragging:
            kx, ky = self._display_to_matrix()
            scale = self._surface_scale(press.overlay)
            self._scroll_surface(
                press.overlay,
                press.start_scroll - dy * ky / scale,
                press.start_scroll_x - dx * kx / scale,
            )
        if phase == "cancel":
            self._press = None
        elif phase == "up":
            self._press = None
            if press.dragging:
                return
            if press.target is None:
                if (
                    press.outside
                    and 0 <= press.overlay < len(self._overlays)
                    and press.overlay == len(self._overlays) - 1
                    and self._overlays[press.overlay].dismiss_on_click_outside
                ):
                    self.close_overlay()
                return
            spot, overlay_idx, _outside, _scroll_y, _scroll_x = self._press_target()
            if spot is not None and overlay_idx == press.overlay and spot.node_id == press.target.node_id:
                self._activate(spot)

    def _press_target(self) -> tuple[Hotspot | None, int, bool, float, float]:
        """Hotspot under the pointer, its overlay index (-1 = base), and press state."""
        if self._overlays:
            overlay = self._overlays[-1]
            surface = self._overlay_surface(overlay)
            kx, ky = self._display_to_matrix()
            lx = (self._pointer[0] * kx - surface.origin_x) / surface.scale
            ly = (self._pointer[1] * ky - surface.origin_y) / surface.scale
            frame = self.document.frame(overlay.frame_id)
            outside = not (0.0 <= lx <= frame.width and 0.0 <= ly <= frame.height)
            spot = None if outside else self._hit_overlay(overlay, lx, ly)
            return spot, len(self._overlays) - 1, outside, overlay.scroll_y, 0.0
        spot = self._hit(*self._to_view(*self._pointer))
        return spot, -1, False, self.scroll_y, self.scroll_x

    def _hit_overlay(self, overlay: _Overlay, lx: float, ly: float) -> Hotspot | None:
        y = ly + overlay.scroll_y
        return next((t for t in reversed(self._tap_targets(overlay.frame_id)) if t.contains(lx, y)), None)

    def _hit(self, vx: float, vy: float) -> Hotspot | None:
        targets = self._tap_targets()
        screen = self._screen(self.current_frame_id)
        scrolling = screen.max_scroll > 0 or screen.max_scroll_x > 0
        if scrolling and any(x0 <= vx <= x1 and y0 <= vy <= y1 for x0, y0, x1, y1 in self._fixed_regions()):
            return next((t for t in reversed(targets) if t.fixed and t.contains(vx, vy)), None)
        return next(
            (t for t in reversed(targets) if not (scrolling and t.fixed) and t.contains(vx + self.scroll_x, vy + self.scroll_y)),
            None,
        )

    def _fixed_regions(self) -> list[tuple[float, float, float, float]]:
        frame_id = self.current_frame_id
        if frame_id not in self._fixed_bounds:
            ids = self.document.fixed_child_ids(frame_id)
            self._fixed_bounds[frame_id] = list(self.document.node_bounds(frame_id, ids).values())
        return self._fixed_bounds[frame_id]

    def _tap_targets(self, frame_id: str | None = None) -> list[Hotspot]:
        key = frame_id or self.current_frame_id
        cached = self._targets.get(key)
        if cached is None:
            cached = self.document.targets(key, frozenset(self._handlers))
            self._targets[key] = cached
        return cached
