from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_planes_v2_spec_gate_has_f027_training_fields() -> None:
    spec_doc = (ROOT / "docs/planes_v2_protocol_foundation.md").read_text(encoding="utf-8")
    assert "hello_plane" in spec_doc
    assert "coordinate_playground" in spec_doc
    assert "Coordinate ambiguity" in spec_doc
    assert "Non-deterministic coordinate placement" in spec_doc


def test_planes_v2_contract_gate_includes_canonical_basis_aliases() -> None:
    spec_doc = (ROOT / "docs/planes_v2_protocol_foundation.md").read_text(encoding="utf-8")
    assert "\"canonical_basis\"" in spec_doc
    assert "\"x\": \"u_basis\"" in spec_doc
    assert "\"i_hat\": \"u_basis\"" in spec_doc
    assert "cartesian_center" in spec_doc
