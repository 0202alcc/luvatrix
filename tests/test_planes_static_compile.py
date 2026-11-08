from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from luvatrix_core.platform.web.build import build_web_app
from luvatrix_ui.planes_container import PlanesValidationError, compile_container
from luvatrix_ui.planes_runtime import PlaneApp
from luvatrix_ui.planes_static_compile import (
    compile_static_bundle,
    is_static_eligible,
)


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


def _static_container_payload() -> dict[str, object]:
    return {
        "container_protocol_version": "0.1.0",
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.staticmotion",
            "title": "Static Motion",
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
            {
                "id": "settings",
                "active_planes": ["settings_plane"],
                "transitions": [
                    {
                        "trigger": "navigate_home",
                        "to_route": "home",
                        "kind": "slide_left",
                        "duration_ms": 300,
                        "easing": "ease_in_out",
                    }
                ],
            },
        ],
        "scripts": [],
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
                "functions": {"on_press_single": "trigger:navigate_settings"},
                "props": {"text": "Home", "font_size_px": 16, "color_hex": "#F5FBFF"},
            },
            {
                "id": "home_badge",
                "type": "svg",
                "attach_to": "home_plane",
                "component_local_z": 2,
                "blend_mode": "absolute_rgba",
                "position": {"x": 150, "y": 12, "frame": "screen_tl"},
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
                "functions": {"on_press_single": "trigger:navigate_home"},
                "props": {"text": "Settings", "font_size_px": 16, "color_hex": "#E8FFE8"},
            },
        ],
        "animations": [
            {
                "target": "settings_title",
                "trigger": "route_enter",
                "kind": "fade",
                "duration_ms": 100,
                "easing": "linear",
                "loop": "none",
                "keyframes": [
                    {"at": 0.0, "props": {"opacity": 0.0}},
                    {"at": 1.0, "props": {"opacity": 1.0}},
                ],
            }
        ],
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


def _write_app_dir(root: Path) -> Path:
    """Full app dir (app.toml + entrypoint + container.json)."""
    app_dir = root / "static_app"
    app_dir.mkdir(parents=True, exist_ok=True)
    container_path = _write_app(app_dir, _static_container_payload())
    (app_dir / "app.toml").write_text(
        'app_id = "examples.static_motion"\n'
        'protocol_version = "3"\n'
        'entrypoint = "app_main:create"\n'
        'required_capabilities = ["window.write"]\n'
        '\n[web]\nstatic_container = "container.json"\n',
        encoding="utf-8",
    )
    (app_dir / "app_main.py").write_text(
        "def create():\n"
        "    raise RuntimeError('static app entrypoint is not exercised natively')\n",
        encoding="utf-8",
    )
    return app_dir


class TriggerBindingValidationTests(unittest.TestCase):
    def test_trigger_binding_to_known_trigger_compiles(self) -> None:
        compiled = compile_container(_static_container_payload())
        self.assertEqual(compiled.routes[0].transitions[0].trigger, "navigate_settings")

    def test_trigger_binding_to_unknown_trigger_rejected(self) -> None:
        payload = _static_container_payload()
        payload["components"][0]["functions"] = {"on_press_single": "trigger:missing"}
        with self.assertRaises(PlanesValidationError):
            compile_container(payload)


class NativeTriggerDispatchTests(unittest.TestCase):
    def test_click_on_trigger_bound_component_activates_route(self) -> None:
        from luvatrix_core.core.hdi_thread import HDIEvent

        with tempfile.TemporaryDirectory() as td:
            path = _write_app(Path(td), _static_container_payload())
            app = PlaneApp(path, handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)
            self.assertEqual(app.state.get("active_route"), "home")

            ctx.queue(
                HDIEvent(
                    event_id=1,
                    ts_ns=1,
                    window_id="w",
                    device="mouse",
                    event_type="click",
                    status="OK",
                    payload={"x": 20.0, "y": 15.0},
                )
            )
            app.loop(ctx, 0.016)

            self.assertEqual(app.state.get("active_route"), "settings")
            transition = app.state["perf"]["active_transition"]
            self.assertIsNotNone(transition)
            self.assertEqual(transition["to_route"], "settings")


