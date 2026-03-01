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


if __name__ == "__main__":
    unittest.main()
