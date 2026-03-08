from __future__ import annotations

import pytest

from luvatrix_ui.planes_protocol import PlanesValidationError
from luvatrix_ui.planes_v2_validator import validate_visual_evidence_manifest


def _valid_manifest() -> dict[str, object]:
    return {
        "entries": [
            {
                "commit_sha": "abc123",
                "command": "PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py",
                "timestamp": "2026-03-08T21:30:00Z",
                "scenario": "planes_v2_poc",
                "seed": 1337,
                "artifact_path": "artifacts/debug_menu/r040_smoke/planes_v2_poc.log",
                "artifact_digest": "sha256:11",
                "sidecar_path": "artifacts/debug_menu/r040_smoke/manifest.json",
                "sidecar_digest": "sha256:22",
            }
        ]
    }


def test_visual_evidence_manifest_valid() -> None:
    result = validate_visual_evidence_manifest(_valid_manifest(), strict=True)
    assert result.valid is True
    assert result.diagnostics == ()


def test_visual_evidence_manifest_missing_required_field_fails_in_strict_mode() -> None:
    manifest = _valid_manifest()
    manifest["entries"][0].pop("artifact_digest")  # type: ignore[index]
    with pytest.raises(PlanesValidationError, match="schema.required_string"):
        validate_visual_evidence_manifest(manifest, strict=True)


def test_visual_evidence_manifest_collects_diagnostics_in_non_strict_mode() -> None:
    manifest = _valid_manifest()
    manifest["entries"][0]["seed"] = "bad"  # type: ignore[index]
    result = validate_visual_evidence_manifest(manifest, strict=False)
    assert result.valid is False
    assert any(item.code == "evidence.entry.seed" for item in result.diagnostics)
