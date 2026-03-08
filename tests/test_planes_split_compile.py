from __future__ import annotations

from luvatrix_ui.planes_protocol import compile_split_to_canonical_ir


def _split_payload() -> dict[str, object]:
    return {
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.uf029.split",
            "title": "UF029 Split",
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
                "id": "overlay",
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
        "routes": [{"id": "main", "default": True, "active_planes": ["world", "overlay"]}],
        "scripts": [{"id": "handlers", "lang": "python", "src": "scripts/handlers.py"}],
        "components": [
            {
                "id": "tile",
                "type": "text",
                "attachment_kind": "plane",
                "attach_to": "world",
                "component_local_z": 3,
                "position": {"x": 2, "y": 4, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 64},
                    "height": {"unit": "px", "value": 16},
                },
                "z_index": 3,
                "props": {"text": "world"},
            },
            {
                "id": "hud",
                "type": "text",
                "attachment_kind": "camera_overlay",
                "component_local_z": 4,
                "position": {"x": 1, "y": 1, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 32},
                    "height": {"unit": "px", "value": 12},
                },
                "z_index": 4,
                "props": {"text": "hud"},
            },
        ],
    }


def test_planes_split_compile_emits_canonical_ir_contract() -> None:
    page = compile_split_to_canonical_ir(_split_payload(), matrix_width=640, matrix_height=360)
    assert page.ir_version == "planes-v2"
    assert page.ordering_contract_version == "plane-z-local-z-overlay-v1"
    assert set(page.active_plane_ids) == {"world", "overlay"}


def test_planes_split_compile_preserves_overlay_ranking() -> None:
    page = compile_split_to_canonical_ir(_split_payload(), matrix_width=640, matrix_height=360)
    tile = next(c for c in page.components if c.component_id == "tile")
    hud = next(c for c in page.components if c.component_id == "hud")
    assert tile.attachment_kind == "plane"
    assert hud.attachment_kind == "camera_overlay"
    assert tile.stable_order_key < hud.stable_order_key
