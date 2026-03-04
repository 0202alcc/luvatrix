from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

import torch

from luvatrix_core.core.app_runtime import AppContext
from luvatrix_core.core.hdi_thread import HDIEvent
from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_ui.planes_runtime import PlaneApp, load_plane_app


@dataclass
class _Matrix:
    width: int
    height: int


class _FakeCtx:
    def __init__(self, width: int, height: int) -> None:
        self.matrix = _Matrix(width=width, height=height)
        self.mounted = []
        self.begin_calls = 0
        self.finalize_calls = 0
        self.clear = None
        self.last_dirty_rects = None
        self.last_scroll_shift = None
        self._events: list[HDIEvent] = []

    def begin_ui_frame(
        self,
        renderer,
        *,
        content_width_px,
        content_height_px,
        clear_color,
        dirty_rects=None,
        scroll_shift=None,
    ) -> None:
        _ = (renderer, content_width_px, content_height_px)
        self.begin_calls += 1
        self.clear = clear_color
        self.last_dirty_rects = dirty_rects
        self.last_scroll_shift = scroll_shift

    def mount_component(self, component) -> None:
        self.mounted.append(component)

    def finalize_ui_frame(self) -> None:
        self.finalize_calls += 1

    def poll_hdi_events(self, max_events: int):
        out = list(self._events[: max(0, int(max_events))])
        self._events = self._events[max(0, int(max_events)) :]
        return out

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)

    def pending_hdi_events(self) -> int:
        return len(self._events)

    def consume_hdi_telemetry(self) -> dict[str, int]:
        return {}


class _QueuedHDI:
    def __init__(self) -> None:
        self._events: list[HDIEvent] = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)

    def poll_events(self, max_events: int) -> list[HDIEvent]:
        out = list(self._events[:max_events])
        self._events = self._events[max_events:]
        return out


class _NoopSensorManager:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=0,
            ts_ns=0,
            sensor_type=sensor_type,
            status="UNAVAILABLE",
            value=None,
            unit=None,
        )


