from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from luvatrix_ui.planes_static_compile import compile_static_bundle, is_static_eligible


def _js_container_payload() -> dict[str, object]:
    return {
        "container_protocol_version": "0.1.0",
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.jshandlers",
            "title": "JS Handlers",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": [
            {
                "id": "home_plane",
                "default_frame": "screen_tl",
                "background": {"color": "#0B1020"},
                "plane_global_z": 0,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 320},
                    "height": {"unit": "px", "value": 180},
                },
            },
        ],
        "routes": [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [],
            },
        ],
        "scripts": [
            {"id": "ui", "lang": "javascript", "src": "scripts/ui.js"},
        ],
        "components": [
            {
                "id": "go_button",
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
                "functions": {"on_press_single": "ui::say_hello"},
                "props": {"text": "Run JS", "font_size_px": 14, "color_hex": "#F5FBFF"},
            },
        ],
        "animations": [],
    }


def _python_script_payload() -> dict[str, object]:
    payload = _js_container_payload()
    payload["scripts"] = [{"id": "handlers", "lang": "python", "src": "scripts/h.py"}]
    payload["components"][0]["functions"] = {"on_press_single": "handlers::go"}
    return payload


def _write_app(root: Path, payload: dict[str, object]) -> Path:
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "icon.svg").write_text(
        "<svg width='16' height='16' xmlns='http://www.w3.org/2000/svg'>"
        "<rect width='16' height='16' fill='#2A6FDB'/></svg>",
        encoding="utf-8",
    )
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "ui.js").write_text(
        "export function say_hello(event, state) { state.called = true; }\n",
        encoding="utf-8",
    )
    (scripts / "h.py").write_text("def go(event, state):\n    pass\n", encoding="utf-8")
    path = root / "container.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class JsHandlerEligibilityTests(unittest.TestCase):
    def test_javascript_scripts_keep_container_static_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _js_container_payload())
            self.assertTrue(is_static_eligible(root / "container.json"))

    def test_python_scripts_disqualify_static(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _python_script_payload())
            self.assertFalse(is_static_eligible(root / "container.json"))


class JsHandlerBundleTests(unittest.TestCase):
    def test_bundle_serializes_js_scripts_with_resolved_src(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _js_container_payload())
            bundle = compile_static_bundle(root / "container.json")

            self.assertEqual(len(bundle["scripts"]), 1)
            script = bundle["scripts"][0]
            self.assertEqual(script["id"], "ui")
            self.assertEqual(script["lang"], "javascript")
            self.assertEqual(script["src"], "app/scripts/ui.js")

    def test_bundle_components_carry_script_binding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _js_container_payload())
            bundle = compile_static_bundle(root / "container.json")

            button = bundle["components"][0]
            self.assertEqual(button["handler"], "ui::say_hello")
            self.assertIsNone(button["trigger"])

    def test_bundle_is_json_serializable_with_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _js_container_payload())
            bundle = compile_static_bundle(root / "container.json")
            self.assertEqual(json.loads(json.dumps(bundle))["scripts"][0]["id"], "ui")


class StaticCoreHandlerDispatchTests(unittest.TestCase):
    def test_node_static_core_dispatches_js_handler_on_press(self) -> None:
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for JS dispatch tests")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _js_container_payload())
            bundle = compile_static_bundle(root / "container.json")

            repo_root = Path(__file__).resolve().parents[1]
            result = subprocess.run(
                [
                    node,
                    str(repo_root / "tools" / "web" / "static_core_dispatch_test.mjs"),
                    "--core",
                    str(
                        repo_root
                        / "luvatrix_core"
                        / "platform"
                        / "web"
                        / "runtime_assets"
                        / "runtime"
                        / "static-core.js"
                    ),
                    "--handlers",
                    str(repo_root / "tests" / "fixtures" / "static_js_handlers.js"),
                    "--bundle",
                    json.dumps(bundle),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(
                result.returncode, 0, msg=f"node stderr: {result.stderr}\nstdout: {result.stdout}"
            )
            self.assertIn("DISPATCH_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
