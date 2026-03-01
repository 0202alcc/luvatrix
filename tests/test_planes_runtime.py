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


if __name__ == "__main__":
    unittest.main()
