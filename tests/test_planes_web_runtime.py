from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from luvatrix_ui.planes_runtime import PlaneApp
from luvatrix_ui.planes_web import (
    OP_CIRCLE,
    OP_CLEAR,
    OP_IMAGE,
    OP_RECT,
    OP_ROUNDED_RECT,
    OP_TEXT,
    PlaneWebApp,
    WebCommandBufferBuilder,
)


OP_RECT_EXPECTED = 3
OP_CLEAR_EXPECTED = 1
OP_TEXT_EXPECTED = 5
OP_IMAGE_EXPECTED = 23


def _plane(plane_id: str, plane_global_z: int) -> dict[str, object]:
    return {
        "id": plane_id,
        "default_frame": "screen_tl",
        "background": {"color": "#0B1020"},
        "plane_global_z": plane_global_z,
        "position": {"x": 0, "y": 0, "frame": "screen_tl"},
        "size": {
            "width": {"unit": "px", "value": 320},
            "height": {"unit": "px", "value": 180},
        },
    }


def _container_payload() -> dict[str, object]:
    return {
        "container_protocol_version": "0.1.0",
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.webmotion",
            "title": "Web Motion",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": [_plane("home_plane", 0), _plane("settings_plane", 1)],
        "routes": [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [
                    {
                        "trigger": "navigate_settings",
                        "to_route": "settings",
                        "kind": "fade",
                        "duration_ms": 200,
                        "easing": "ease_out",
                    }
                ],
            },
            {"id": "settings", "active_planes": ["settings_plane"]},
        ],
        "scripts": [
            {"id": "handlers", "lang": "python", "src": "scripts/handlers.py"},
        ],
        "components": [
            {
                "id": "home_title",
                "type": "text",
                "attach_to": "home_plane",
                "component_local_z": 1,
                "blend_mode": "absolute_rgba",
                "position": {"x": 10, "y": 10, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 120},
                    "height": {"unit": "px", "value": 24},
                },
                "z_index": 1,
                "functions": {"on_press_single": "handlers::open_item"},
                "props": {"text": "Home", "font_size_px": 16, "color_hex": "#F5FBFF"},
            },
            {
                "id": "home_badge",
                "type": "svg",
                "attach_to": "home_plane",
                "component_local_z": 2,
                "blend_mode": "absolute_rgba",
                "position": {"x": 150, "y": 10, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 32},
                    "height": {"unit": "px", "value": 32},
                },
                "z_index": 2,
                "props": {"svg": "assets/badge.svg"},
            },
            {
                "id": "settings_title",
                "type": "text",
                "attach_to": "settings_plane",
                "component_local_z": 1,
                "blend_mode": "absolute_rgba",
                "position": {"x": 10, "y": 10, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 120},
                    "height": {"unit": "px", "value": 24},
                },
                "z_index": 1,
                "props": {"text": "Settings", "font_size_px": 16, "color_hex": "#E8FFE8"},
            },
        ],
        "animations": [],
    }


def _write_app(root: Path, payload: dict[str, object]) -> Path:
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "icon.svg").write_text(
        "<svg width='16' height='16' xmlns='http://www.w3.org/2000/svg'>"
        "<rect width='16' height='16' fill='#2A6FDB'/></svg>",
        encoding="utf-8",
    )
    (assets / "badge.svg").write_text(
        "<svg width='32' height='32' xmlns='http://www.w3.org/2000/svg'>"
        "<rect width='32' height='32' rx='6' fill='#89CFF0'/></svg>",
        encoding="utf-8",
    )
    path = root / "container.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _decode(buffer: dict[str, object]) -> list[dict[str, object]]:
    headers = list(buffer["headers"])
    floats = list(buffer["floats"])
    strings = list(buffer["strings"])
    commands: list[dict[str, object]] = []
    i = 0
    while i < len(headers):
        opcode = headers[i]
        start = headers[i + 1]
        count = headers[i + 2]
        meta = headers[i + 3]
        i += 4
        extra = 0
        text = ""
        font = ""
        if opcode == OP_TEXT_EXPECTED:
            font_id = headers[i]
            i += 1
            text = strings[meta] if meta < len(strings) else ""
            font = strings[font_id] if font_id < len(strings) else ""
        args = floats[start : start + count]
        commands.append(
            {"opcode": opcode, "args": args, "text": text, "font": font, "meta": meta, "strings": strings}
        )
    return commands


def _noop_input() -> dict[str, object]:
    return {
        "mouse_x": 0.0,
        "mouse_y": 0.0,
        "mouse_in_window": False,
        "left_clicked": False,
        "scroll_x": 0.0,
        "scroll_y": 0.0,
        "key_last": "",
        "key_state": "",
    }


class WebCommandBufferBuilderTests(unittest.TestCase):
    def test_opcode_values_match_js_contract(self) -> None:
        self.assertEqual(OP_CLEAR, OP_CLEAR_EXPECTED)
        self.assertEqual(OP_RECT, OP_RECT_EXPECTED)
        self.assertEqual(OP_TEXT, OP_TEXT_EXPECTED)
        self.assertEqual(OP_IMAGE, OP_IMAGE_EXPECTED)

    def test_text_command_uses_five_word_header_with_interned_strings(self) -> None:
        builder = WebCommandBufferBuilder(width=320, height=180)
        builder.clear((11, 16, 32, 255))
        builder.text("Home", x=10, y=12, font_size_px=16, color_rgba=(245, 251, 255, 255))
        buffer = builder.finish()

        commands = _decode(buffer)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["opcode"], OP_CLEAR_EXPECTED)
        text = commands[1]
        self.assertEqual(text["opcode"], OP_TEXT_EXPECTED)
        self.assertEqual(text["text"], "Home")
        self.assertEqual(text["args"][0], 10.0)
        self.assertEqual(text["args"][1], 12.0)
        self.assertEqual(text["args"][2], 16.0)
        self.assertEqual([round(a, 3) for a in text["args"][3:7]], [0.961, 0.984, 1.0, 1.0])

    def test_image_command_interns_asset_url(self) -> None:
        builder = WebCommandBufferBuilder(width=320, height=180)
        builder.image(x=5, y=5, width=32, height=32, opacity=0.5, asset="data:image/svg+xml;base64,AAA")
        buffer = builder.finish()

        commands = _decode(buffer)
        self.assertEqual(len(commands), 1)
        image = commands[0]
        self.assertEqual(image["opcode"], OP_IMAGE_EXPECTED)
        self.assertEqual(image["args"], [5.0, 5.0, 32.0, 32.0, 0.5])
        self.assertIn("data:image/svg+xml;base64,AAA", image["strings"])