def _build_plane_file(root: Path) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "logo.svg").write_text(
        "<svg width=\"10\" height=\"10\" xmlns=\"http://www.w3.org/2000/svg\"><rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" fill=\"#ffffff\"/></svg>",
        encoding="utf-8",
    )
    payload = {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "x",
            "title": "Demo",
            "icon": "assets/logo.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {
            "id": "main",
            "default_frame": "screen_tl",
            "background": {"color": "#112233"},
        },
        "scripts": [{"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}],
        "components": [
            {
                "id": "title",
                "type": "text",
                "position": {"x": 10, "y": 10},
                "size": {
                    "width": {"unit": "px", "value": 120},
                    "height": {"unit": "px", "value": 30},
                },
                "z_index": 2,
                "functions": {"on_press_single": "handlers::open"},
                "props": {
                    "text": "hello",
                    "font_size_px": 16,
                    "color_hex": "#f5fbff",
                    "hover_color_hex": "#ffe082",
                    "theme_colors": {"default": "#f5fbff", "alt": "#9bc9f8"},
                },
            },
            {
                "id": "logo",
                "type": "svg",
                "position": {"x": 12, "y": 52},
                "size": {
                    "width": {"unit": "px", "value": 32},
                    "height": {"unit": "px", "value": 32},
                },
                "z_index": 3,
                "props": {"svg": "assets/logo.svg"},
            },
        ],
    }
    plane_path = root / "plane.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_theme_background_plane_file(root: Path) -> Path:
    plane_path = _build_plane_file(root)
    payload = json.loads(plane_path.read_text(encoding="utf-8"))
    payload["themes"] = {
        "default": {"background": "#112233"},
        "alt": {"background": "#223344"},
    }
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_scroll_plane_file(root: Path) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "canvas.svg").write_text(
        "<svg width=\"220\" height=\"200\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"0\" y=\"0\" width=\"220\" height=\"200\" fill=\"#224466\"/>"
        "<rect x=\"120\" y=\"120\" width=\"80\" height=\"60\" fill=\"#88ccff\"/>"
        "</svg>",
        encoding="utf-8",
    )
    payload = {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "x.scroll",
            "title": "Scroll",
            "icon": "assets/canvas.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {
            "id": "main",
            "default_frame": "screen_tl",
            "background": {"color": "#0b1320"},
        },
        "scripts": [{"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}],
        "components": [
            {
                "id": "canvas",
                "type": "svg",
                "position": {"x": 0, "y": 0},
                "size": {"width": {"unit": "px", "value": 220}, "height": {"unit": "px", "value": 200}},
                "z_index": 0,
                "props": {"svg": "assets/canvas.svg"},
            },
            {
                "id": "viewport",
                "type": "viewport",
                "position": {"x": 10, "y": 12},
                "size": {"width": {"unit": "px", "value": 100}, "height": {"unit": "px", "value": 80}},
                "z_index": 4,
                "props": {
                    "clip": True,
                    "content_ref": "canvas",
                    "scroll": {"x": 0, "y": 0},
                    "scroll_speed": {"x": 1.0, "y": 1.0},
                },
            },
        ],
    }
    plane_path = root / "plane_scroll.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_nested_scroll_plane_file(root: Path) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "outer.svg").write_text(
        "<svg width=\"260\" height=\"220\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"0\" y=\"0\" width=\"260\" height=\"220\" fill=\"#204060\"/></svg>",
        encoding="utf-8",
    )
    (root / "assets" / "inner.svg").write_text(
        "<svg width=\"140\" height=\"120\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"0\" y=\"0\" width=\"140\" height=\"120\" fill=\"#6080a0\"/></svg>",
        encoding="utf-8",
    )
    payload = {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "x.nested",
            "title": "Nested",
            "icon": "assets/outer.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {"id": "main", "default_frame": "screen_tl", "background": {"color": "#111111"}},
        "scripts": [{"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}],
        "components": [
            {
                "id": "outer_canvas",
                "type": "svg",
                "position": {"x": 0, "y": 0},
                "size": {"width": {"unit": "px", "value": 260}, "height": {"unit": "px", "value": 220}},
                "z_index": 0,
                "props": {"svg": "assets/outer.svg"},
            },
            {
                "id": "inner_canvas",
                "type": "svg",
                "position": {"x": 0, "y": 0},
                "size": {"width": {"unit": "px", "value": 140}, "height": {"unit": "px", "value": 120}},
                "z_index": 1,
                "props": {"svg": "assets/inner.svg"},
            },
            {
                "id": "outer_viewport",
                "type": "viewport",
                "position": {"x": 10, "y": 10},
                "size": {"width": {"unit": "px", "value": 120}, "height": {"unit": "px", "value": 100}},
                "z_index": 5,
                "props": {"clip": True, "content_ref": "outer_canvas", "scroll": {"x": 0, "y": 0}},
            },
            {
                "id": "inner_viewport",
                "type": "viewport",
                "position": {"x": 20, "y": 20},
                "size": {"width": {"unit": "px", "value": 100}, "height": {"unit": "px", "value": 90}},
                "z_index": 6,
                "props": {"clip": True, "content_ref": "inner_canvas", "scroll": {"x": 0, "y": 0}},
            },
        ],
    }
    plane_path = root / "plane_nested_scroll.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_plane_camera_scroll_file(root: Path, *, include_fixed_title: bool = True) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "panel.svg").write_text(
        "<svg width=\"800\" height=\"600\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"0\" y=\"0\" width=\"800\" height=\"600\" fill=\"#2a77b8\"/></svg>",
        encoding="utf-8",
    )
    payload = {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "x.plane_scroll",
            "title": "Plane Scroll",
            "icon": "assets/panel.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {"id": "main", "default_frame": "screen_tl", "background": {"color": "#111111"}},
        "scripts": [{"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}],
        "components": [
            {
                "id": "panel",
                "type": "svg",
                "position": {"x": 220, "y": 160},
                "size": {"width": {"unit": "px", "value": 800}, "height": {"unit": "px", "value": 600}},
                "z_index": 0,
                "props": {"svg": "assets/panel.svg"},
            }
        ],
    }
    if include_fixed_title:
        payload["components"].append(
            {
                "id": "fixed_title",
                "type": "text",
                "position": {"x": 12, "y": 8},
                "size": {"width": {"unit": "px", "value": 120}, "height": {"unit": "px", "value": 24}},
                "z_index": 10,
                "props": {"text": "fixed", "camera_fixed": True},
            }
        )
    plane_path = root / "plane_camera_scroll.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_plane_culling_file(root: Path) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "rect.svg").write_text(
        "<svg width=\"200\" height=\"120\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"0\" y=\"0\" width=\"200\" height=\"120\" fill=\"#2a77b8\"/></svg>",
        encoding="utf-8",
    )
    payload = {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "x.cull",
            "title": "Cull",
            "icon": "assets/rect.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {"id": "main", "default_frame": "screen_tl", "background": {"color": "#111111"}},
        "components": [
            {
                "id": "near_panel",
                "type": "svg",
                "position": {"x": 20, "y": 20},
                "size": {"width": {"unit": "px", "value": 200}, "height": {"unit": "px", "value": 120}},
                "z_index": 1,
                "props": {"svg": "assets/rect.svg"},
            },
            {
                "id": "far_panel",
                "type": "svg",
                "position": {"x": 2200, "y": 1600},
                "size": {"width": {"unit": "px", "value": 200}, "height": {"unit": "px", "value": 120}},
                "z_index": 1,
                "props": {"svg": "assets/rect.svg"},
            },
        ],
    }
    plane_path = root / "plane_cull.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_plane_v2_multi_file(root: Path) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "rect.svg").write_text(
        "<svg width=\"300\" height=\"200\" xmlns=\"http://www.w3.org/2000/svg\">"
        "<rect x=\"0\" y=\"0\" width=\"300\" height=\"200\" fill=\"#2a77b8\"/></svg>",
        encoding="utf-8",
    )
    payload = {
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "x.v2",
            "title": "V2",
            "icon": "assets/rect.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": [
            {
                "id": "world",
                "default_frame": "screen_tl",
                "background": {"color": "#111111"},
                "plane_global_z": 0,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 1200}, "height": {"unit": "px", "value": 900}},
            },
            {
                "id": "content",
                "default_frame": "screen_tl",
                "background": {"color": "#111111"},
                "plane_global_z": 5,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 1200}, "height": {"unit": "px", "value": 900}},
            },
        ],
        "routes": [{"id": "main", "default": True, "active_planes": ["world", "content"]}],
        "components": [
            {
                "id": "world_panel",
                "type": "svg",
                "attachment_kind": "plane",
                "attach_to": "world",
                "component_local_z": 1,
                "blend_mode": "absolute_rgba",
                "position": {"x": 200, "y": 120, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 300}, "height": {"unit": "px", "value": 200}},
                "props": {"svg": "assets/rect.svg"},
            },
            {
                "id": "overlay_text",
                "type": "text",
                "attachment_kind": "camera_overlay",
                "component_local_z": 10,
                "blend_mode": "absolute_rgba",
                "position": {"x": 12, "y": 8, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 120}, "height": {"unit": "px", "value": 24}},
                "props": {"text": "fixed"},
            },
        ],
    }
    plane_path = root / "plane_v2_multi.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


