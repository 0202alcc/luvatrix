from __future__ import annotations

import unittest

from luvatrix_core.core.debug_capture import (
    REQUIRED_REPLAY_MANIFEST_KEYS,
    ReplayInputEvent,
    build_replay_manifest,
    compute_replay_ordering_digest,
    debug_capture_platform_capability_matrix,
    evaluate_replay_determinism,
)


class DebugReplayContractTests(unittest.TestCase):
    def test_replay_manifest_has_required_fields(self) -> None:
        manifest = build_replay_manifest(
            session_id="replay-001",
            seed=1337,
            platform="macos",
            ordering_digest="abc123",
            event_count=3,
            recorded_at_utc="2026-03-05T20:30:00Z",
        )
        for key in REQUIRED_REPLAY_MANIFEST_KEYS:
            self.assertIn(key, manifest)

    def test_replay_digest_is_deterministic_for_same_event_sequence(self) -> None:
        events = (
            ReplayInputEvent(sequence=1, timestamp_ms=1000, event_type="mouse.down", payload_digest="d1"),
            ReplayInputEvent(sequence=2, timestamp_ms=1016, event_type="mouse.up", payload_digest="d2"),
            ReplayInputEvent(sequence=3, timestamp_ms=1032, event_type="key.down", payload_digest="d3"),
        )
        self.assertEqual(compute_replay_ordering_digest(events), compute_replay_ordering_digest(events))

    def test_replay_determinism_flags_mismatch(self) -> None:
        events = (
            ReplayInputEvent(sequence=1, timestamp_ms=1000, event_type="mouse.down", payload_digest="d1"),
            ReplayInputEvent(sequence=2, timestamp_ms=1016, event_type="mouse.up", payload_digest="d2"),
        )
        result = evaluate_replay_determinism(
            session_id="replay-002",
            seed=42,
            platform="macos",
            events=events,
            expected_digest="not-the-right-digest",
        )
        self.assertFalse(result.deterministic)
        self.assertEqual(result.event_count, 2)

    def test_replay_non_macos_is_explicit_stub(self) -> None:
        matrix = debug_capture_platform_capability_matrix()
        self.assertIn("debug.replay.stub", matrix["windows"]["declared_capabilities"])
        self.assertIn("debug.replay.stub", matrix["linux"]["declared_capabilities"])


if __name__ == "__main__":
    unittest.main()
