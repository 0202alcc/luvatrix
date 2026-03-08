from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "ci" / "uf029_generate_parity_digest.py"
SPEC = importlib.util.spec_from_file_location("uf029_generate_parity_digest", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_planes_parity_equivalence_digest_covers_required_scenarios() -> None:
    digest = MODULE.build_parity_digest()
    scenarios = {item["name"]: item for item in digest["scenarios"]}
    assert "split_vs_monolith_compile_parity_to_canonical_ir" in scenarios
    assert "overlay_parity_semantics" in scenarios


def test_planes_parity_equivalence_digest_required_scenarios_pass() -> None:
    digest = MODULE.build_parity_digest()
    scenarios = {item["name"]: item for item in digest["scenarios"]}
    assert scenarios["split_vs_monolith_compile_parity_to_canonical_ir"]["pass"] is True
    assert scenarios["overlay_parity_semantics"]["pass"] is True
