from __future__ import annotations

import pytest

from luvatrix_ui.planes_protocol import PlanesValidationError, compile_monolith_to_canonical_ir, compile_split_to_canonical_ir


def _base_app() -> dict[str, object]:
    return {
        "id": "com.example.f031",
        "title": "F031",
        "icon": "assets/icon.svg",
        "web": {"tab_title": None, "tab_icon": None},
    }


def _single_component(attach_to: str = "world") -> list[dict[str, object]]:
    return [
        {
            "id": "c1",
            "type": "text",
            "attachment_kind": "plane",
            "attach_to": attach_to,
            "position": {"x": 0, "y": 0, "frame": "screen_tl"},
            "size": {"width": {"unit": "px", "value": 10}, "height": {"unit": "px", "value": 10}},
            "z_index": 0,
            "props": {"text": "ok"},
        }
    ]


def test_legacy_planes_conformance_accepts_k_hat_index_only() -> None:
    payload = {
        "planes_protocol_version": "0.2.0-dev",
        "app": _base_app(),
        "planes": [
            {
                "id": "world",
                "default_frame": "screen_tl",
                "background": {"color": "#000000"},
                "k_hat_index": -3,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 100}, "height": {"unit": "px", "value": 100}},
            }
        ],
        "routes": [{"id": "main", "default": True, "active_planes": ["world"]}],
        "components": _single_component("world"),
        "scripts": [],
    }
    page = compile_split_to_canonical_ir(payload, matrix_width=128, matrix_height=128)
    assert page.plane_manifest[0].plane_global_z == -3


def test_planes_monolith_adapter_accepts_v2_declared_version_without_forced_rewrite() -> None:
    payload = {
        "planes_protocol_version": "0.2.0-dev",
        "app": _base_app(),
        "plane": {"id": "world", "default_frame": "screen_tl", "background": {"color": "#111111"}},
        "components": [
            {
                "id": "legacy",
                "type": "text",
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 10}, "height": {"unit": "px", "value": 10}},
                "z_index": 1,
                "props": {"text": "legacy"},
            }
        ],
    }
    page = compile_monolith_to_canonical_ir(payload, matrix_width=128, matrix_height=128)
    assert page.ir_version == "planes-v2"
    assert page.components[0].attachment_kind == "plane"
    assert page.components[0].plane_id == "world"


def test_z_index_alias_is_supported_as_depth_alias() -> None:
    payload = {
        "planes_protocol_version": "0.2.0-dev",
        "app": _base_app(),
        "planes": [
            {
                "id": "back",
                "default_frame": "screen_tl",
                "background": {"color": "#111111"},
                "z_index_alias": -5,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 100}, "height": {"unit": "px", "value": 100}},
            },
            {
                "id": "front",
                "default_frame": "screen_tl",
                "background": {"color": "#222222"},
                "plane_global_z": -1,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 100}, "height": {"unit": "px", "value": 100}},
            },
        ],
        "routes": [{"id": "main", "default": True, "active_planes": ["back", "front"]}],
        "components": _single_component("back"),
        "scripts": [],
    }
    page = compile_split_to_canonical_ir(payload, matrix_width=128, matrix_height=128)
    assert [plane.plane_id for plane in page.plane_manifest] == ["back", "front"]


def test_z_index_alias_conflict_rejected() -> None:
    payload = {
        "planes_protocol_version": "0.2.0-dev",
        "app": _base_app(),
        "planes": [
            {
                "id": "world",
                "default_frame": "screen_tl",
                "background": {"color": "#000000"},
                "k_hat_index": -2,
                "z_index_alias": -1,
                "position": {"x": 0, "y": 0, "frame": "screen_tl"},
                "size": {"width": {"unit": "px", "value": 100}, "height": {"unit": "px", "value": 100}},
            }
        ],
        "routes": [{"id": "main", "default": True, "active_planes": ["world"]}],
        "components": _single_component(),
        "scripts": [],
    }
    with pytest.raises(PlanesValidationError, match="conflicting depth aliases"):
        compile_split_to_canonical_ir(payload, matrix_width=128, matrix_height=128)
