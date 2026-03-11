from __future__ import annotations

import hashlib
import json
import unittest

from tools.perf.assert_thresholds import assert_thresholds
from tools.perf.r041_go_no_go import evaluate_go_no_go
from tools.perf.run_suite import run_suite


class PerfToolsTests(unittest.TestCase):
    @staticmethod
    def _trace_fingerprint(summary: dict) -> str:
        scenarios = summary.get("scenarios", {})
        payload = {}
        for name in ("idle", "scroll", "drag", "resize_stress_fullframe_allowed"):
            result = scenarios.get(name, {}).get("result", {})
            payload[name] = {
                "event_order_digest_trace": result.get("event_order_digest_trace", []),
                "event_poll_trace": result.get("event_poll_trace", []),
                "event_payload_digest_trace": result.get("event_payload_digest_trace", []),
            }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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
        for name in ("idle", "scroll", "drag", "resize_stress_fullframe_allowed"):
            self.assertIn(name, scenarios)
            payload = scenarios[name]
            self.assertTrue(bool(payload.get("deterministic", False)))
            result = payload.get("result", {})
            self.assertGreaterEqual(float(result.get("p95_frame_total_ms", -1.0)), 0.0)
            self.assertGreaterEqual(int(result.get("p95_copy_bytes", -1)), 0)
            self.assertGreaterEqual(float(result.get("p95_dirty_area_ratio", -1.0)), 0.0)
            self.assertGreaterEqual(float(result.get("incremental_present_pct", -1.0)), 0.0)
            self.assertGreaterEqual(float(result.get("full_present_pct", -1.0)), 0.0)

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
                "resize_stress_fullframe_allowed": {
                    "p95_frame_total_ms": 1000.0,
                    "jitter_ms": 1000.0,
                    "p95_copy_bytes": 10000000,
                    "p95_copy_count": 100,
                },
            }
        }
        out = assert_thresholds("baseline_contract", baseline, contract)
        self.assertTrue(bool(out.get("passed", False)))
        self.assertEqual(out.get("errors"), [])

    def test_run_suite_input_burst_exports_latency_and_replay_contract(self) -> None:
        summary = run_suite(
            scenario="input_burst",
            samples=16,
            width=640,
            height=360,
        )
        payload = summary.get("scenarios", {}).get("input_burst", {})
        self.assertTrue(bool(payload.get("deterministic", False)))
        result = payload.get("result", {})
        self.assertGreaterEqual(float(result.get("p95_events_processed", -1.0)), 0.0)
        self.assertGreaterEqual(float(result.get("p95_event_budget", -1.0)), 0.0)
        self.assertGreaterEqual(float(result.get("p95_pending_after", -1.0)), 0.0)
        self.assertIsInstance(result.get("event_order_digest_trace", []), list)
        self.assertIsInstance(result.get("event_poll_trace", []), list)

    def test_run_suite_sensor_polling_exports_provider_class_latency(self) -> None:
        summary = run_suite(
            scenario="sensor_polling",
            samples=8,
            width=640,
            height=360,
        )
        payload = summary.get("scenarios", {}).get("sensor_polling", {})
        self.assertTrue(bool(payload.get("deterministic", False)))
        result = payload.get("result", {})
        self.assertGreaterEqual(float(result.get("polling_cpu_cost_ms", -1.0)), 0.0)
        self.assertGreaterEqual(float(result.get("jitter_ms", -1.0)), 0.0)
        classes = result.get("provider_latency_by_class", {})
        self.assertIsInstance(classes, dict)
        self.assertIn("fast_path", classes)
        self.assertIn("cached_path", classes)

    def test_run_suite_seed_fidelity_distinguishes_cross_seed_and_keeps_same_seed_stable(self) -> None:
        run_a = run_suite(
            scenario="all_interactive",
            samples=24,
            width=640,
            height=360,
            seed=1337,
        )
        run_b = run_suite(
            scenario="all_interactive",
            samples=24,
            width=640,
            height=360,
            seed=1337,
        )
        run_c = run_suite(
            scenario="all_interactive",
            samples=24,
            width=640,
            height=360,
            seed=2024,
        )
        self.assertEqual(self._trace_fingerprint(run_a), self._trace_fingerprint(run_b))
        self.assertNotEqual(self._trace_fingerprint(run_a), self._trace_fingerprint(run_c))
        self.assertEqual(run_a.get("provenance", {}).get("seed_list", []), [1337])

    def test_r041_go_no_go_harness_returns_contract_shape(self) -> None:
        perf = run_suite(
            scenario="drag",
            samples=8,
            width=640,
            height=360,
            seed=1337,
        )
        contract = {
            "milestone_id": "R-041",
            "scenario": "drag",
            "thresholds": {
                "p95_frame_total_ms_max": 1000.0,
                "p99_frame_total_ms_max": 1000.0,
                "jitter_ms_max": 1000.0,
                "p95_input_to_present_ms_max": 1000.0,
                "full_present_pct_max": 100.0,
                "p95_dirty_area_ratio_max": 1.0,
            },
            "weights": {
                "frame_latency": 0.35,
                "jitter": 0.2,
                "input_to_present": 0.2,
                "dirty_rect_efficiency": 0.15,
                "incremental_present": 0.1,
            },
            "go_threshold": 10.0,
        }
        verdict = evaluate_go_no_go(perf_summary=perf, contract=contract)
        self.assertEqual(verdict.get("milestone_id"), "R-041")
        self.assertEqual(verdict.get("scenario"), "drag")
        self.assertIn(verdict.get("decision"), {"GO", "NO-GO"})
        self.assertIsInstance(verdict.get("metric_scores"), dict)
        self.assertIsInstance(verdict.get("blockers"), list)

    def test_r041_go_no_go_blocks_on_hard_caps(self) -> None:
        perf = {
            "scenarios": {
                "drag": {
                    "deterministic": True,
                    "result": {
                        "p95_frame_total_ms": 25.0,
                        "p99_frame_total_ms": 30.0,
                        "jitter_ms": 4.0,
                        "p95_input_to_present_ms": 50.0,
                        "full_present_pct": 25.0,
                        "incremental_present_pct": 75.0,
                        "p95_dirty_area_ratio": 0.3,
                    },
                }
            }
        }
        contract = {
            "milestone_id": "R-041",
            "scenario": "drag",
            "thresholds": {
                "p95_frame_total_ms_max": 16.7,
                "p99_frame_total_ms_max": 22.0,
                "jitter_ms_max": 5.5,
                "p95_input_to_present_ms_max": 33.4,
                "full_present_pct_max": 8.0,
                "p95_dirty_area_ratio_max": 0.42,
            },
            "weights": {
                "frame_latency": 0.35,
                "jitter": 0.2,
                "input_to_present": 0.2,
                "dirty_rect_efficiency": 0.15,
                "incremental_present": 0.1,
            },
            "go_threshold": 90.0,
        }
        verdict = evaluate_go_no_go(perf_summary=perf, contract=contract)
        self.assertEqual(verdict.get("decision"), "NO-GO")
        blockers = verdict.get("blockers", [])
        self.assertTrue(any("full_present_pct hard cap exceeded" in str(item) for item in blockers))


if __name__ == "__main__":
    unittest.main()