class StaticEligibilityTests(unittest.TestCase):
    def test_trigger_only_container_is_static_eligible(self) -> None:
        self.assertTrue(is_static_eligible(_static_container_payload()))

    def test_script_bound_container_is_not_static_eligible(self) -> None:
        payload = _static_container_payload()
        payload["components"][0]["functions"] = {"on_press_single": "handlers::open"}
        payload["scripts"] = [{"id": "handlers", "lang": "python", "src": "scripts/h.py"}]
        self.assertFalse(is_static_eligible(payload))

    def test_on_state_animation_disqualifies_static(self) -> None:
        payload = _static_container_payload()
        payload["animations"] = [
            {
                "target": "home_title",
                "trigger": "on_state",
                "kind": "fade",
                "duration_ms": 100,
                "state_key": "flash",
                "keyframes": [
                    {"at": 0.0, "props": {"opacity": 0.0}},
                    {"at": 1.0, "props": {"opacity": 1.0}},
                ],
            }
        ]
        self.assertFalse(is_static_eligible(payload))


class StaticBundleCompilerTests(unittest.TestCase):
    def test_bundle_serializes_routes_components_and_animations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _static_container_payload())
            bundle = compile_static_bundle(root / "container.json")

            self.assertEqual(bundle["schema_version"], 1)
            self.assertEqual(bundle["entry_route"], "home")
            self.assertEqual(len(bundle["routes"]), 2)
            home = bundle["routes"][0]
            self.assertEqual(home["transitions"][0]["trigger"], "navigate_settings")
            self.assertEqual(home["transitions"][0]["kind"], "fade")

            components = {c["id"]: c for c in bundle["components"]}
            self.assertIn("home_title", components)
            self.assertEqual(components["home_title"]["text"], "Home")
            self.assertEqual(components["home_title"]["trigger"], "navigate_settings")
            self.assertEqual(components["home_title"]["font_size_px"], 16)
            self.assertEqual(components["home_title"]["unit"], "px")
            badge = components["home_badge"]
            self.assertIn("data:image/svg+xml;base64,", badge["svg_data_url"])

            animations = bundle["animations"]
            self.assertEqual(animations[0]["target"], "settings_title")
            self.assertEqual(animations[0]["keyframes"][0]["at"], 0.0)

    def test_bundle_is_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _static_container_payload())
            bundle = compile_static_bundle(root / "container.json")
            encoded = json.dumps(bundle)
            self.assertIsInstance(encoded, str)
            self.assertEqual(json.loads(encoded)["entry_route"], "home")


class StaticBuildIntegrationTests(unittest.TestCase):
    def test_build_web_emits_static_bundle_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_dir = _write_app_dir(root)
            out = root / "web"
            result = build_web_app(app_dir, out)

            bundle_path = out / "static_bundle.json"
            self.assertTrue(bundle_path.exists())
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            self.assertEqual(bundle["entry_route"], "home")

            index = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("luvatrix-static.js", index)
            self.assertNotIn("luvatrix-web.js", index)
            self.assertTrue((out / "runtime" / "static-core.js").exists())
            self.assertTrue((out / "runtime" / "luvatrix-static.js").exists())
            _ = result


NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "node is required for JS parity tests")
class StaticCoreParityTests(unittest.TestCase):
    """The JS static core must emit byte-identical command buffers."""

    def _golden_frames(self, root: Path) -> list[dict[str, object]]:
        from luvatrix_ui.planes_web import PlaneWebApp

        app = PlaneWebApp(root / "container.json", handlers={})
        app.init_browser(
            width=320,
            height=180,
            input_provider=lambda: {
                "mouse_x": 0.0,
                "mouse_y": 0.0,
                "mouse_in_window": False,
                "left_clicked": False,
            },
            manifest={},
        )
        frames: list[dict[str, object]] = [app.loop_browser(0.016)]
        app.activate_route("settings")
        for dt in (0.05, 0.05, 0.3, 0.016):
            frames.append(app.loop_browser(dt))
        return frames

    def test_node_static_core_matches_python_golden_frames(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, _static_container_payload())
            bundle = compile_static_bundle(root / "container.json")
            golden = self._golden_frames(root)

            repo_root = Path(__file__).resolve().parents[1]
            script_path = repo_root / "tools" / "web" / "static_core_parity.mjs"
            core_path = repo_root / "luvatrix_core" / "platform" / "web" / "runtime_assets" / "runtime" / "static-core.js"
            self.assertTrue(script_path.exists(), f"missing parity script: {script_path}")
            self.assertTrue(core_path.exists(), f"missing static core: {core_path}")
            proc = subprocess.run(
                [
                    NODE,
                    str(script_path),
                    "--core",
                    str(core_path),
                    "--bundle",
                    json.dumps(bundle),
                    "--golden",
                    json.dumps(
                        [
                            {
                                "headers": list(f["headers"]),
                                "floats": list(f["floats"]),
                                "strings": list(f["strings"]),
                            }
                            for f in golden
                        ]
                    ),
                    "--ticks",
                    json.dumps([0.016, 0.05, 0.05, 0.3, 0.016]),
                    "--activate",
                    "settings",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, msg=f"node stderr: {proc.stderr}\nstdout: {proc.stdout}")
            self.assertIn("PARITY_OK", proc.stdout)

    def test_node_static_core_resolves_unitized_geometry(self) -> None:
        """vw/vh components must resolve identically to the Python compile."""
        payload = _static_container_payload()
        payload["components"][0]["size"]["width"] = {"unit": "vw", "value": 50}

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_app(root, payload)
            bundle = compile_static_bundle(root / "container.json")

            from luvatrix_ui.planes_web import PlaneWebApp

            app = PlaneWebApp(root / "container.json", handlers={})
            app.init_browser(
                width=320,
                height=180,
                input_provider=lambda: {
                    "mouse_x": 0.0,
                    "mouse_y": 0.0,
                    "mouse_in_window": False,
                    "left_clicked": False,
                },
                manifest={},
            )
            golden = [app.loop_browser(0.016)]

            repo_root = Path(__file__).resolve().parents[1]
            script_path = repo_root / "tools" / "web" / "static_core_parity.mjs"
            core_path = repo_root / "luvatrix_core" / "platform" / "web" / "runtime_assets" / "runtime" / "static-core.js"
            proc = subprocess.run(
                [
                    NODE,
                    str(script_path),
                    "--core",
                    str(core_path),
                    "--bundle",
                    json.dumps(bundle),
                    "--golden",
                    json.dumps(
                        [
                            {
                                "headers": list(f["headers"]),
                                "floats": list(f["floats"]),
                                "strings": list(f["strings"]),
                            }
                            for f in golden
                        ]
                    ),
                    "--ticks",
                    json.dumps([0.016]),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, msg=f"node stderr: {proc.stderr}\nstdout: {proc.stdout}")
            self.assertIn("PARITY_OK", proc.stdout)


class _FakeMatrix:
    width: int = 320
    height: int = 180


class _FakeCtx:
    def __init__(self) -> None:
        self.matrix = _FakeMatrix()
        self.mounted: list[object] = []
        self.begin_calls = 0
        self.finalize_calls = 0
        self._events: list[object] = []

    def begin_ui_frame(self, renderer, *, content_width_px, content_height_px, clear_color, dirty_rects=None, scroll_shift=None) -> None:
        _ = (renderer, content_width_px, content_height_px, clear_color, dirty_rects, scroll_shift)
        self.begin_calls += 1

    def mount_component(self, component) -> None:
        self.mounted.append(component)

    def finalize_ui_frame(self) -> None:
        self.finalize_calls += 1

    def poll_hdi_events(self, max_events: int):
        out = list(self._events[: max(0, int(max_events))])
        self._events = self._events[max(0, int(max_events)) :]
        return out

    def queue(self, event) -> None:
        self._events.append(event)

    def pending_hdi_events(self) -> int:
        return len(self._events)

    def consume_hdi_telemetry(self) -> dict[str, int]:
        return {}


if __name__ == "__main__":
    unittest.main()
