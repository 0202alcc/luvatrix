from __future__ import annotations

import unittest

from luvatrix_ui.planes_protocol import (
    PlanesValidationError,
    compile_planes_to_ui_ir,
    resolve_web_metadata,
    validate_planes_payload,
)


def _base_payload() -> dict[str, object]:
    return {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "com.example",
            "title": "Demo",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {
            "id": "main",
            "default_frame": "screen_tl",
            "background": {"color": "#000000"},
        },
        "scripts": [
            {"id": "handlers", "lang": "python", "src": "scripts/handlers.py"},
        ],
        "components": [
            {
                "id": "title",
                "type": "text",
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "vw", "value": 100},
                    "height": {"unit": "px", "value": 24},
                },
                "z_index": 1,
                "functions": {"on_press_single": "handlers::open_item"},
                "props": {"text": "Hello"},
            }
        ],
    }


def _base_payload_v2() -> dict[str, object]:
    return {
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.v2",
            "title": "Demo v2",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": [
            {
                "id": "world",
                "default_frame": "screen_tl",
                "background": {"color": "#000000"},
                "plane_global_z": 0,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 800},
                    "height": {"unit": "px", "value": 600},
                },
            },
            {
                "id": "overlay_plane",
                "default_frame": "screen_tl",
                "background": {"color": "#000000"},
                "plane_global_z": 2,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 800},
                    "height": {"unit": "px", "value": 600},
                },
            },
        ],
        "routes": [{"id": "main", "default": True, "active_planes": ["world", "overlay_plane"]}],
        "scripts": [
            {"id": "handlers", "lang": "python", "src": "scripts/handlers.py"},
        ],
        "components": [
            {
                "id": "world_svg",
                "type": "svg",
                "attachment_kind": "plane",
                "attach_to": "world",
                "component_local_z": 1,
                "blend_mode": "absolute_rgba",
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "vw", "value": 100},
                    "height": {"unit": "vh", "value": 100},
                },
                "z_index": 1,
                "props": {"svg": "assets/logo.svg"},
            },
            {
                "id": "title_overlay",
                "type": "text",
                "attachment_kind": "camera_overlay",
                "component_local_z": 5,
                "blend_mode": "absolute_rgba",
                "position": {"x": 10, "y": 10, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 240},
                    "height": {"unit": "px", "value": 24},
                },
                "z_index": 5,
                "functions": {"on_press_single": "handlers::open_item"},
                "props": {"text": "overlay"},
            },
        ],
    }


