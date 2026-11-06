"""Slice 3 MCP tools: app_input (synthetic HDI injection) and gate controls
(app_pause / app_step / app_resume)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.mcp_runtime import (
    MCP_CAPABILITIES,
    McpRuntimeBridge,
    TickGate,
    coerce_hdi_event,
    discovery_file_path,
    read_discovery_file,
)
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.unified_runtime import UnifiedRuntime
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.targets.base import DisplayFrame, RenderTarget

from test_mcp_runtime import _post_json


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class _FakeSensorManager(SensorManagerThread):
    def __init__(self) -> None:
        super().__init__(providers={})


class _RecordingTarget(RenderTarget):
    def start(self) -> None:
        pass

    def present_frame(self, frame: DisplayFrame) -> None:
        pass

    def stop(self) -> None:
        pass

    def pump_events(self) -> None:
        pass

    def should_close(self) -> bool:
        return False


def _call_tool(bridge: McpRuntimeBridge, name: str, arguments: dict | None = None) -> dict:
    response = bridge.dispatcher().handle_payload(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    assert response is not None
    return response


def _tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


class TickGateTests(unittest.TestCase):
    def test_free_runs_by_default(self) -> None:
        gate = TickGate()
        self.assertFalse(gate.paused)
        for _ in range(5):
            self.assertTrue(gate.tick_permitted())

    def test_pause_blocks_until_resume(self) -> None:
        gate = TickGate()
        gate.pause()
        self.assertTrue(gate.paused)
        self.assertFalse(gate.tick_permitted())
        self.assertFalse(gate.tick_permitted())
        gate.resume()
        self.assertFalse(gate.paused)
        self.assertTrue(gate.tick_permitted())

    def test_step_releases_exact_count_while_paused(self) -> None:
        gate = TickGate()
        gate.pause()
        gate.step(3)
        self.assertEqual(gate.pending_steps, 3)
        self.assertTrue(gate.tick_permitted())
        self.assertTrue(gate.tick_permitted())
        self.assertTrue(gate.tick_permitted())
        self.assertEqual(gate.pending_steps, 0)
        self.assertFalse(gate.tick_permitted())

    def test_step_accumulates(self) -> None:
        gate = TickGate()
        gate.pause()
        gate.step(2)
        gate.step(4)
        self.assertEqual(gate.pending_steps, 6)
        gate.resume()
        self.assertEqual(gate.pending_steps, 0)


class CoerceHdiEventTests(unittest.TestCase):
    def test_maps_fields(self) -> None:
        event = coerce_hdi_event(
            {
                "device": "mouse",
                "event_type": "click",
                "payload": {"x": 12.5, "y": 40.0, "button": 0},
            },
            event_id=7,
            window_id="test.app",
        )
        self.assertEqual(event.event_id, 7)
        self.assertEqual(event.window_id, "test.app")
        self.assertEqual(event.device, "mouse")
        self.assertEqual(event.event_type, "click")
        self.assertEqual(event.status, "OK")
        self.assertEqual(event.payload, {"x": 12.5, "y": 40.0, "button": 0})
        self.assertGreater(event.ts_ns, 0)

    def test_missing_payload_defaults_to_empty_dict(self) -> None:
        event = coerce_hdi_event(
            {"device": "keyboard", "event_type": "key_down"},
            event_id=1,
            window_id="w",
        )
        self.assertEqual(event.payload, {})

    def test_rejects_unknown_device(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            coerce_hdi_event({"device": "joystick", "event_type": "click"}, event_id=1, window_id="w")
        self.assertIn("joystick", str(ctx.exception))

    def test_rejects_missing_event_type(self) -> None:
        with self.assertRaises(ValueError):
            coerce_hdi_event({"device": "mouse"}, event_id=1, window_id="w")

    def test_rejects_non_dict_payload(self) -> None:
        with self.assertRaises(ValueError):
            coerce_hdi_event(
                {"device": "mouse", "event_type": "click", "payload": [1, 2]},
                event_id=1,
                window_id="w",
            )


class InjectSyntheticEventTests(unittest.TestCase):
    def test_injected_pointer_event_flows_through_normalization(self) -> None:
        hdi = HDIThread(source=None)
        injected = coerce_hdi_event(
            {
                "device": "mouse",
                "event_type": "click",
                "payload": {"x": 5.0, "y": 6.0, "button": 0},
            },
            event_id=1,
            window_id="w",
        )
        enqueued = hdi.inject_synthetic_event(injected)
        self.assertGreaterEqual(enqueued, 1)
        events = hdi.poll_events(8)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "click")
        self.assertEqual(events[0].status, "OK")
        self.assertEqual(events[0].payload["x"], 5.0)

    def test_injected_keyboard_events_feed_state_machine(self) -> None:
        hdi = HDIThread(source=None)
        down = coerce_hdi_event(
            {"device": "keyboard", "event_type": "key_down", "payload": {"key": "a", "code": 0}},
            event_id=1,
            window_id="w",
        )
        up = coerce_hdi_event(
            {"device": "keyboard", "event_type": "key_up", "payload": {"key": "a", "code": 0}},
            event_id=2,
            window_id="w",
        )
        hdi.inject_synthetic_event(down)
        hdi.inject_synthetic_event(up)
        types = [event.event_type for event in hdi.poll_events(8)]
        self.assertIn("key_down", types)
        self.assertIn("key_up", types)


class InputAndGateToolTests(unittest.TestCase):
    def _bridge(
        self,
        *,
        granted: set[str] | None = None,
        injected: list[HDIEvent] | None = None,
    ) -> McpRuntimeBridge:
        return McpRuntimeBridge(
            app_id="test.mcp",
            granted_capabilities=granted if granted is not None else set(MCP_CAPABILITIES),
            state_provider=lambda: {},
            input_injector=(injected.append if injected is not None else None),
        )

    def test_app_input_enqueues_coerced_events(self) -> None:
        injected: list[HDIEvent] = []
        bridge = self._bridge(injected=injected)
        payload = _tool_payload(
            _call_tool(
                bridge,
                "app_input",
                {
                    "events": [
                        {"device": "mouse", "event_type": "click", "payload": {"x": 1, "y": 2, "button": 0}},
                        {"device": "keyboard", "event_type": "key_down", "payload": {"key": "b", "code": 11}},
                    ]
                },
            )
        )
        self.assertEqual(payload["accepted"], 2)
        self.assertEqual(len(injected), 2)
        self.assertEqual(injected[0].device, "mouse")
        self.assertEqual(injected[1].payload["key"], "b")
        self.assertEqual(injected[0].window_id, "test.mcp")
        self.assertNotEqual(injected[0].event_id, injected[1].event_id)

    def test_app_input_single_event_form(self) -> None:
        injected: list[HDIEvent] = []
        bridge = self._bridge(injected=injected)
        payload = _tool_payload(
            _call_tool(bridge, "app_input", {"event": {"device": "mouse", "event_type": "pointer_move", "payload": {"x": 3, "y": 4}}})
        )
        self.assertEqual(payload["accepted"], 1)
        self.assertEqual(injected[0].event_type, "pointer_move")

    def test_app_input_requires_event_or_events(self) -> None:
        bridge = self._bridge(injected=[])
        response = _call_tool(bridge, "app_input", {})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("event", response["result"]["content"][0]["text"])

    def test_app_input_requires_input_capability(self) -> None:
        bridge = self._bridge(granted={"mcp.inspect", "mcp.control", "mcp.app"}, injected=[])
        listing = bridge.dispatcher().handle_payload({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listing is not None
        names = [tool["name"] for tool in listing["result"]["tools"]]
        self.assertNotIn("app_input", names)
        response = _call_tool(bridge, "app_input", {"event": {"device": "mouse", "event_type": "click"}})
        self.assertEqual(response["error"]["code"], -32601)
        self.assertIn("mcp.input", response["error"]["message"])

    def test_gate_tools_pause_step_resume(self) -> None:
        bridge = self._bridge()
        self.assertFalse(bridge.gate.paused)

        payload = _tool_payload(_call_tool(bridge, "app_pause"))
        self.assertTrue(payload["paused"])
        self.assertTrue(bridge.gate.paused)

        state = _tool_payload(_call_tool(bridge, "app_state"))
        self.assertTrue(state["gate"]["paused"])

        # app_step is invalid while not paused; resume then verify the error path.
        bridge.gate.resume()
        response = _call_tool(bridge, "app_step", {"ticks": 2})
        self.assertTrue(response["result"]["isError"])
        self.assertIn("paused", response["result"]["content"][0]["text"])

        _call_tool(bridge, "app_pause")
        payload = _tool_payload(_call_tool(bridge, "app_step", {"ticks": 3}))
        self.assertEqual(payload["released_ticks"], 3)
        self.assertEqual(bridge.gate.pending_steps, 3)

        payload = _tool_payload(_call_tool(bridge, "app_resume"))
        self.assertFalse(payload["paused"])
        self.assertFalse(bridge.gate.paused)

    def test_app_stop_is_immediate_while_paused(self) -> None:
        bridge = self._bridge()
        bridge.gate.pause()
        _call_tool(bridge, "app_stop")
        self.assertTrue(bridge.stop_requested)


class McpInputControlEndToEndTests(unittest.TestCase):
    def test_pause_step_and_input_injection_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                'app_id = "test.mcp-input"\n'
                'protocol_version = "1"\n'
                'entrypoint = "app_main:create"\n'
                'required_capabilities = ["hdi.mouse"]\n'
                "optional_capabilities = []\n"
                "\n[mcp]\nenabled = true\n",
                encoding="utf-8",
            )
            (app_dir / "app_main.py").write_text(
                "import json\n"
                "from pathlib import Path\n"
                "class App:\n"
                "    def init(self, ctx):\n"
                "        self.ticks = 0\n"
                "        self.events_path = Path(__file__).with_name('events.jsonl')\n"
                "    def loop(self, ctx, dt):\n"
                "        self.ticks += 1\n"
                "        events = ctx.poll_hdi_events(max_events=16)\n"
                "        if events:\n"
                "            with self.events_path.open('a', encoding='utf-8') as handle:\n"
                "                for event in events:\n"
                "                    handle.write(json.dumps({'tick': self.ticks, 'type': event.event_type, 'payload': event.payload}) + '\\n')\n"
                "    def stop(self, ctx): pass\n"
                "def create(): return App()\n",
                encoding="utf-8",
            )
            runtime = UnifiedRuntime(
                matrix=WindowMatrix(width=4, height=4),
                target=_RecordingTarget(),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
                capability_decider=lambda _cap: True,
                mcp_enabled=True,
            )
            outcome: dict[str, object] = {}
            thread = threading.Thread(
                target=lambda: outcome.setdefault(
                    "result", runtime.run_app(app_dir, max_ticks=None, target_fps=200)
                ),
                daemon=True,
            )
            thread.start()
            discovery = discovery_file_path(app_dir)
            deadline = time.monotonic() + 10.0
            while not discovery.exists():
                if time.monotonic() > deadline:
                    self.fail("MCP discovery file was not created")
                time.sleep(0.01)
            info = read_discovery_file(app_dir)

            def call(req_id: int, name: str, arguments: dict | None = None) -> dict:
                status, body = _post_json(
                    info["url"],
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments or {}},
                    },
                    token=info["token"],
                )
                self.assertEqual(status, 200)
                self.assertFalse(body["result"]["isError"], body)
                return json.loads(body["result"]["content"][0]["text"])

            # Wait for the app to be free-running, then pause.
            while json.loads(
                _post_json(
                    info["url"],
                    {"jsonrpc": "2.0", "id": 90, "method": "tools/call", "params": {"name": "app_state", "arguments": {}}},
                    token=info["token"],
                )[1]["result"]["content"][0]["text"]
            )["runtime"]["app_loop_ticks"] < 1:
                time.sleep(0.01)
            call(1, "app_pause")
            paused_ticks = call(2, "app_state")["runtime"]["app_loop_ticks"]
            time.sleep(0.15)
            self.assertEqual(call(3, "app_state")["runtime"]["app_loop_ticks"], paused_ticks)

            # Inject a click, step exactly two ticks, and confirm the tick count.
            call(4, "app_input", {"event": {"device": "mouse", "event_type": "click", "payload": {"x": 2, "y": 2, "button": 0}}})
            call(5, "app_step", {"ticks": 2})
            step_deadline = time.monotonic() + 5.0
            while call(6, "app_state")["runtime"]["app_loop_ticks"] < paused_ticks + 2:
                if time.monotonic() > step_deadline:
                    self.fail("app_step did not release the gate")
                time.sleep(0.01)
            time.sleep(0.15)
            self.assertEqual(call(7, "app_state")["runtime"]["app_loop_ticks"], paused_ticks + 2)

            # The injected click was consumed by the app on a stepped tick.
            events_file = app_dir / "events.jsonl"
            self.assertTrue(events_file.exists())
            recorded = [json.loads(line) for line in events_file.read_text().splitlines() if line.strip()]
            self.assertTrue(
                any(entry["type"] == "click" for entry in recorded),
                recorded,
            )
            click_ticks = [entry["tick"] for entry in recorded if entry["type"] == "click"]
            self.assertTrue(all(tick > paused_ticks for tick in click_ticks))

            # Resume free-runs again, then stop cleanly.
            call(8, "app_resume")
            resume_deadline = time.monotonic() + 5.0
            while call(9, "app_state")["runtime"]["app_loop_ticks"] <= paused_ticks + 2:
                if time.monotonic() > resume_deadline:
                    self.fail("app_resume did not restore free running")
                time.sleep(0.01)
            call(10, "app_stop")
            thread.join(timeout=10.0)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
