from __future__ import annotations

import unittest

from luvatrix_core.core.debug_capture import (
    REQUIRED_RECORDING_MANIFEST_KEYS,
    RecordingBudgetEnvelope,
    build_recording_manifest,
    evaluate_recording_budget,
)


class DebugRecordingContractTests(unittest.TestCase):
    def test_debug_recording_manifest_has_required_fields(self) -> None:
        manifest = build_recording_manifest(
            session_id="session-001",
            route="app.home",
            revision="r42",
            started_at_utc="2026-03-05T15:30:00Z",
            stopped_at_utc="2026-03-05T15:31:00Z",
            provenance_id="run-abc",
            frame_count=1800,
        )
        for key in REQUIRED_RECORDING_MANIFEST_KEYS:
            self.assertIn(key, manifest)

    def test_debug_recording_budget_passes_within_envelope(self) -> None:
        envelope = RecordingBudgetEnvelope(
            start_overhead_ms=5.0,
            stop_overhead_ms=5.0,
            steady_overhead_ms=1.0,
        )
        result = evaluate_recording_budget(
            envelope=envelope,
            observed_start_overhead_ms=4.0,
            observed_stop_overhead_ms=3.0,
            observed_steady_overhead_ms=0.5,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.exceeded_limits, ())

    def test_debug_recording_budget_flags_exceeded_limits(self) -> None:
        envelope = RecordingBudgetEnvelope(
            start_overhead_ms=5.0,
            stop_overhead_ms=5.0,
            steady_overhead_ms=1.0,
        )
        result = evaluate_recording_budget(
            envelope=envelope,
            observed_start_overhead_ms=7.0,
            observed_stop_overhead_ms=6.0,
            observed_steady_overhead_ms=1.5,
        )
        self.assertFalse(result.passed)
        self.assertEqual(
            result.exceeded_limits,
            ("start_overhead_ms", "stop_overhead_ms", "steady_overhead_ms"),
        )


if __name__ == "__main__":
    unittest.main()
