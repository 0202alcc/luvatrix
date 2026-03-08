from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_planes_ir_contract_doc_contains_required_contract_sections() -> None:
    text = (ROOT / "docs" / "planes_canonical_ir_contract.md").read_text(encoding="utf-8")
    assert "ir_version = \"planes-v2\"" in text
    assert "ordering_contract_version = \"plane-z-local-z-overlay-v1\"" in text
    assert "x/y/z -> u/v/w" in text
    assert "i_hat/j_hat/k_hat -> u_hat/v_hat/w_hat" in text


def test_planes_ir_contract_doc_contains_training_mapping_and_go_blockers() -> None:
    text = (ROOT / "docs" / "planes_canonical_ir_contract.md").read_text(encoding="utf-8")
    assert 'closeout_training_project_ids = ["camera_overlay_basics"]' in text
    assert "ordering mismatch" in text
    assert "transform mismatch" in text
    assert "hit-test mismatch" in text
