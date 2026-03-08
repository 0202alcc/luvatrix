from __future__ import annotations

import hashlib
import json

from luvatrix_ui.planes_protocol import compile_monolith_to_canonical_ir, compile_split_to_canonical_ir


def _monolith_payload() -> dict[str, object]:
    return {
        "planes_protocol_version": "0.1.0",
        "app": {
            "id": "com.example.uf029.parity",
            "title": "Parity",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "plane": {
            "id": "world",
            "default_frame": "screen_tl",
            "background": {"color": "#111111"},
        },
        "components": [
            {
                "id": "world_rect",
                "type": "text",
                "position": {"x": 10, "y": 20, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 120},
                    "height": {"unit": "px", "value": 30},
                },
                "z_index": 1,
                "component_local_z": 1,
                "props": {"text": "world"},
            },
            {
                "id": "hud",
                "type": "text",
                "attachment_kind": "camera_overlay",
                "position": {"x": 3, "y": 5, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 60},
                    "height": {"unit": "px", "value": 20},
                },
                "z_index": 9,
                "component_local_z": 9,
                "props": {"text": "hud"},
            },
        ],
    }


def _split_payload() -> dict[str, object]:
    return {
        "planes_protocol_version": "0.2.0-dev",
        "app": {
            "id": "com.example.uf029.parity",
            "title": "Parity",
            "icon": "assets/icon.svg",
            "web": {"tab_title": None, "tab_icon": None},
        },
        "planes": [
            {
                "id": "world",
                "default_frame": "screen_tl",
                "background": {"color": "#111111"},
                "plane_global_z": 0,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 1920},
                    "height": {"unit": "px", "value": 1080},
                },
            }
        ],
        "routes": [{"id": "main", "default": True, "active_planes": ["world"]}],
        "components": [
            {
                "id": "world_rect",
                "type": "text",
                "attachment_kind": "plane",
                "attach_to": "world",
                "position": {"x": 10, "y": 20, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 120},
                    "height": {"unit": "px", "value": 30},
                },
                "z_index": 1,
                "component_local_z": 1,
                "props": {"text": "world"},
            },
            {
                "id": "hud",
                "type": "text",
                "attachment_kind": "camera_overlay",
                "position": {"x": 3, "y": 5, "frame": "screen_tl"},
                "size": {
                    "width": {"unit": "px", "value": 60},
                    "height": {"unit": "px", "value": 20},
                },
                "z_index": 9,
                "component_local_z": 9,
                "props": {"text": "hud"},
            },
        ],
    }


def _digest(page: object) -> str:
    from luvatrix_ui.ui_ir import UIIRPage

    assert isinstance(page, UIIRPage)
    payload = {
        "ir_version": page.ir_version,
        "ordering_contract_version": page.ordering_contract_version,
        "active_plane_ids": list(page.active_plane_ids),
        "components": [
            {
                "id": c.component_id,
                "attachment_kind": c.attachment_kind,
                "plane_id": c.plane_id,
                "stable_order_key": list(c.stable_order_key),
                "world_bounds": [c.world_bounds.x, c.world_bounds.y, c.world_bounds.width, c.world_bounds.height],
            }
            for c in page.components
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_planes_parity_equivalence_monolith_and_split_have_same_digest() -> None:
    split_page = compile_split_to_canonical_ir(_split_payload(), matrix_width=640, matrix_height=360)
    monolith_page = compile_monolith_to_canonical_ir(_monolith_payload(), matrix_width=640, matrix_height=360)
    assert _digest(split_page) == _digest(monolith_page)


def test_planes_parity_equivalence_overlay_semantics_are_preserved() -> None:
    monolith_page = compile_monolith_to_canonical_ir(_monolith_payload(), matrix_width=640, matrix_height=360)
    world = next(c for c in monolith_page.components if c.component_id == "world_rect")
    hud = next(c for c in monolith_page.components if c.component_id == "hud")
    assert world.attachment_kind == "plane"
    assert hud.attachment_kind == "camera_overlay"
    assert world.stable_order_key < hud.stable_order_key
