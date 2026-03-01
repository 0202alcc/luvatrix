from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest

from luvatrix_core.core.hdi_thread import HDIEvent
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
        self._events: list[HDIEvent] = []

    def begin_ui_frame(self, renderer, *, content_width_px, content_height_px, clear_color) -> None:
        _ = (renderer, content_width_px, content_height_px)
        self.begin_calls += 1
        self.clear = clear_color

    def mount_component(self, component) -> None:
        self.mounted.append(component)

    def finalize_ui_frame(self) -> None:
        self.finalize_calls += 1

    def poll_hdi_events(self, max_events: int):
        _ = max_events
        out = list(self._events)
        self._events = []
        return out

    def queue(self, event: HDIEvent) -> None:
        self._events.append(event)


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
                "props": {"text": "hello", "font_size_px": 16},
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


def _build_plane_camera_scroll_file(root: Path) -> Path:
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
            },
            {
                "id": "fixed_title",
                "type": "text",
                "position": {"x": 12, "y": 8},
                "size": {"width": {"unit": "px", "value": 120}, "height": {"unit": "px", "value": 24}},
                "z_index": 10,
                "props": {"text": "fixed", "camera_fixed": True},
            },
        ],
    }
    plane_path = root / "plane_camera_scroll.json"
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
            self.assertAlmostEqual(float(content_mount.position.x), -30.0, places=6)  # viewport x=10 minus scroll_x=40
            self.assertAlmostEqual(float(content_mount.position.y), -13.0, places=6)  # viewport y=12 minus scroll_y=25

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


if __name__ == "__main__":
    unittest.main()
