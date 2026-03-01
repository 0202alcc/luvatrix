from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .controls.button import ButtonModel, ButtonState
from .controls.interaction import HDIPressEvent


DEFAULT_FRAME = "screen_tl"


class CoordinateTransformer(Protocol):
    def transform_point(
        self,
        point: tuple[float, float],
        from_frame: str | None = None,
        to_frame: str | None = None,
    ) -> tuple[float, float]:
        ...


@dataclass(frozen=True)
class CoordinatePoint:
    x: float
    y: float
    frame: str | None = None


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float
    frame: str | None = None

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("BoundingBox width/height must be >= 0")

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height


@dataclass(frozen=True)
class DisplayableArea:
    """Displayable content area (excludes black bars in preserve-aspect mode)."""

    content_width_px: float
    content_height_px: float
    viewport_width_px: float | None = None
    viewport_height_px: float | None = None

    def __post_init__(self) -> None:
        if self.content_width_px <= 0 or self.content_height_px <= 0:
            raise ValueError("content dimensions must be > 0")


def parse_coordinate_notation(notation: str, default_frame: str | None = None) -> CoordinatePoint:
    """Parse `x,y` or `frame:x,y` into a CoordinatePoint."""

    raw = notation.strip()
    if not raw:
        raise ValueError("coordinate notation must be non-empty")
    frame: str | None = default_frame
    coords = raw
    if ":" in raw:
        maybe_frame, maybe_coords = raw.split(":", 1)
        if not maybe_frame.strip():
            raise ValueError("coordinate frame name must be non-empty")
        frame = maybe_frame.strip()
        coords = maybe_coords
    parts = [p.strip() for p in coords.split(",")]
    if len(parts) != 2:
        raise ValueError("coordinates must use `x,y` format")
    return CoordinatePoint(x=float(parts[0]), y=float(parts[1]), frame=frame)


def transform_point_to_frame(
    point: CoordinatePoint,
    *,
    target_frame: str,
    transformer: CoordinateTransformer | None,
    fallback_frame: str,
) -> tuple[float, float]:
    source_frame = point.frame or fallback_frame
    if source_frame == target_frame:
        return (point.x, point.y)
    if transformer is None:
        raise ValueError(f"cannot transform from frame `{source_frame}` to `{target_frame}` without transformer")
    return transformer.transform_point((point.x, point.y), from_frame=source_frame, to_frame=target_frame)


@dataclass
class ComponentBase:
    """Shared schema for Luvatrix UI components.

    Visual bounds define how a component is painted.
    Interaction bounds default to visual bounds, but can be overridden without
    changing visual rendering.
    """

    component_id: str
    default_frame: str = DEFAULT_FRAME
    disabled: bool = False
    interaction_bounds_override: BoundingBox | None = None
    drag_bounds_override: BoundingBox | None = None
    draggable: bool = False
    _button_model: ButtonModel = field(default_factory=ButtonModel, init=False, repr=False)
    _drag_active: bool = field(default=False, init=False, repr=False)
    _drag_pointer_offset: tuple[float, float] = field(default=(0.0, 0.0), init=False, repr=False)

    def visual_bounds(self) -> BoundingBox:
        raise NotImplementedError

    @property
    def press_state(self) -> ButtonState:
        return self._button_model.state

    def set_hovered(self, hovered: bool) -> None:
        self._button_model.set_hovered(hovered)

    def set_disabled(self, disabled: bool) -> None:
        self.disabled = disabled
        self._button_model.set_disabled(disabled)

    def interaction_bounds(self) -> BoundingBox:
        return self.interaction_bounds_override or self.visual_bounds()

    def drag_bounds(self) -> BoundingBox:
        return self.drag_bounds_override or self.interaction_bounds()

    def hit_test(
        self,
        point: CoordinatePoint,
        *,
        transformer: CoordinateTransformer | None = None,
    ) -> bool:
        bounds = self.interaction_bounds()
        bx, by = transform_point_to_frame(
            point,
            target_frame=bounds.frame or self.default_frame,
            transformer=transformer,
            fallback_frame=self.default_frame,
        )
        return bounds.contains(bx, by)

    def on_press(self, press: HDIPressEvent, *, inside_interaction_bounds: bool | None = None) -> bool:
        if inside_interaction_bounds is not None:
            self.set_hovered(inside_interaction_bounds)
        if self.disabled:
            self._button_model.set_disabled(True)
            return False
        prev = self._button_model.state
        new_state = self._button_model.on_press(press)
        if inside_interaction_bounds is True:
            return True
        if prev in ("press_down", "press_hold"):
            return True
        return new_state in ("press_down", "press_hold")

    def on_drag_to(self, x: float, y: float, *, frame: str) -> bool:
        """Apply a drag-position update.

        Components that support drag should override this hook to update their own
        position model. Return True when a state mutation occurred.
        """

        _ = (x, y, frame)
        return False

    def update_drag(
        self,
        point: CoordinatePoint,
        *,
        is_down: bool,
        transformer: CoordinateTransformer | None = None,
    ) -> bool:
        """Standardized opt-in drag flow for components.

        - Drag is active only when `draggable=True`.
        - Drag begins on pointer-down inside drag bounds.
        - While active and down, calls `on_drag_to(...)`.
        - Pointer-up ends drag.
        """

        if not self.draggable or self.disabled:
            if not is_down:
                self._drag_active = False
            return False

        bounds = self.drag_bounds()
        bx, by = transform_point_to_frame(
            point,
            target_frame=bounds.frame or self.default_frame,
            transformer=transformer,
            fallback_frame=self.default_frame,
        )
        if is_down:
            if not self._drag_active and bounds.contains(bx, by):
                self._drag_active = True
                self._drag_pointer_offset = (bx - bounds.x, by - bounds.y)
            if self._drag_active:
                ox, oy = self._drag_pointer_offset
                next_x = bx - ox
                next_y = by - oy
                return self.on_drag_to(next_x, next_y, frame=bounds.frame or self.default_frame)
            return False
        self._drag_active = False
        return False