class PlanesProtocolTests(unittest.TestCase):
    def test_web_metadata_inherits_title_and_icon(self) -> None:
        meta = resolve_web_metadata(_base_payload()["app"])  # type: ignore[arg-type]
        self.assertEqual(meta.tab_title, "Demo")
        self.assertEqual(meta.tab_icon, "assets/icon.svg")

    def test_validate_accepts_minimal_valid_payload(self) -> None:
        validate_planes_payload(_base_payload())

    def test_validate_rejects_unknown_hook(self) -> None:
        payload = _base_payload()
        payload["components"][0]["functions"] = {"on_magic": "handlers::x"}  # type: ignore[index]
        with self.assertRaises(PlanesValidationError):
            validate_planes_payload(payload)

    def test_validate_rejects_unknown_script_target(self) -> None:
        payload = _base_payload()
        payload["components"][0]["functions"] = {"on_press_single": "missing::x"}  # type: ignore[index]
        with self.assertRaises(PlanesValidationError):
            validate_planes_payload(payload)

    def test_validate_viewport_requires_clip_and_content(self) -> None:
        payload = _base_payload()
        payload["components"].append(  # type: ignore[union-attr]
            {
                "id": "v",
                "type": "viewport",
                "position": {"x": 10, "y": 10},
                "size": {
                    "width": {"unit": "px", "value": 100},
                    "height": {"unit": "px", "value": 100},
                },
                "z_index": 0,
                "props": {"clip": False},
            }
        )
        with self.assertRaises(PlanesValidationError):
            validate_planes_payload(payload)

    def test_compile_produces_ui_ir_with_normalized_units(self) -> None:
        page = compile_planes_to_ui_ir(_base_payload(), matrix_width=640, matrix_height=360)
        self.assertEqual(page.ir_version, "planes-v0")
        self.assertEqual(page.page_id, "main")
        self.assertEqual(len(page.components), 1)
        self.assertAlmostEqual(page.components[0].width, 640.0)
        self.assertEqual(page.components[0].interactions[0].event, "on_press_single")

    def test_compile_svg_creates_svg_asset(self) -> None:
        payload = _base_payload()
        payload["components"].append(  # type: ignore[union-attr]
            {
                "id": "logo",
                "type": "svg",
                "position": {"x": 2, "y": 2},
                "size": {
                    "width": {"unit": "pt", "value": 72},
                    "height": {"unit": "cm", "value": 2.54},
                },
                "z_index": 2,
                "props": {"svg": "assets/logo.svg"},
            }
        )
        page = compile_planes_to_ui_ir(payload, matrix_width=640, matrix_height=360)
        logo = next(c for c in page.components if c.component_id == "logo")
        self.assertIsNotNone(logo.asset)
        assert logo.asset is not None
        self.assertEqual(logo.asset.kind, "svg")

    def test_validate_accepts_v2_payload(self) -> None:
        validate_planes_payload(_base_payload_v2())

    def test_validate_accepts_anchor_string_units(self) -> None:
        payload = _base_payload_v2()
        payload["components"][1]["anchor"] = {  # type: ignore[index]
            "x": "50%",
            "y": "1.25em",
            "frame_reference": "cartesian_center",
        }
        validate_planes_payload(payload)

    def test_validate_rejects_invalid_anchor_unit(self) -> None:
        payload = _base_payload_v2()
        payload["components"][1]["anchor"] = {"x": "50percent", "y": "50%"}  # type: ignore[index]
        with self.assertRaises(PlanesValidationError):
            validate_planes_payload(payload)

    def test_validate_rejects_invalid_anchor_frame(self) -> None:
        payload = _base_payload_v2()
        payload["components"][1]["anchor"] = {"x": "50%", "y": "50%", "frame_reference": ""}  # type: ignore[index]
        with self.assertRaises(PlanesValidationError):
            validate_planes_payload(payload)

    def test_compile_uses_cartesian_center_default_when_frames_omitted(self) -> None:
        payload = _base_payload_v2()
        payload["planes"][0].pop("default_frame")  # type: ignore[index]
        payload["planes"][1].pop("default_frame")  # type: ignore[index]
        page = compile_planes_to_ui_ir(payload, matrix_width=640, matrix_height=360)
        self.assertEqual(page.default_frame, "cartesian_center")

    def test_compile_accepts_auto_component_size_units(self) -> None:
        payload = _base_payload_v2()
        payload["components"][1]["size"] = {  # type: ignore[index]
            "width": "auto",
            "height": "auto",
        }
        page = compile_planes_to_ui_ir(payload, matrix_width=640, matrix_height=360)
        overlay = next(c for c in page.components if c.component_id == "title_overlay")
        self.assertEqual(float(overlay.width), 0.0)
        self.assertEqual(float(overlay.height), 0.0)
        self.assertTrue(bool(overlay.style.get("auto_size_width", False)))
        self.assertTrue(bool(overlay.style.get("auto_size_height", False)))

    def test_compile_component_percent_dimensions_are_parent_relative(self) -> None:
        payload = _base_payload_v2()
        payload["components"][0]["size"] = {  # type: ignore[index]
            "width": {"unit": "%", "value": 50},
            "height": {"unit": "%", "value": 25},
        }
        page = compile_planes_to_ui_ir(payload, matrix_width=640, matrix_height=360)
        world = next(c for c in page.components if c.component_id == "world_svg")
        self.assertAlmostEqual(float(world.width), 400.0)
        self.assertAlmostEqual(float(world.height), 150.0)

    def test_compile_accepts_unitized_string_size_shorthand(self) -> None:
        payload = _base_payload_v2()
        payload["planes"][0]["size"] = {"width": "100vw", "height": "100vh"}  # type: ignore[index]
        payload["components"][1]["size"] = {"width": "50vw", "height": "10vh"}  # type: ignore[index]
        page = compile_planes_to_ui_ir(payload, matrix_width=640, matrix_height=360)
        world_plane = next(p for p in page.plane_manifest if p.plane_id == "world")
        overlay = next(c for c in page.components if c.component_id == "title_overlay")
        self.assertAlmostEqual(float(world_plane.resolved_bounds.width), 640.0)
        self.assertAlmostEqual(float(world_plane.resolved_bounds.height), 360.0)
        self.assertAlmostEqual(float(overlay.width), 320.0)
        self.assertAlmostEqual(float(overlay.height), 36.0)

    def test_compile_accepts_unitized_string_positions(self) -> None:
        payload = _base_payload_v2()
        payload["components"][0]["position"] = {"x": "50%", "y": "25%", "frame": "screen_tl"}  # type: ignore[index]
        payload["planes"][1]["position"] = {"x": "10vw", "y": "5vh", "frame": "screen_tl"}  # type: ignore[index]
        page = compile_planes_to_ui_ir(payload, matrix_width=640, matrix_height=360)
        world = next(c for c in page.components if c.component_id == "world_svg")
        overlay_plane = next(p for p in page.plane_manifest if p.plane_id == "overlay_plane")
        self.assertAlmostEqual(float(world.position.x), 400.0)
        self.assertAlmostEqual(float(world.position.y), 150.0)
        self.assertAlmostEqual(float(overlay_plane.resolved_position.x), 64.0)
        self.assertAlmostEqual(float(overlay_plane.resolved_position.y), 18.0)

    def test_compile_v2_produces_planes_v2_ir(self) -> None:
        page = compile_planes_to_ui_ir(_base_payload_v2(), matrix_width=640, matrix_height=360)
        self.assertEqual(page.ir_version, "planes-v2")
        self.assertEqual(page.ordering_contract_version, "plane-z-local-z-overlay-v1")
        self.assertEqual(set(page.active_plane_ids), {"world", "overlay_plane"})
        self.assertEqual(len(page.plane_manifest), 2)
        world = next(c for c in page.components if c.component_id == "world_svg")
        overlay = next(c for c in page.components if c.component_id == "title_overlay")
        self.assertEqual(world.attachment_kind, "plane")
        self.assertEqual(world.plane_id, "world")
        self.assertEqual(overlay.attachment_kind, "camera_overlay")

    def test_validate_v2_rejects_missing_attachment_kind_in_strict_mode(self) -> None:
        payload = _base_payload_v2()
        payload["components"][0].pop("attachment_kind")  # type: ignore[index]
        with self.assertRaises(PlanesValidationError):
            validate_planes_payload(payload, strict=True)


if __name__ == "__main__":
    unittest.main()
