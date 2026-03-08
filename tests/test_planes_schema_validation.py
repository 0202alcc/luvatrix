from __future__ import annotations

import json
from pathlib import Path

import pytest

from luvatrix_ui.planes_protocol import PlanesValidationError
from luvatrix_ui.planes_v2_validator import validate_split_schema_bundle, validate_split_schema_documents


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


def test_split_schema_documents_collects_diagnostics_in_permissive_mode() -> None:
    manifest = {
        "planes_protocol_version": "0.2.0-dev",
        "camera_plane_id": "",
        "planes": [],
    }
    result = validate_split_schema_documents(manifest, [], [], [], strict=False)
    assert result.valid is False
    assert len(result.diagnostics) >= 2


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
