from __future__ import annotations

import json
from pathlib import Path

import pytest

from luvatrix_ui.planes_protocol import PlanesValidationError
from luvatrix_ui.planes_v2_validator import render_diagnostics, validate_split_schema_bundle, validate_split_schema_documents


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_split_schema_documents_valid_minimal() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": ["camera", "world"],
    }
    planes = [
        {"id": "camera", "kind": "camera", "k_hat_index": 0, "default_frame": "screen_tl"},
        {"id": "world", "kind": "world", "k_hat_index": -1, "default_frame": "world_tl"},
    ]
    routes = [{"id": "default"}]
    frames = [{"id": "screen_tl"}, {"id": "world_tl"}]

    result = validate_split_schema_documents(manifest, planes, routes, frames, strict=True)
    assert result.valid is True
    assert result.diagnostics == ()


def test_split_schema_documents_missing_required_field_raises_in_strict_mode() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "planes": ["camera"],
    }
    planes = [{"id": "camera", "kind": "camera", "k_hat_index": 0, "default_frame": "screen_tl"}]

    with pytest.raises(PlanesValidationError, match="schema.required_string"):
        validate_split_schema_documents(manifest, planes, [], [], strict=True)


def test_cross_file_invariant_camera_plane_exists_and_kind_enforced() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": ["camera"],
    }
    planes = [{"id": "camera", "kind": "world", "k_hat_index": -1, "default_frame": "screen_tl"}]

    with pytest.raises(PlanesValidationError, match="invariant.camera.kind"):
        validate_split_schema_documents(manifest, planes, [], [{"id": "screen_tl"}], strict=True)


def test_cross_file_invariant_world_plane_requires_negative_k_hat_index() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": ["camera", "world"],
    }
    planes = [
        {"id": "camera", "kind": "camera", "k_hat_index": 0, "default_frame": "screen_tl"},
        {"id": "world", "kind": "world", "k_hat_index": 1, "default_frame": "world_tl"},
    ]
    frames = [{"id": "screen_tl"}, {"id": "world_tl"}]

    with pytest.raises(PlanesValidationError, match="invariant.world.k_hat_index"):
        validate_split_schema_documents(manifest, planes, [], frames, strict=True)


def test_cross_file_invariant_rejects_attachment_cycles() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": ["camera", "a", "b"],
    }
    planes = [
        {"id": "camera", "kind": "camera", "k_hat_index": 0, "default_frame": "screen_tl"},
        {"id": "a", "kind": "world", "k_hat_index": -1, "default_frame": "screen_tl", "attach_to": "b"},
        {"id": "b", "kind": "world", "k_hat_index": -2, "default_frame": "screen_tl", "attach_to": "a"},
    ]
    frames = [{"id": "screen_tl"}]

    with pytest.raises(PlanesValidationError, match="invariant.planes.attachment_cycle"):
        validate_split_schema_documents(manifest, planes, [], frames, strict=True)


def test_cross_file_invariant_route_startup_and_frame_refs() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": ["camera"],
        "startup_route_id": "missing_route",
    }
    planes = [{"id": "camera", "kind": "camera", "k_hat_index": 0, "default_frame": "screen_tl"}]
    routes = [{"id": "default", "active_planes": ["camera"], "startup_frame_id": "missing_frame"}]
    frames = [{"id": "screen_tl"}]

    with pytest.raises(PlanesValidationError, match="invariant.routes.startup_frame_ref"):
        validate_split_schema_documents(manifest, planes, routes, frames, strict=True)


def test_split_schema_documents_collects_diagnostics_in_permissive_mode() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "",
        "planes": [],
    }
    result = validate_split_schema_documents(manifest, [], [], [], strict=False)
    assert result.valid is False
    assert len(result.diagnostics) >= 2


def test_permissive_compatibility_window_converts_errors_to_warnings() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": ["camera"],
        "compatibility_window": True,
    }
    planes = [{"id": "camera", "kind": "camera", "k_hat_index": 1, "default_frame": "missing"}]
    result = validate_split_schema_documents(
        manifest,
        planes,
        routes=[],
        frames=[],
        strict=False,
        permissive_compatibility_window=True,
    )
    assert result.valid is True
    assert result.diagnostics
    assert all(item.level == "warning" for item in result.diagnostics)
    assert all(item.code.startswith("permissive.") for item in result.diagnostics)


def test_render_diagnostics_is_deterministically_sorted() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "camera",
        "planes": [],
    }
    result = validate_split_schema_documents(manifest, [], [], [], strict=False)
    rendered = render_diagnostics(result)
    assert rendered == tuple(sorted(rendered))


def test_split_schema_bundle_loads_files_and_validates(tmp_path: Path) -> None:
    _write(
        tmp_path / "manifest.json",
        {
            "planes_protocol_version": "0.2.0-dev",
            "camera_plane_id": "camera",
            "planes": ["camera"],
        },
    )
    _write(
        tmp_path / "planes" / "camera.json",
        {"id": "camera", "kind": "camera", "k_hat_index": 0, "default_frame": "screen_tl"},
    )

    result = validate_split_schema_bundle(tmp_path, strict=True)
    assert result.valid is True


def test_split_schema_bundle_requires_manifest_file(tmp_path: Path) -> None:
    with pytest.raises(PlanesValidationError, match="missing required file"):
        validate_split_schema_bundle(tmp_path, strict=True)