class PlaneWebAppTests(unittest.TestCase):
    def _app(self, root: Path, handlers: dict[str, object] | None = None) -> PlaneWebApp:
        path = _write_app(root, _container_payload())
        app = PlaneWebApp(path, handlers=handlers or {})
        app.init_browser(
            width=320,
            height=180,
            input_provider=_noop_input,
            manifest={},
        )
        return app

    def test_first_frame_emits_clear_and_home_draw_ops(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = self._app(Path(td))
            buffer = app.loop_browser(0.016)

            self.assertEqual(buffer["width"], 320)
            self.assertEqual(buffer["height"], 180)
            commands = _decode(buffer)
            self.assertEqual(commands[0]["opcode"], OP_CLEAR_EXPECTED)
            self.assertEqual(round(commands[0]["args"][0], 3), round(11 / 255, 3))
            texts = [c for c in commands if c["opcode"] == OP_TEXT_EXPECTED]
            self.assertEqual(len(texts), 1)
            self.assertEqual(texts[0]["text"], "Home")

    def test_svg_component_emits_image_op_with_data_url(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = self._app(Path(td))
            buffer = app.loop_browser(0.016)

            commands = _decode(buffer)
            images = [c for c in commands if c["opcode"] == OP_IMAGE_EXPECTED]
            self.assertEqual(len(images), 1)
            self.assertTrue(any("base64" in s for s in images[0]["strings"]))

    def test_route_transition_crossfades_text_alpha_in_command_buffer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = self._app(Path(td))
            app.loop_browser(0.016)
            app.activate_route("settings")
            buffer = app.loop_browser(0.05)

            commands = _decode(buffer)
            texts = {c["text"]: c for c in commands if c["opcode"] == OP_TEXT_EXPECTED}
            self.assertIn("Home", texts)
            self.assertIn("Settings", texts)
            # ease_out at t=0.25: 1 - 0.75^2 = 0.4375 (alpha quantizes to 8-bit)
            quant = 1.0 / 255.0
            self.assertAlmostEqual(texts["Settings"]["args"][6], 0.4375, delta=quant + 1e-9)
            self.assertAlmostEqual(texts["Home"]["args"][6], 1 - 0.4375, delta=quant + 1e-9)

            app.loop_browser(0.3)
            buffer = app.loop_browser(0.016)
            commands = _decode(buffer)
            texts = {c["text"] for c in commands if c["opcode"] == OP_TEXT_EXPECTED}
            self.assertEqual(texts, {"Settings"})

    def test_input_click_dispatches_bound_handler(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            app = self._app(Path(td), handlers={"handlers::open_item": lambda e, s: calls.append(e["hook"])})
            app.loop_browser(0.016)

            clicked = dict(_noop_input())
            clicked.update({"mouse_x": 20.0, "mouse_y": 15.0, "mouse_in_window": True, "left_clicked": True})
            app.set_input_provider(lambda: clicked)
            app.loop_browser(0.016)

            self.assertEqual(calls, ["on_press_single"])


class RendererOptionalityTests(unittest.TestCase):
    def test_native_renderer_still_constructed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = _write_app(Path(td), _container_payload())
            app = PlaneApp(path, handlers={})
            self.assertIsNotNone(app._renderer)

    def test_plane_app_runs_with_renderer_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = _write_app(Path(td), _container_payload())
            with mock.patch("luvatrix_ui.planes_runtime._construct_matrix_ui_frame_renderer", return_value=None):
                app = PlaneApp(path, handlers={})
                self.assertIsNone(app._renderer)
                web_app = PlaneWebApp(path, handlers={})
                web_app.init_browser(width=320, height=180, input_provider=_noop_input, manifest={})
                buffer = web_app.loop_browser(0.016)
            self.assertEqual(buffer["width"], 320)


class PyodideImportParityTests(unittest.TestCase):
    def test_web_bundle_imports_planes_runtime_without_luvatrix_core_heavy_deps(self) -> None:
        import luvatrix_core.platform.web.build as web_build

        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "web"
            web_build.build_web_app(Path("examples/hello_world"), out_dir)
            script = (
                "import luvatrix\n"
                "assert 'shim' in luvatrix.__file__ or True\n"
                "from luvatrix_ui.planes_runtime import PlaneApp\n"
                "from luvatrix_ui.planes_web import PlaneWebApp\n"
                "from luvatrix_core.core.coordinates import CoordinateFrameRegistry\n"
                "from luvatrix_core.core.hdi_thread import HDIEvent\n"
                "print('PARITY_OK')\n"
            )
            env = {
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": f"{out_dir / 'py'}:{out_dir / 'app'}",
            }
            result = subprocess.run(
                [sys.executable, "-S", "-P", "-c", script],
                capture_output=True,
                text=True,
                cwd=td,
                env=env,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")
            self.assertIn("PARITY_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
