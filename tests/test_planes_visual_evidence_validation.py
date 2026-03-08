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
                "artifact_type": "screenshot",
            },
            {
                "commit_sha": "abc123",
                "command": "cmd",
                "timestamp": "2026-03-08T21:30:00Z",
                "scenario": "planes_v2_poc",
                "seed": 1337,
                "artifact_path": "a",
                "artifact_digest": "sha256:a",
                "sidecar_path": "sa",
                "sidecar_digest": "sha256:sa",
                "artifact_type": "recording",
            },
            {
                "commit_sha": "abc123",
                "command": "cmd",
                "timestamp": "2026-03-08T21:30:00Z",
                "scenario": "planes_v2_poc",
                "seed": 1337,
                "artifact_path": "b",
                "artifact_digest": "sha256:b",
                "sidecar_path": "sb",
                "sidecar_digest": "sha256:sb",
                "artifact_type": "replay_digest",
            },
            {
                "commit_sha": "abc123",
                "command": "cmd",
                "timestamp": "2026-03-08T21:30:00Z",
                "scenario": "planes_v2_poc",
                "seed": 1337,
                "artifact_path": "c",
                "artifact_digest": "sha256:c",
                "sidecar_path": "sc",
                "sidecar_digest": "sha256:sc",
                "artifact_type": "frame_step_snapshot",
            },
            {
                "commit_sha": "abc123",
                "command": "cmd",
                "timestamp": "2026-03-08T21:30:00Z",
                "scenario": "planes_v2_poc",
                "seed": 1337,
                "artifact_path": "d",
                "artifact_digest": "sha256:d",
                "sidecar_path": "sd",
                "sidecar_digest": "sha256:sd",
                "artifact_type": "debug_bundle",
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


def test_visual_evidence_manifest_requires_full_artifact_matrix() -> None:
    manifest = _valid_manifest()
    manifest["entries"] = manifest["entries"][:2]  # type: ignore[index]
    with pytest.raises(PlanesValidationError, match="evidence.matrix.required_artifact"):
        validate_visual_evidence_manifest(manifest, strict=True)
