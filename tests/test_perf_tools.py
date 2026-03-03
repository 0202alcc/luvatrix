from __future__ import annotations

import unittest

from tools.perf.assert_thresholds import assert_thresholds
from tools.perf.run_suite import run_suite


class PerfToolsTests(unittest.TestCase):
    def test_run_suite_exports_deterministic_shape(self) -> None:
        summary = run_suite(
            scenario="all_interactive",
            samples=4,
            width=640,
            height=360,
        )
        self.assertEqual(summary.get("suite"), "all_interactive")
        scenarios = summary.get("scenarios", {})
        self.assertIsInstance(scenarios, dict)
        for name in ("idle", "scroll", "drag", "resize_stress"):
            self.assertIn(name, scenarios)
            payload = scenarios[name]
            self.assertTrue(bool(payload.get("deterministic", False)))
            result = payload.get("result", {})
            self.assertGreaterEqual(float(result.get("p95_frame_total_ms", -1.0)), 0.0)
            self.assertGreaterEqual(int(result.get("p95_copy_bytes", -1)), 0)

    def test_assert_thresholds_contract(self) -> None:
        baseline = run_suite(
            scenario="all_interactive",
            samples=3,
            width=320,
            height=180,
        )
        contract = {
            "scenarios": {
                "idle": {"p95_frame_total_ms": 1000.0, "jitter_ms": 1000.0, "p95_copy_bytes": 10000000, "p95_copy_count": 100},
                "scroll": {"p95_frame_total_ms": 1000.0, "jitter_ms": 1000.0, "p95_copy_bytes": 10000000, "p95_copy_count": 100},
                "drag": {"p95_frame_total_ms": 1000.0, "jitter_ms": 1000.0, "p95_copy_bytes": 10000000, "p95_copy_count": 100},
                "resize_stress": {"p95_frame_total_ms": 1000.0, "jitter_ms": 1000.0, "p95_copy_bytes": 10000000, "p95_copy_count": 100},
            }
        }
        out = assert_thresholds("baseline_contract", baseline, contract)
        self.assertTrue(bool(out.get("passed", False)))
        self.assertEqual(out.get("errors"), [])


if __name__ == "__main__":
    unittest.main()
