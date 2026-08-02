from __future__ import annotations

import struct
import unittest

from luvatrix_core.platform.android.hdi_source import (
    AndroidHDISource,
    android_input_telemetry,
    clear_android_input_events,
    enqueue_native_key_event,
    enqueue_native_touch_event,
)


class AndroidHDISourceTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_android_input_events()

    def test_touch_events_are_polled_as_hdi_events(self) -> None:
        enqueue_native_touch_event(7, "down", 12.5, 30.0, force=0.4, major_radius=9.0)

        events = AndroidHDISource().poll(window_active=True, ts_ns=1)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].device, "touch")
        self.assertEqual(events[0].event_type, "touch")
        self.assertEqual(events[0].payload["touch_id"], 7)
        self.assertEqual(events[0].payload["phase"], "down")
        self.assertEqual(android_input_telemetry()["active_touches"], 1)

    def test_key_events_are_polled_as_hdi_events(self) -> None:
        enqueue_native_key_event("A", "down", scan_code=29)

        events = AndroidHDISource().poll(window_active=True, ts_ns=1)

        self.assertEqual(events[0].device, "keyboard")
        self.assertEqual(events[0].event_type, "key_down")
        self.assertEqual(events[0].payload["key"], "A")
        self.assertEqual(events[0].payload["scan_code"], 29)
        self.assertEqual(android_input_telemetry()["last_key"], "A")

    def test_inactive_window_does_not_consume_events(self) -> None:
        source = AndroidHDISource()
        enqueue_native_touch_event(1, "down", 1.0, 2.0)

        self.assertEqual(source.poll(window_active=False, ts_ns=1), [])
        self.assertEqual(len(source.poll(window_active=True, ts_ns=2)), 1)

    def test_cancel_removes_active_touch(self) -> None:
        source = AndroidHDISource()
        enqueue_native_touch_event(1, "down", 1.0, 2.0)
        enqueue_native_touch_event(1, "cancel", 1.0, 2.0)

        source.poll(window_active=True, ts_ns=1)

        self.assertEqual(android_input_telemetry()["active_touches"], 0)
        self.assertEqual(android_input_telemetry()["last_phase"], "cancel")

    def test_bridge_touch_moves_are_coalesced_to_latest_per_poll(self) -> None:
        class _Bridge:
            def getWidth(self) -> int:
                return 100

            def getHeight(self) -> int:
                return 200

            def drainInputEventsJson(self) -> list[str]:
                return [
                    '{"device":"touch","touch_id":1,"phase":"move","x":10,"y":20}',
                    '{"device":"touch","touch_id":1,"phase":"move","x":30,"y":40}',
                    '{"device":"touch","touch_id":2,"phase":"move","x":50,"y":60}',
                ]

        events = AndroidHDISource(_Bridge(), logical_width=10, logical_height=20).poll(window_active=True, ts_ns=1)

        self.assertEqual(len(events), 2)
        by_id = {event.payload["touch_id"]: event.payload for event in events}
        self.assertEqual(by_id[1]["x"], 3.0)
        self.assertEqual(by_id[1]["y"], 4.0)
        self.assertEqual(by_id[2]["x"], 5.0)
        self.assertEqual(by_id[2]["y"], 6.0)

    def test_binary_bridge_preserves_edges_and_coalesces_touch_moves(self) -> None:
        class _Bridge:
            def getWidth(self) -> int:
                return 100

            def getHeight(self) -> int:
                return 200

            def drainInputEventsBinary(self) -> bytes:
                return _binary_input_packets(
                    _binary_packet(device=1, phase=1, touch_id=7, x=10.0, y=20.0),
                    _binary_packet(device=1, phase=0, touch_id=7, x=30.0, y=40.0),
                    _binary_packet(device=1, phase=0, touch_id=7, x=50.0, y=60.0),
                    _binary_packet(device=1, phase=2, touch_id=7, x=50.0, y=60.0),
                    _binary_packet(device=2, phase=1, key="KEYCODE_A", scan_code=29),
                )

        events = AndroidHDISource(_Bridge(), logical_width=10, logical_height=20).poll(window_active=True, ts_ns=1)

        self.assertEqual(
            [(event.device, event.event_type, event.payload.get("phase")) for event in events],
            [
                ("touch", "touch", "down"),
                ("touch", "touch", "move"),
                ("touch", "touch", "up"),
                ("keyboard", "key_down", "down"),
            ],
        )
        self.assertEqual(events[1].payload["x"], 5.0)
        self.assertEqual(events[1].payload["y"], 6.0)
        self.assertEqual(events[-1].payload["key"], "KEYCODE_A")
        self.assertEqual(events[-1].payload["scan_code"], 29)


def _binary_input_packets(*packets: bytes) -> bytes:
    return struct.pack("<4sHH", b"LVXI", 1, len(packets)) + b"".join(packets)


def _binary_packet(
    *,
    device: int,
    phase: int,
    touch_id: int = 0,
    x: float = 0.0,
    y: float = 0.0,
    force: float = 0.0,
    major_radius: float = 0.0,
    tool_type: int = 0,
    scan_code: int = 0,
    key: str = "",
) -> bytes:
    key_bytes = key.encode("utf-8")[:32]
    return struct.pack(
        "<BBBBiffffii32s",
        device,
        phase,
        tool_type,
        len(key_bytes),
        touch_id,
        x,
        y,
        force,
        major_radius,
        scan_code,
        0,
        key_bytes.ljust(32, b"\0"),
    )


if __name__ == "__main__":
    unittest.main()
