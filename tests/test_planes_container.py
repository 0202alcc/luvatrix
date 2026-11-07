from __future__ import annotations

import unittest

from luvatrix_ui.planes_container import (
    compile_container,
    validate_container_payload,
)
from luvatrix_ui.planes_protocol import PlanesValidationError, compile_planes_to_ui_ir


def _plane(plane_id: str) -> dict[str, object]:
    return {
        "id": plane_id,
        "default_frame": "screen_tl",
        "background": {"color": "#000000"},
        "plane_global_z": 0,
        "position": {"x": 0, "y": 0, "frame": "screen_tl"},
        "size": {
            "width": {"unit": "px", "value": 800},
            "height": {"unit": "px", "value": 600},
        },
    }


def _base_container() -> dict[str, object]:
    return {
        "container_protocol_version": "0.1.0",
        "app": {
            "id": "com.example.bundle",
            "title": "Bundle",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": [_plane("home_plane"), _plane("settings_plane")],
        "routes": [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [
                    {
                        "trigger": "navigate_settings",
                        "to_route": "settings",
                        "kind": "slide_left",
                        "duration_ms": 240,
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
                "position": {"x": 20, "y": 16, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 240},
                    "height": {"unit": "px", "value": 24},
                },
                "z_index": 1,
                "props": {"text": "Home"},
            },
            {
                "id": "settings_title",
                "type": "text",
                "attach_to": "settings_plane",
                "component_local_z": 1,
                "blend_mode": "absolute_rgba",
                "position": {"x": 20, "y": 16, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 240},
                    "height": {"unit": "px", "value": 24},
                },
                "z_index": 1,
                "props": {"text": "Settings"},
            },
        ],
        "animations": [
            {
                "target": "home_title",
                "trigger": "route_enter",
                "kind": "fade",
                "duration_ms": 180,
                "easing": "ease_in_out",
                "loop": "none",
                "keyframes": [
                    {"at": 0.0, "props": {"opacity": 0.0}},
                    {"at": 1.0, "props": {"opacity": 1.0}},
                ],
            }
        ],
    }


class ContainerCompileTests(unittest.TestCase):
    def test_compile_container_normalizes_routes_and_entry(self) -> None:
        compiled = compile_container(_base_container())

        self.assertEqual(compiled.entry_route, "home")
        self.assertEqual([route.id for route in compiled.routes], ["home", "settings"])
        home = compiled.routes[0]
        self.assertEqual(len(home.transitions), 1)
        transition = home.transitions[0]
        self.assertEqual(transition.trigger, "navigate_settings")
        self.assertEqual(transition.to_route, "settings")
        self.assertEqual(transition.kind, "slide_left")
        self.assertEqual(transition.duration_ms, 240)
        self.assertEqual(transition.easing, "ease_out")

    def test_compile_container_fills_transition_defaults(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [{"trigger": "go", "to_route": "settings"}],
            },
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        compiled = compile_container(payload)

        transition = compiled.routes[0].transitions[0]
        self.assertEqual(transition.kind, "fade")
        self.assertEqual(transition.duration_ms, 200)
        self.assertEqual(transition.easing, "ease_in_out")

    def test_compile_container_normalizes_animations(self) -> None:
        compiled = compile_container(_base_container())

        self.assertEqual(len(compiled.animations), 1)
        animation = compiled.animations[0]
        self.assertEqual(animation.target, "home_title")
        self.assertEqual(animation.trigger, "route_enter")
        self.assertEqual(animation.kind, "fade")
        self.assertEqual(animation.duration_ms, 180)
        self.assertEqual(animation.easing, "ease_in_out")
        self.assertEqual(animation.loop, "none")
        self.assertEqual(len(animation.keyframes), 2)
        self.assertEqual(animation.keyframes[0].at, 0.0)
        self.assertEqual(animation.keyframes[0].props, {"opacity": 0.0})

    def test_compile_container_planes_payload_excludes_container_keys(self) -> None:
        compiled = compile_container(_base_container())

        self.assertNotIn("container_protocol_version", compiled.planes_payload)
        self.assertNotIn("animations", compiled.planes_payload)
        for route in compiled.planes_payload["routes"]:
            self.assertNotIn("transitions", route)

        page = compile_planes_to_ui_ir(
            compiled.planes_payload,
            matrix_width=800,
            matrix_height=600,
        )
        self.assertEqual(page.active_route_id, "home")


class ContainerValidationTests(unittest.TestCase):
    def test_rejects_duplicate_route_ids(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {"id": "home", "default": True, "active_planes": ["home_plane"]},
            {"id": "home", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_transition_to_unknown_route(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [{"trigger": "go", "to_route": "missing"}],
            },
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_route_without_default(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {"id": "home", "active_planes": ["home_plane"]},
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_multiple_default_routes(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {"id": "home", "default": True, "active_planes": ["home_plane"]},
            {"id": "settings", "default": True, "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_route_referencing_unknown_plane(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {"id": "home", "default": True, "active_planes": ["nope_plane"]},
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_unknown_transition_kind(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [{"trigger": "go", "to_route": "settings", "kind": "explode"}],
            },
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_non_positive_transition_duration(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [{"trigger": "go", "to_route": "settings", "duration_ms": 0}],
            },
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_unknown_easing(self) -> None:
        payload = _base_container()
        payload["routes"] = [
            {
                "id": "home",
                "default": True,
                "active_planes": ["home_plane"],
                "transitions": [{"trigger": "go", "to_route": "settings", "easing": "bounce"}],
            },
            {"id": "settings", "active_planes": ["settings_plane"]},
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_animation_targeting_unknown_component(self) -> None:
        payload = _base_container()
        payload["animations"] = [
            {"target": "ghost_button", "trigger": "route_enter", "kind": "fade", "duration_ms": 100}
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_unknown_animation_kind(self) -> None:
        payload = _base_container()
        payload["animations"] = [
            {"target": "home_title", "trigger": "route_enter", "kind": "explode", "duration_ms": 100}
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_non_positive_animation_duration(self) -> None:
        payload = _base_container()
        payload["animations"] = [
            {"target": "home_title", "trigger": "route_enter", "kind": "fade", "duration_ms": -5}
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_unknown_loop_mode(self) -> None:
        payload = _base_container()
        payload["animations"] = [
            {
                "target": "home_title",
                "trigger": "route_enter",
                "kind": "fade",
                "duration_ms": 100,
                "loop": "forever",
            }
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_keyframe_at_outside_unit_interval(self) -> None:
        payload = _base_container()
        payload["animations"] = [
            {
                "target": "home_title",
                "trigger": "route_enter",
                "kind": "fade",
                "duration_ms": 100,
                "keyframes": [{"at": 1.5, "props": {"opacity": 1.0}}],
            }
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_rejects_descending_keyframe_progression(self) -> None:
        payload = _base_container()
        payload["animations"] = [
            {
                "target": "home_title",
                "trigger": "route_enter",
                "kind": "fade",
                "duration_ms": 100,
                "keyframes": [
                    {"at": 0.5, "props": {"opacity": 0.5}},
                    {"at": 0.0, "props": {"opacity": 0.0}},
                ],
            }
        ]

        with self.assertRaises(PlanesValidationError):
            compile_container(payload)

    def test_validate_container_payload_passes_wellformed_document(self) -> None:
        self.assertIsNone(validate_container_payload(_base_container()))


if __name__ == "__main__":
    unittest.main()
