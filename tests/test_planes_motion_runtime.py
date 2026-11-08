from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from luvatrix_ui.planes_container import PlanesValidationError, compile_container
from luvatrix_ui.planes_runtime import PlaneApp


def _plane(plane_id: str, plane_global_z: int) -> dict[str, object]:
    return {
        "id": plane_id,
        "default_frame": "screen_tl",
        "background": {"color": "#000000"},
        "plane_global_z": plane_global_z,
        "position": {"x": 0, "y": 0, "frame": "screen_tl"},
        "size": {
            "width": {"unit": "px", "value": 320},
            "height": {"unit": "px", "value": 180},
        },
    }


def _text_component(component_id: str, plane_id: str, text: str) -> dict[str, object]:
    return {
        "id": component_id,
        "type": "text",
        "attach_to": plane_id,
        "component_local_z": 1,
        "blend_mode": "absolute_rgba",
        "position": {"x": 10, "y": 10, "frame": "screen_tl"},
        "size": {
            "width": {"unit": "px", "value": 120},
            "height": {"unit": "px", "value": 24},
        },
        "z_index": 1,
        "props": {"text": text, "font_size_px": 16, "color_hex": "#FFFFFF"},
    }


def _container_payload() -> dict[str, object]:
    return {
        "container_protocol_version": "0.1.0",
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.motion",
            "title": "Motion",
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
            _text_component("home_title", "home_plane", "Home"),
            _text_component("settings_title", "settings_plane", "Settings"),
        ],
        "animations": [],
    }


def _write_app(root: Path, payload: dict[str, object]) -> Path:
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "icon.svg").write_text(
        "<svg width='10' height='10' xmlns='http://www.w3.org/2000/svg'>"
        "<rect width='10' height='10' fill='#ffffff'/></svg>",
        encoding="utf-8",
    )
    path = root / "container.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _animation_payload() -> dict[str, object]:
    """Container without route transitions, to isolate animation behavior."""
    payload = _container_payload()
    payload["routes"] = [
        {"id": "home", "default": True, "active_planes": ["home_plane"]},
        {"id": "settings", "active_planes": ["settings_plane"]},
    ]
    return payload


