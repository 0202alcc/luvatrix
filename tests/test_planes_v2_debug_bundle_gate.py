from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "ops/ci/r040_macos_debug_menu_functional_smoke.py"


def test_planes_v2_debug_bundle_gate_has_bundle_export_action() -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "debug.menu.bundle.export" in source
    assert "debug.menu.capture.screenshot" in source


def test_planes_v2_debug_replay_gate_has_replay_and_frame_step_actions() -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "debug.menu.replay.start" in source
    assert "debug.menu.frame.step" in source