def _build_scroll_hook_plane_file(root: Path) -> Path:
    payload = {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "x.scroll_hook",
            "title": "Scroll Hook",
            "icon": "assets/logo.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {"id": "main", "default_frame": "screen_tl", "background": {"color": "#112233"}},
        "scripts": [{"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}],
        "components": [
            {
                "id": "hook_target",
                "type": "text",
                "position": {"x": 10, "y": 10},
                "size": {"width": {"unit": "px", "value": 220}, "height": {"unit": "px", "value": 24}},
                "z_index": 2,
                "functions": {"on_scroll": "handlers::on_scroll"},
                "props": {"text": "scroll target"},
            }
        ],
    }
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "logo.svg").write_text(
        "<svg width=\"10\" height=\"10\" xmlns=\"http://www.w3.org/2000/svg\"><rect x=\"0\" y=\"0\" width=\"10\" height=\"10\" fill=\"#ffffff\"/></svg>",
        encoding="utf-8",
    )
    plane_path = root / "plane_scroll_hook.json"
    plane_path.write_text(json.dumps(payload), encoding="utf-8")
    return plane_path


class PlanesRuntimeTests(unittest.TestCase):
    def test_load_plane_app_renders_components(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)

            self.assertEqual(ctx.begin_calls, 1)
            self.assertEqual(ctx.finalize_calls, 1)
            self.assertEqual(len(ctx.mounted), 2)
            self.assertEqual(ctx.clear, (17, 34, 51, 255))

    def test_plane_runtime_dispatches_click_handler(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = PlaneApp(plane_path, handlers={})
            calls: list[tuple[str, str]] = []

            def _on_open(event_ctx, state):
                state["clicked"] = event_ctx["component_id"]
                calls.append((event_ctx["hook"], event_ctx["component_id"]))

            app.register_handler("handlers::open", _on_open)
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="click",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0},
                )
            )
            app.loop(ctx, 0.016)
            self.assertEqual(calls, [("on_press_single", "title")])
            self.assertEqual(app.state.get("clicked"), "title")

    def test_plane_runtime_strict_missing_handler_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={}, strict=True)
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="click",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0},
                )
            )
            with self.assertRaises(RuntimeError):
                app.loop(ctx, 0.016)

    def test_plane_runtime_uses_last_pointer_xy_when_click_payload_has_no_coords(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = PlaneApp(plane_path, handlers={})
            calls: list[tuple[str, str]] = []

            def _on_open(event_ctx, state):
                state["clicked"] = event_ctx["component_id"]
                calls.append((event_ctx["hook"], event_ctx["component_id"]))

            app.register_handler("handlers::open", _on_open)
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="pointer_move",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0},
                )
            )
            ctx.queue(
                HDIEvent(
                    event_id=2,
                    ts_ns=2,
                    window_id="w",
                    device="mouse",
                    event_type="press",
                    status="OK",
                    payload={"phase": "single", "key": ""},
                )
            )
            app.loop(ctx, 0.016)
            self.assertEqual(calls, [("on_press_single", "title")])
            self.assertEqual(app.state.get("clicked"), "title")

    def test_plane_runtime_builtin_viewport_scroll_updates_camera_offset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.mounted = []
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0, "delta_x": -40.0, "delta_y": -25.0},
                )
            )
            app.loop(ctx, 0.016)

            scroll_state = app.state.get("viewport_scroll", {})
            self.assertIsInstance(scroll_state, dict)
            self.assertIn("viewport", scroll_state)
            entry = scroll_state["viewport"]
            self.assertAlmostEqual(float(entry["x"]), 40.0, places=6)
            self.assertAlmostEqual(float(entry["y"]), 25.0, places=6)

            content_mount = next((comp for comp in ctx.mounted if comp.component_id == "viewport__content"), None)
            self.assertIsNotNone(content_mount)
            assert content_mount is not None
            self.assertAlmostEqual(float(content_mount.position.x), -30.0, places=6)
            self.assertAlmostEqual(float(content_mount.position.y), -13.0, places=6)

    def test_plane_runtime_viewport_scroll_is_clamped_to_content_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0, "delta_x": -500.0, "delta_y": -500.0},
                )
            )
            app.loop(ctx, 0.016)
            scroll_state = app.state["viewport_scroll"]["viewport"]
            # max_x = 220 - 100 = 120, max_y = 200 - 80 = 120
            self.assertAlmostEqual(float(scroll_state["x"]), 120.0, places=6)
            self.assertAlmostEqual(float(scroll_state["y"]), 120.0, places=6)

    def test_plane_runtime_scroll_remainder_bubbles_to_underlying_viewport(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_nested_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=220)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -80.0, "delta_y": -80.0},
                )
            )
            app.loop(ctx, 0.016)
            outer = app.state["viewport_scroll"]["outer_viewport"]
            inner = app.state["viewport_scroll"]["inner_viewport"]
            # inner max: x=40, y=30 ; outer max: x=140, y=120
            self.assertAlmostEqual(float(inner["x"]), 40.0, places=6)
            self.assertAlmostEqual(float(inner["y"]), 30.0, places=6)
            self.assertAlmostEqual(float(outer["x"]), 40.0, places=6)
            self.assertAlmostEqual(float(outer["y"]), 50.0, places=6)

    def test_plane_runtime_mounts_viewport_scrollbars_when_content_overflows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ids = {comp.component_id for comp in ctx.mounted}
            self.assertIn("viewport__scrollbar_x_track", ids)
            self.assertIn("viewport__scrollbar_x_thumb", ids)
            self.assertIn("viewport__scrollbar_y_track", ids)
            self.assertIn("viewport__scrollbar_y_thumb", ids)
            perf = app.state.get("perf", {})
            self.assertGreaterEqual(int(perf.get("camera_overlay_scrollbar_primitives", 0)), 4)

    def test_plane_runtime_scrolls_main_plane_when_no_viewport_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_camera_scroll_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -140.0, "delta_y": -100.0},
                )
            )
            app.loop(ctx, 0.016)

            plane_scroll = app.state.get("plane_scroll", {})
            self.assertIsInstance(plane_scroll, dict)
            self.assertAlmostEqual(float(plane_scroll.get("x", 0.0)), 140.0, places=6)
            self.assertAlmostEqual(float(plane_scroll.get("y", 0.0)), 100.0, places=6)

            panel = next((comp for comp in ctx.mounted if comp.component_id == "panel"), None)
            fixed = next((comp for comp in ctx.mounted if comp.component_id == "fixed_title"), None)
            self.assertIsNotNone(panel)
            self.assertIsNotNone(fixed)
            assert panel is not None
            assert fixed is not None
            self.assertAlmostEqual(float(panel.position.x), 80.0, places=6)  # 220 - scroll_x(140)
            self.assertAlmostEqual(float(panel.position.y), 60.0, places=6)  # 160 - scroll_y(100)
            self.assertAlmostEqual(float(fixed.position.x), 12.0, places=6)  # fixed to camera
            self.assertAlmostEqual(float(fixed.position.y), 8.0, places=6)
            ids = {comp.component_id for comp in ctx.mounted}
            self.assertIn("__plane_scrollbar_x_track", ids)
            self.assertIn("__plane_scrollbar_x_thumb", ids)
            self.assertIn("__plane_scrollbar_y_track", ids)
            self.assertIn("__plane_scrollbar_y_thumb", ids)

    def test_plane_runtime_culls_far_offscreen_components_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_culling_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)

            ids = {comp.component_id for comp in ctx.mounted}
            self.assertIn("near_panel", ids)
            self.assertNotIn("far_panel", ids)

            perf = app.state.get("perf", {})
            self.assertEqual(int(perf.get("components_considered", 0)), 2)
            self.assertEqual(int(perf.get("components_culled", 0)), 1)
            self.assertEqual(int(perf.get("components_mounted", 0)), 1)

    def test_plane_runtime_reuses_svg_markup_cache_across_frames(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_culling_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            first_perf = dict(app.state.get("perf", {}))
            self.assertEqual(int(first_perf.get("svg_cache_size", 0)), 1)

            ctx.mounted = []
            app.loop(ctx, 0.016)
            second_perf = dict(app.state.get("perf", {}))
            self.assertEqual(int(second_perf.get("svg_cache_size", 0)), 1)

    def test_plane_runtime_reuses_retained_mount_nodes_for_unchanged_frame(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            first_by_id = {comp.component_id: comp for comp in ctx.mounted}

            ctx.mounted = []
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0, "delta_x": -1.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            second_by_id = {comp.component_id: comp for comp in ctx.mounted}

            self.assertIs(first_by_id["title"], second_by_id["title"])
            self.assertIs(first_by_id["logo"], second_by_id["logo"])
            perf = app.state.get("perf", {})
            self.assertGreaterEqual(int(perf.get("retained_components_reused", 0)), 2)

    def test_plane_runtime_skips_compose_when_no_dirty_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            begin_before = ctx.begin_calls
            finalize_before = ctx.finalize_calls

            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "idle_skip")
            self.assertEqual(int(perf.get("dirty_rect_count", -1)), 0)
            self.assertEqual(ctx.begin_calls, begin_before)
            self.assertEqual(ctx.finalize_calls, finalize_before)

    def test_plane_runtime_pointer_move_without_visual_delta_skips_compose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            begin_before = ctx.begin_calls
            finalize_before = ctx.finalize_calls
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="pointer_move",
                    status="OK",
                    payload={"x": 300.0, "y": 170.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "idle_skip")
            self.assertEqual(int(perf.get("dirty_rect_count", -1)), 0)
            self.assertEqual(ctx.begin_calls, begin_before)
            self.assertEqual(ctx.finalize_calls, finalize_before)

    def test_plane_runtime_hover_transition_invalidates_old_new_bounds_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="pointer_move",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0},
                )
            )
            app.loop(ctx, 0.016)
            self.assertEqual(str(app.state.get("hover_component_id", "")), "title")
            self.assertEqual(str(app.state.get("perf", {}).get("compose_mode", "")), "partial_dirty")
            self.assertEqual(ctx.last_dirty_rects, [(9, 9, 122, 32)])

            ctx.queue(
                HDIEvent(
                    event_id=2,
                    ts_ns=2,
                    window_id="w",
                    device="mouse",
                    event_type="pointer_move",
                    status="OK",
                    payload={"x": 20.0, "y": 60.0},
                )
            )
            app.loop(ctx, 0.016)
            self.assertEqual(str(app.state.get("hover_component_id", "")), "logo")
            self.assertEqual(str(app.state.get("perf", {}).get("compose_mode", "")), "partial_dirty")
            self.assertEqual(ctx.last_dirty_rects, [(9, 9, 122, 32), (11, 51, 34, 34)])

    def test_plane_runtime_theme_change_uses_scoped_dirty_when_background_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            app.state["active_theme"] = "alt"
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "partial_dirty")
            self.assertEqual(ctx.last_dirty_rects, [(9, 9, 122, 32)])
            self.assertLess(int(perf.get("dirty_rect_area_px", 0)), 320 * 180)

    def test_plane_runtime_theme_change_uses_full_frame_when_background_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_theme_background_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::open": lambda e, s: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            app.state["active_theme"] = "alt"
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "full_frame")
            self.assertEqual(ctx.last_dirty_rects, [(0, 0, 320, 180)])

    def test_plane_runtime_exposes_frame_timing_stages_and_event_counters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0, "delta_x": -8.0, "delta_y": -4.0},
                )
            )
            app.loop(ctx, 0.016)

            perf = app.state.get("perf", {})
            self.assertGreaterEqual(int(perf.get("events_polled", 0)), 1)
            self.assertGreaterEqual(int(perf.get("events_processed", 0)), 1)
            self.assertGreaterEqual(int(perf.get("scroll_events", 0)), 1)
            self.assertGreaterEqual(int(perf.get("hit_test_calls", 0)), 1)
            self.assertGreaterEqual(int(perf.get("hit_test_candidates_checked", 0)), 1)
            self.assertGreaterEqual(int(perf.get("hit_test_spatial_buckets", 0)), 1)
            self.assertGreaterEqual(int(perf.get("scroll_scheduler_coalesced_events", 0)), 0)
            self.assertGreaterEqual(int(perf.get("intent_queue_depth_before", 0)), 0)
            self.assertGreaterEqual(int(perf.get("intent_queue_depth_after_enqueue", 0)), 0)
            self.assertGreaterEqual(int(perf.get("intent_queue_depth_after_drain", 0)), 0)
            self.assertGreaterEqual(int(perf.get("bitmap_cache_hits", 0)), 0)
            self.assertGreaterEqual(int(perf.get("bitmap_cache_misses", 0)), 0)
            self.assertGreaterEqual(int(perf.get("layout_cache_hits", 0)), 1)
            self.assertGreaterEqual(int(perf.get("layout_cache_misses", 0)), 1)
            self.assertGreaterEqual(int(perf.get("renderer_batch_groups", 0)), 0)
            self.assertGreaterEqual(int(perf.get("renderer_batch_state_switches", 0)), 0)

            timing = perf.get("timing_ms", {})
            self.assertIsInstance(timing, dict)
            expected_keys = {"input", "hit_test", "scroll_update", "cull", "mount", "raster", "present", "frame_total"}
            self.assertTrue(expected_keys.issubset(set(timing.keys())))
            for key in expected_keys:
                value = float(timing.get(key, 0.0))
                self.assertGreaterEqual(value, 0.0)
            self.assertGreaterEqual(int(perf.get("copy_count", 0)), 0)
            self.assertGreaterEqual(int(perf.get("copy_bytes", 0)), 0)
            self.assertGreaterEqual(float(perf.get("dirty_rect_area_ratio", 0.0)), 0.0)
            self.assertGreaterEqual(float(perf.get("incremental_present_pct", 0.0)), 0.0)
            self.assertGreaterEqual(float(perf.get("full_present_pct", 0.0)), 0.0)
            self.assertTrue(isinstance(perf.get("intent_queue_enabled", False), bool))
            self.assertTrue(isinstance(perf.get("scroll_scheduler_enabled", False), bool))
            self.assertTrue(isinstance(perf.get("scroll_bitmap_cache_enabled", False), bool))
            copy_timing = perf.get("copy_timing_ms", {})
            self.assertIsInstance(copy_timing, dict)
            for key in (
                "ui_pack",
                "matrix_stage_clone",
                "matrix_snapshot_clone",
                "upload_pack",
                "upload_map",
                "upload_memcpy",
                "queue_submit",
                "queue_present",
            ):
                self.assertGreaterEqual(float(copy_timing.get(key, 0.0)), 0.0)

    def test_plane_runtime_intent_queue_handoff_limits_frame_drain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_hook_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::on_scroll": lambda event_ctx, state: None})
            app.state["intent_queue_enabled"] = True
            app._event_batch_base = 2
            app._event_batch_max = 2
            app._intent_ingest_max = 8
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            for i in range(8):
                ctx.queue(
                    HDIEvent(
                        event_id=i + 1,
                        ts_ns=i + 1,
                        window_id="w",
                        device="trackpad",
                        event_type="scroll",
                        status="OK",
                        payload={"x": 20.0, "y": 20.0, "delta_x": -1.0, "delta_y": -1.0, "phase": "changed"},
                    )
                )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(int(perf.get("events_processed", 0)), 2)
            self.assertEqual(int(perf.get("intent_queue_enqueued", 0)), 8)
            self.assertEqual(int(perf.get("intent_queue_drained", 0)), 2)
            self.assertEqual(int(perf.get("intent_queue_depth_after_drain", -1)), 6)
            self.assertGreaterEqual(int(perf.get("event_queue_pending_after", 0)), 6)

    def test_plane_runtime_scroll_bitmap_cache_toggle_reflected_in_perf(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            app.state["scroll_bitmap_cache_enabled"] = True
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertTrue(bool(perf.get("scroll_bitmap_cache_enabled", False)))
            self.assertGreaterEqual(int(perf.get("bitmap_cache_hits", 0)), 0)
            self.assertGreaterEqual(int(perf.get("bitmap_cache_misses", 0)), 0)

    def test_plane_runtime_scrollable_plane_prefers_shift_plus_dirty_strip_compose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_camera_scroll_file(Path(td), include_fixed_title=False)
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "partial_dirty")
            self.assertGreaterEqual(int(perf.get("dirty_rect_count", 0)), 1)
            self.assertLess(int(perf.get("dirty_rect_area_px", 0)), 320 * 180)
            self.assertLess(float(perf.get("dirty_rect_area_ratio", 0.0)), 1.0)
            self.assertEqual(ctx.last_scroll_shift, (-10, 0))

    def test_plane_runtime_viewport_scroll_uses_partial_dirty_without_shift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "partial_dirty")
            self.assertGreaterEqual(int(perf.get("dirty_rect_count", 0)), 1)
            self.assertLess(int(perf.get("dirty_rect_area_px", 0)), 320 * 180)
            self.assertIsNone(ctx.last_scroll_shift)

    def test_plane_runtime_subpixel_scroll_uses_full_frame_compose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_camera_scroll_file(Path(td), include_fixed_title=False)
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -0.4, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "full_frame")
            self.assertIsNone(ctx.last_scroll_shift)

    def test_plane_runtime_overlay_scroll_avoids_shift_compose(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_camera_scroll_file(Path(td), include_fixed_title=True)
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "full_frame")
            self.assertIsNone(ctx.last_scroll_shift)

    def test_plane_runtime_invalidation_escape_hatch_forces_full_frame_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            app.state["force_full_invalidation"] = True
            app.state["force_full_invalidation_reason"] = "regression_guard"
            ctx.queue(
                HDIEvent(
                    event_id=2,
                    ts_ns=2,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "full_frame")
            self.assertTrue(bool(perf.get("invalidation_escape_hatch_used", False)))
            self.assertEqual(str(perf.get("invalidation_escape_hatch_reason", "")), "regression_guard")
            self.assertIsNone(ctx.last_scroll_shift)
            self.assertFalse(bool(app.state.get("force_full_invalidation", False)))

    def test_plane_runtime_incremental_present_toggle_forces_full_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            app.state["incremental_present_enabled"] = False
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            app.loop(ctx, 0.016)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                )
            )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertEqual(str(perf.get("compose_mode", "")), "full_frame")
            self.assertFalse(bool(perf.get("incremental_present_enabled", True)))
            self.assertIsNone(ctx.last_scroll_shift)

    def test_plane_runtime_scroll_visual_parity_incremental_vs_full(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_plane_file(Path(td))
            sequence = [
                {"x": 40.0, "y": 40.0, "delta_x": -10.0, "delta_y": 0.0},
                {"x": 40.0, "y": 40.0, "delta_x": -8.0, "delta_y": -4.0},
                {"x": 40.0, "y": 40.0, "delta_x": 5.0, "delta_y": 2.0},
            ]

            def _run(*, force_full: bool) -> list[torch.Tensor]:
                hdi = _QueuedHDI()
                ctx = AppContext(
                    matrix=WindowMatrix(180, 320),
                    hdi=hdi,  # type: ignore[arg-type]
                    sensor_manager=_NoopSensorManager(),  # type: ignore[arg-type]
                    granted_capabilities={"window.write", "hdi.mouse"},
                )
                app = load_plane_app(plane_path, handlers={})
                app.init(ctx)
                app.loop(ctx, 0.016)
                snaps: list[torch.Tensor] = [ctx.read_matrix_snapshot()]
                for i, payload in enumerate(sequence, start=1):
                    if force_full:
                        app.state["force_full_invalidation"] = True
                        app.state["force_full_invalidation_reason"] = "visual_regression_suite"
                    hdi.queue(
                        HDIEvent(
                            event_id=i,
                            ts_ns=i,
                            window_id="w",
                            device="mouse",
                            event_type="scroll",
                            status="OK",
                            payload=dict(payload),
                        )
                    )
                    app.loop(ctx, 0.016)
                    snaps.append(ctx.read_matrix_snapshot())
                return snaps

            incremental_snaps = _run(force_full=False)
            full_snaps = _run(force_full=True)
            self.assertEqual(len(incremental_snaps), len(full_snaps))
            for lhs, rhs in zip(incremental_snaps, full_snaps):
                self.assertTrue(torch.equal(lhs, rhs))

    def test_plane_runtime_coalesces_scroll_events_and_preserves_phases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_hook_plane_file(Path(td))
            calls: list[dict[str, Any]] = []

            def _on_scroll(event_ctx, state):
                _ = state
                calls.append(dict(event_ctx.get("payload", {})))

            app = load_plane_app(plane_path, handlers={"handlers::on_scroll": _on_scroll})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="trackpad",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 20.0, "y": 20.0, "delta_x": -4.0, "delta_y": -2.0, "phase": "changed"},
                )
            )
            ctx.queue(
                HDIEvent(
                    event_id=2,
                    ts_ns=2,
                    window_id="w",
                    device="trackpad",
                    event_type="scroll",
                    status="OK",
                    payload={
                        "x": 22.0,
                        "y": 21.0,
                        "delta_x": -6.0,
                        "delta_y": -3.0,
                        "phase": "ended",
                        "momentum_phase": "none",
                    },
                )
            )
            app.loop(ctx, 0.016)

            self.assertEqual(len(calls), 1)
            payload = calls[0]
            self.assertEqual(int(payload.get("coalesced_count", 0)), 2)
            self.assertAlmostEqual(float(payload.get("delta_x", 0.0)), -6.0, places=6)
            self.assertAlmostEqual(float(payload.get("delta_y", 0.0)), -3.0, places=6)
            self.assertEqual(str(payload.get("coalesce_mode", "")), "latest")
            self.assertEqual(str(payload.get("phase", "")), "ended")
            self.assertEqual(str(payload.get("momentum_phase", "")), "none")

            perf = app.state.get("perf", {})
            self.assertEqual(int(perf.get("scroll_events", 0)), 2)
            self.assertEqual(int(perf.get("scroll_events_coalesced", 0)), 1)

    def test_plane_runtime_adaptive_event_budget_drains_bursts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_hook_plane_file(Path(td))
            app = load_plane_app(plane_path, handlers={"handlers::on_scroll": lambda event_ctx, state: None})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            for i in range(300):
                ctx.queue(
                    HDIEvent(
                        event_id=i + 1,
                        ts_ns=i + 1,
                        window_id="w",
                        device="trackpad",
                        event_type="scroll",
                        status="OK",
                        payload={"x": 20.0, "y": 20.0, "delta_x": -1.0, "delta_y": -1.0, "phase": "changed"},
                    )
                )
            app.loop(ctx, 0.016)
            perf = app.state.get("perf", {})
            self.assertGreaterEqual(int(perf.get("event_budget", 0)), 300)
            self.assertEqual(int(perf.get("events_processed", 0)), 300)
            self.assertEqual(int(perf.get("event_queue_pending_after", -1)), 0)

    def test_plane_runtime_event_order_digest_is_deterministic_for_same_burst(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_scroll_hook_plane_file(Path(td))

            def _run_once() -> str:
                app = load_plane_app(plane_path, handlers={})
                ctx = _FakeCtx(width=320, height=180)
                app.init(ctx)
                for i in range(96):
                    ctx.queue(
                        HDIEvent(
                            event_id=i + 1,
                            ts_ns=i + 1,
                            window_id="w",
                            device="mouse",
                            event_type="pointer_move",
                            status="OK",
                            payload={"x": 16.0 + float(i % 9), "y": 12.0 + float(i % 7)},
                        )
                    )
                app.loop(ctx, 0.016)
                perf = app.state.get("perf", {})
                return str(perf.get("event_order_digest", ""))

            first = _run_once()
            second = _run_once()
            self.assertEqual(first, second)

    def test_plane_runtime_supports_v2_attachment_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plane_path = _build_plane_v2_multi_file(Path(td))
            app = load_plane_app(plane_path, handlers={})
            ctx = _FakeCtx(width=320, height=180)
            app.init(ctx)
            self.assertEqual(app._ui_page.ir_version, "planes-v2")  # type: ignore[attr-defined]

            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="scroll",
                    status="OK",
                    payload={"x": 40.0, "y": 40.0, "delta_x": -100.0, "delta_y": -60.0},
                )
            )
            app.loop(ctx, 0.016)
            world = next((comp for comp in ctx.mounted if comp.component_id == "world_panel"), None)
            overlay = next((comp for comp in ctx.mounted if comp.component_id == "overlay_text"), None)
            self.assertIsNotNone(world)
            self.assertIsNotNone(overlay)
            assert world is not None
            assert overlay is not None
            self.assertAlmostEqual(float(world.position.x), 100.0, places=6)
            self.assertAlmostEqual(float(world.position.y), 60.0, places=6)
            self.assertAlmostEqual(float(overlay.position.x), 12.0, places=6)
            self.assertAlmostEqual(float(overlay.position.y), 8.0, places=6)


if __name__ == "__main__":
    unittest.main()