def _animation(target: str, **overrides: object) -> dict[str, object]:
    animation: dict[str, object] = {
        "target": target,
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
    animation.update(overrides)
    return animation


class _FakeMatrix:
    width: int = 320
    height: int = 180


class _FakeCtx:
    def __init__(self, width: int = 320, height: int = 180) -> None:
        self.matrix = _FakeMatrix()
        self.matrix.width = width
        self.matrix.height = height
        self.mounted = []
        self.begin_calls = 0
        self.finalize_calls = 0
        self.last_dirty_rects = None

    def begin_ui_frame(self, renderer, *, content_width_px, content_height_px, clear_color, dirty_rects=None, scroll_shift=None) -> None:
        _ = (renderer, content_width_px, content_height_px, clear_color, scroll_shift)
        self.begin_calls += 1
        self.last_dirty_rects = dirty_rects

    def mount_component(self, component) -> None:
        self.mounted.append(component)

    def finalize_ui_frame(self) -> None:
        self.finalize_calls += 1

    def poll_hdi_events(self, max_events: int):
        return []

    def pending_hdi_events(self) -> int:
        return 0

    def consume_hdi_telemetry(self) -> dict[str, int]:
        return {}


def _mounted_opacities(app: PlaneApp) -> dict[str, float]:
    opacities: dict[str, float] = {}
    for m in app._mounted_last_frame:
        opacity = getattr(m, "opacity", None)
        if opacity is None:
            opacity = m.appearance.opacity
        opacities[m.component_id] = float(opacity)
    return opacities


class RouteTransitionRuntimeTests(unittest.TestCase):
    def test_activate_route_switches_active_planes_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = PlaneApp(_write_app(Path(td), _container_payload()), handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)

            app.activate_route("settings")
            self.assertEqual(app.state["active_route"], "settings")
            app.loop(ctx, 0.05)

            # During the fade transition both planes render (crossfade).
            mounted_ids = {m.component_id for m in app._mounted_last_frame}
            self.assertEqual(mounted_ids, {"home_title", "settings_title"})

            app.loop(ctx, 0.3)
            app.state["force_full_invalidation"] = True
            app.loop(ctx, 0.016)
            mounted_ids = {m.component_id for m in app._mounted_last_frame}
            self.assertEqual(mounted_ids, {"settings_title"})

    def test_activate_route_applies_container_fade_transition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = PlaneApp(_write_app(Path(td), _container_payload()), handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)

            app.activate_route("settings")
            app.loop(ctx, 0.05)

            transition = app.state["perf"]["active_transition"]
            self.assertIsNotNone(transition)
            self.assertEqual(transition["from_route"], "home")
            self.assertEqual(transition["to_route"], "settings")
            self.assertEqual(transition["kind"], "fade")
            # ease_out at t=0.25: 1 - (1 - 0.25)^2 = 0.4375
            self.assertAlmostEqual(transition["progress"], 0.4375, places=4)
            self.assertEqual(transition["duration_ms"], 200)

            opacities = _mounted_opacities(app)
            self.assertIn("settings_title", opacities)
            self.assertAlmostEqual(opacities["settings_title"], 0.4375, places=4)

    def test_activate_route_without_spec_switches_immediately(self) -> None:
        payload = _container_payload()
        payload["routes"] = [
            {"id": "home", "default": True, "active_planes": ["home_plane"]},
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            app = PlaneApp(_write_app(Path(td), payload), handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)

            app.activate_route("settings")
            app.loop(ctx, 0.016)

            self.assertIsNone(app.state["perf"]["active_transition"])
            mounted_ids = {m.component_id for m in app._mounted_last_frame}
            self.assertEqual(mounted_ids, {"settings_title"})

    def test_transition_completes_and_clears_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = PlaneApp(_write_app(Path(td), _container_payload()), handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)

            app.activate_route("settings")
            app.loop(ctx, 0.3)

            self.assertIsNone(app.state["perf"]["active_transition"])
            opacities = _mounted_opacities(app)
            self.assertAlmostEqual(opacities["settings_title"], 1.0, places=4)

    def test_transition_completion_frame_presents_settled_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = PlaneApp(_write_app(Path(td), _container_payload()), handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)

            app.activate_route("settings")
            app.loop(ctx, 0.05)
            begin_calls_after_crossfade = ctx.begin_calls

            # The completion frame must present the settled route even when
            # nothing else is dirty; the screen may not stay mid-crossfade.
            app.loop(ctx, 0.3)

            self.assertEqual(ctx.begin_calls, begin_calls_after_crossfade + 1)
            mounted_ids = {m.component_id for m in app._mounted_last_frame}
            self.assertEqual(mounted_ids, {"settings_title"})
            self.assertIsNone(app.state["perf"]["active_transition"])

    def test_transition_marks_full_frame_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app = PlaneApp(_write_app(Path(td), _container_payload()), handlers={})
            ctx = _FakeCtx()
            app.init(ctx)
            app.loop(ctx, 0.016)

            app.activate_route("settings")
            app.loop(ctx, 0.05)

            self.assertIsNotNone(ctx.last_dirty_rects)
            self.assertEqual(ctx.last_dirty_rects, [(0, 0, 320, 180)])


class ComponentAnimationRuntimeTests(unittest.TestCase):
    def _app_with_animation(self, payload_overrides: dict[str, object] | None = None):
        payload = _animation_payload()
        if payload_overrides:
            payload.update(payload_overrides)
        root = tempfile.TemporaryDirectory()
        app = PlaneApp(_write_app(Path(root.name), payload), handlers={})
        ctx = _FakeCtx()
        app.init(ctx)
        app.loop(ctx, 0.016)
        return app, ctx, root

    def test_route_enter_animation_interpolates_opacity(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [_animation("settings_title", trigger="route_enter", duration_ms=100)]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.05)

            opacities = _mounted_opacities(app)
            self.assertAlmostEqual(opacities["settings_title"], 0.5, places=4)

            app.loop(ctx, 0.05)
            opacities = _mounted_opacities(app)
            self.assertAlmostEqual(opacities["settings_title"], 1.0, places=4)

    def test_telemetry_lists_running_animation_progress(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [_animation("settings_title", trigger="route_enter", duration_ms=100)]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.05)

            progress = app.state["perf"]["animation_progress"]
            self.assertAlmostEqual(progress["settings_title"], 0.5, places=4)

            app.loop(ctx, 0.06)
            self.assertNotIn("settings_title", app.state["perf"]["animation_progress"])

    def test_animation_delay_holds_first_keyframe(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [_animation("settings_title", trigger="route_enter", duration_ms=100, delay_ms=100)]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.05)

            opacities = _mounted_opacities(app)
            self.assertAlmostEqual(opacities["settings_title"], 0.0, places=4)

            app.loop(ctx, 0.05)
            opacities = _mounted_opacities(app)
            self.assertAlmostEqual(opacities["settings_title"], 0.0, places=4)

    def test_animation_loop_repeat_wraps_progress(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [_animation("settings_title", trigger="route_enter", duration_ms=100, loop="repeat")]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.15)

            progress = app.state["perf"]["animation_progress"]["settings_title"]
            self.assertAlmostEqual(progress, 0.5, places=4)

    def test_animation_loop_ping_pong_reflects_triangle_wave(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [_animation("settings_title", trigger="route_enter", duration_ms=100, loop="ping_pong")]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.15)

            progress = app.state["perf"]["animation_progress"]["settings_title"]
            self.assertAlmostEqual(progress, 0.5, places=4)

    def test_animation_marks_component_bounds_dirty(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [_animation("settings_title", trigger="route_enter", duration_ms=200)]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.05)

            dirty = ctx.last_dirty_rects
            self.assertIsNotNone(dirty)
            self.assertTrue(any(rect[0] <= 10 and rect[1] <= 10 for rect in dirty))

    def test_on_state_animation_triggers_on_state_change(self) -> None:
        payload = _animation_payload()
        payload["animations"] = [
            _animation("settings_title", trigger="on_state", duration_ms=100, state_key="flash")
        ]
        app, ctx, root = self._app_with_animation(payload)
        with root:
            app.activate_route("settings")
            app.loop(ctx, 0.016)
            self.assertNotIn("settings_title", app.state["perf"]["animation_progress"])

            app.state["flash"] = True
            app.loop(ctx, 0.05)
            progress = app.state["perf"]["animation_progress"]
            self.assertAlmostEqual(progress["settings_title"], 0.5, places=4)

            app.state["flash"] = True
            app.loop(ctx, 0.05)
            # Same value does not restart; the animation completed and left
            # the telemetry set.
            self.assertNotIn("settings_title", app.state["perf"]["animation_progress"])


class MotionEasingTests(unittest.TestCase):
    def test_easing_curves_are_deterministic(self) -> None:
        from luvatrix_ui.planes_motion import easing_progress

        self.assertAlmostEqual(easing_progress("linear", 0.25), 0.25, places=6)
        self.assertAlmostEqual(easing_progress("ease_in", 0.5), 0.25, places=6)
        self.assertAlmostEqual(easing_progress("ease_out", 0.5), 0.75, places=6)
        self.assertAlmostEqual(easing_progress("ease_in_out", 0.5), 0.5, places=6)
        self.assertEqual(easing_progress("linear", -0.5), 0.0)
        self.assertEqual(easing_progress("linear", 1.5), 1.0)


class ContainerStateKeyValidationTests(unittest.TestCase):
    def test_on_state_animation_requires_state_key(self) -> None:
        payload = _container_payload()
        payload["animations"] = [_animation("home_title", trigger="on_state")]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_on_state_animation_with_state_key_compiles(self) -> None:
        payload = _container_payload()
        payload["animations"] = [_animation("home_title", trigger="on_state", state_key="flash")]

        compiled = compile_container(payload)
        self.assertEqual(compiled.animations[0].state_key, "flash")


if __name__ == "__main__":
    unittest.main()
