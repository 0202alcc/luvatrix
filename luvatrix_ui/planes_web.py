"""Browser bridge for Planes/Container apps on the web target.

The same `PlaneApp` runtime drives native targets and the browser: a
`WebAppContext` implements the ctx surface `PlaneApp` expects, converts
JS input snapshots into HDI events, and translates mounted drawables
into the web command-buffer format decoded by the browser renderers
(``command-buffer.js`` / ``renderers.js``). `PlaneWebApp` adapts that
context to the browser app contract (`init_browser` / `loop_browser`)
used by `luvatrix-web.js` under Pyodide.

This module is pure Python (no torch, no `luvatrix_core` beyond the
shipped pure subset: `coordinates` and `hdi_thread`), so the identical
code runs in the native test suite and in the browser bundle.

Supported mounted drawables: `TextComponent` and `SVGComponent` (SVG
markup is inlined as a base64 data URL and drawn by the JS IMAGE op).
Stained-glass buttons and other exotic drawables are skipped for now.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from luvatrix_core.core.hdi_thread import HDIEvent

from .controls.svg_component import SVGComponent
from .planes_runtime import PlaneApp
from .text.component import TextComponent

OP_CLEAR = 1
OP_SHADER_RECT = 2
OP_RECT = 3
OP_CIRCLE = 4
OP_TEXT = 5
OP_ROUNDED_RECT = 19
OP_IMAGE = 23

DEFAULT_FONT_FAMILY = "Comic Mono"


def _rgba_floats(color_rgba: tuple[int, int, int, int]) -> list[float]:
    return [max(0.0, min(1.0, float(ch) / 255.0)) for ch in color_rgba]


def _hex_to_rgba(color_hex: str, alpha: float) -> tuple[int, int, int, int]:
    raw = str(color_hex).strip().lstrip("#")
    if len(raw) == 6:
        rgb = raw
        base_alpha = 255
    elif len(raw) == 8:
        rgb = raw[:6]
        base_alpha = int(raw[6:8], 16)
    else:
        rgb = "F5FBFF"
        base_alpha = 255
    return (
        int(rgb[0:2], 16),
        int(rgb[2:4], 16),
        int(rgb[4:6], 16),
        int(round(base_alpha * max(0.0, min(1.0, float(alpha))))),
    )


def _svg_data_url(markup: str) -> str:
    encoded = base64.b64encode(str(markup).encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


class WebCommandBufferBuilder:
    """Command buffer producer matching the JS decoder contract.

    Headers are flat 4-word entries ``[opcode, float_start, float_count,
    meta0]`` plus a 5th ``font_id`` word for text commands. Strings are
    interned; ``meta0`` carries the text/asset string id.
    """

    def __init__(self, *, width: int, height: int) -> None:
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.headers: list[int] = []
        self.floats: list[float] = []
        self.strings: list[str] = []
        self._string_ids: dict[str, int] = {}

    def _intern(self, value: str) -> int:
        existing = self._string_ids.get(value)
        if existing is not None:
            return existing
        self._string_ids[value] = len(self.strings)
        self.strings.append(value)
        return len(self.strings) - 1

    def clear(self, color_rgba: tuple[int, int, int, int]) -> None:
        self.headers.extend([OP_CLEAR, len(self.floats), 4, 0])
        self.floats.extend(_rgba_floats(color_rgba))

    def rect(self, *, x: float, y: float, width: float, height: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_RECT, start, len(values), 0])
        self.floats.extend(values)

    def rounded_rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float,
        color_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), float(radius), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_ROUNDED_RECT, start, len(values), 0])
        self.floats.extend(values)

    def circle(
        self,
        *,
        cx: float,
        cy: float,
        radius: float,
        fill_rgba: tuple[int, int, int, int],
        stroke_rgba: tuple[int, int, int, int] = (0, 0, 0, 0),
        stroke_width: float = 0.0,
    ) -> None:
        start = len(self.floats)
        values = [
            float(cx),
            float(cy),
            float(radius),
            *_rgba_floats(fill_rgba),
            *_rgba_floats(stroke_rgba),
            float(stroke_width),
        ]
        self.headers.extend([OP_CIRCLE, start, len(values), 0])
        self.floats.extend(values)

    def text(
        self,
        text: str,
        *,
        x: float,
        y: float,
        font_family: str = DEFAULT_FONT_FAMILY,
        font_size_px: float = 14.0,
        color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255),
        max_width_px: float | None = None,
        rotation_deg: float = 0.0,
    ) -> None:
        text_id = self._intern(str(text))
        font_id = self._intern(str(font_family))
        start = len(self.floats)
        values = [
            float(x),
            float(y),
            float(font_size_px),
            *_rgba_floats(color_rgba),
            float(max_width_px or 0.0),
            float(rotation_deg),
        ]
        self.headers.extend([OP_TEXT, start, len(values), text_id, font_id])
        self.floats.extend(values)

    def image(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        opacity: float,
        asset: str,
    ) -> None:
        asset_id = self._intern(str(asset))
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), max(0.0, min(1.0, float(opacity)))]
        self.headers.extend([OP_IMAGE, start, len(values), asset_id])
        self.floats.extend(values)

    def finish(self) -> dict[str, object]:
        return {
            "headers": self.headers,
            "floats": self.floats,
            "strings": self.strings,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class WebMatrix:
    width: int
    height: int


class WebAppContext:
    """AppContext-shaped adapter for `PlaneApp` in the browser.

    Implements the ctx surface PlaneApp uses: `matrix`, `poll_hdi_events`,
    `begin_ui_frame` / `mount_component` / `finalize_ui_frame`, plus the
    optional counters (`mounted`, `pending_hdi_events`,
    `consume_hdi_telemetry`). The renderer argument of `begin_ui_frame` is
    ignored: the browser translates mounts straight into command-buffer
    ops instead of compiling a torch frame tensor.
    """

    def __init__(
        self,
        *,
        width: int,
        height: int,
        input_provider: Callable[[], object],
    ) -> None:
        self.matrix = WebMatrix(width=max(1, int(width)), height=max(1, int(height)))
        self.input_provider = input_provider
        self.mounted: list[Any] = []
        self.last_buffer: dict[str, object] | None = None
        self._builder: WebCommandBufferBuilder | None = None
        self._pending_mounts: list[Any] = []
        self._event_seq = 0
        self._last_pointer: tuple[float, float] | None = None
        self.skipped_mount_types: dict[str, int] = {}

    # -- input -> HDI events -------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        snapshot = self.input_provider()
        return dict(snapshot) if isinstance(snapshot, dict) else {}

    def _next_event(self, event_type: str, device: str, payload: dict[str, Any]) -> HDIEvent:
        self._event_seq += 1
        return HDIEvent(
            event_id=self._event_seq,
            ts_ns=time.time_ns(),
            window_id="web",
            device=device,
            event_type=event_type,
            status="OK",
            payload=payload,
        )

    def poll_hdi_events(self, max_events: int, frame: str | None = None) -> list[HDIEvent]:
        _ = frame
        events: list[HDIEvent] = []
        snapshot = self._snapshot()

        mouse_x = float(snapshot.get("mouse_x", 0.0) or 0.0)
        mouse_y = float(snapshot.get("mouse_y", 0.0) or 0.0)
        in_window = bool(snapshot.get("mouse_in_window", False))

        if in_window:
            if self._last_pointer != (mouse_x, mouse_y):
                self._last_pointer = (mouse_x, mouse_y)
                events.append(
                    self._next_event("pointer_move", "mouse", {"x": mouse_x, "y": mouse_y})
                )
            if snapshot.get("left_clicked"):
                events.append(
                    self._next_event("click", "mouse", {"x": mouse_x, "y": mouse_y})
                )
            scroll_x = float(snapshot.get("scroll_x", 0.0) or 0.0)
            scroll_y = float(snapshot.get("scroll_y", 0.0) or 0.0)
            if scroll_x or scroll_y:
                events.append(
                    self._next_event(
                        "scroll",
                        "mouse",
                        {"delta_x": scroll_x, "delta_y": scroll_y, "phase": "update"},
                    )
                )
        else:
            self._last_pointer = None

        return events[: max(0, int(max_events))]

    def pending_hdi_events(self) -> int:
        return 0

    def consume_hdi_telemetry(self) -> dict[str, int]:
        return {}

    # -- frame pipeline -> command buffer ------------------------------------

    def begin_ui_frame(
        self,
        renderer: Any,
        *,
        content_width_px: float,
        content_height_px: float,
        clear_color: tuple[int, int, int, int],
        dirty_rects: Any = None,
        scroll_shift: Any = None,
    ) -> None:
        _ = (renderer, content_width_px, content_height_px, dirty_rects, scroll_shift)
        self._builder = WebCommandBufferBuilder(
            width=self.matrix.width,
            height=self.matrix.height,
        )
        self._builder.clear(clear_color)
        self._pending_mounts = []

    def mount_component(self, component: Any) -> None:
        self._pending_mounts.append(component)
        self.mounted.append(component)

    def finalize_ui_frame(self) -> None:
        builder = self._builder
        if builder is None:
            return
        for component in self._pending_mounts:
            self._emit_component(builder, component)
        self._pending_mounts = []
        self.last_buffer = builder.finish()
        self._builder = None

    def _emit_component(self, builder: WebCommandBufferBuilder, component: Any) -> None:
        if isinstance(component, TextComponent):
            builder.text(
                str(component.text),
                x=float(component.position.x),
                y=float(component.position.y),
                font_size_px=float(component.size.value),
                color_rgba=_hex_to_rgba(
                    str(component.appearance.color_hex),
                    float(component.appearance.opacity),
                ),
                max_width_px=getattr(component, "max_width_px", None),
            )
            return
        if isinstance(component, SVGComponent):
            builder.image(
                x=float(component.position.x),
                y=float(component.position.y),
                width=float(component.width),
                height=float(component.height),
                opacity=float(component.opacity),
                asset=_svg_data_url(component.svg_markup),
            )
            return
        type_name = type(component).__name__
        self.skipped_mount_types[type_name] = int(self.skipped_mount_types.get(type_name, 0)) + 1


class PlaneWebApp:
    """Browser contract (`init_browser` / `loop_browser`) over `PlaneApp`.

    Usage inside an app entrypoint that must run on both native and web:

        def init_browser(self, *, width, height, input_provider, manifest):
            self._web = PlaneWebApp(APP_DIR / "container.json", handlers={...})
            self._web.init_browser(width=width, height=height,
                                    input_provider=input_provider, manifest=manifest)

        def loop_browser(self, dt):
            return self._web.loop_browser(dt)
    """

    def __init__(
        self,
        plane_path: str | Any,
        *,
        handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], object | None]] | None = None,
        strict: bool = True,
    ) -> None:
        self._app = PlaneApp(plane_path, handlers=handlers, strict=strict)
        self._ctx: WebAppContext | None = None

    @property
    def state(self) -> dict[str, Any]:
        return self._app.state

    def set_input_provider(self, provider: Callable[[], object]) -> None:
        if self._ctx is not None:
            self._ctx.input_provider = provider

    def activate_route(self, route_id: str) -> None:
        self._app.activate_route(route_id)

    def init_browser(
        self,
        *,
        width: int,
        height: int,
        input_provider: Callable[[], object],
        manifest: dict[str, object] | None = None,
    ) -> None:
        _ = manifest
        self._ctx = WebAppContext(width=width, height=height, input_provider=input_provider)
        self._app.init(self._ctx)

    def loop_browser(self, dt: float) -> dict[str, object]:
        if self._ctx is None:
            raise RuntimeError("init_browser must run before loop_browser")
        self._app.loop(self._ctx, float(dt))
        buffer = self._ctx.last_buffer
        if buffer is None:
            # Idle-skip frame: replay the last presented buffer.
            buffer = self._ctx.last_buffer or {
                "headers": [],
                "floats": [],
                "strings": [],
                "width": self._ctx.matrix.width,
                "height": self._ctx.matrix.height,
            }
        return buffer

    def teardown_browser(self) -> None:
        if self._ctx is not None:
            self._app.stop(self._ctx)