from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ops" / "ci" / "m008_perf_gate.py"
SPEC = importlib.util.spec_from_file_location("m008_perf_gate", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class M008PerfGateTests(unittest.TestCase):
    def test_perf_gate_smoke_contract(self) -> None:
        summary = MODULE.run_perf_gate(
            samples=12,
            budget_p95_ms=1000.0,
            budget_jitter_ms=1000.0,
            min_incremental_pct=0.0,
            max_visual_mismatch_frames=0,
        )
        self.assertTrue(bool(summary.get("passed", False)))
        self.assertTrue(bool(summary.get("deterministic", False)))
        result = summary.get("result", {})
        self.assertIsInstance(result, dict)
        self.assertGreaterEqual(float(result.get("p95_ms", -1.0)), 0.0)
        self.assertGreaterEqual(float(result.get("jitter_ms", -1.0)), 0.0)
        self.assertGreaterEqual(float(result.get("incremental_present_pct", -1.0)), 0.0)
        visual = summary.get("visual_parity", {})
        self.assertIsInstance(visual, dict)
        self.assertTrue(bool(visual.get("passed", False)))
        self.assertEqual(int(visual.get("mismatch_frames", -1)), 0)


if __name__ == "__main__":
    unittest.main()
