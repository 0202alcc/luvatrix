"""Slice 4 MCP tools: app-defined hooks (mcp_tools / mcp_call / mcp_state).

App hook code always executes on the runtime thread: the MCP server thread
queues tool calls, and the run loop drains them between ticks.
"""
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


class _HookApp:
    """In-process stand-in for an app lifecycle object with MCP hooks."""

    def __init__(self) -> None:
        self.count = 0
        self.calls: list[tuple[str, dict]] = []

    def mcp_tools(self) -> list[dict]:
        return [
            {
                "name": "demo_get_count",
                "description": "Get the loop count.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "demo_boom",
                "description": "Always raises.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def mcp_call(self, name: str, arguments: dict) -> object:
        self.calls.append((name, dict(arguments)))
        if name == "demo_get_count":
            return {"count": self.count}
        if name == "demo_boom":
            raise RuntimeError("boom from app")
        raise KeyError(name)

    def mcp_state(self) -> dict:
        return {"count": self.count}


def _make_bridge(
    *,
    granted: set[str] | None = None,
    app_call_timeout_s: float = 10.0,
) -> McpRuntimeBridge:
    return McpRuntimeBridge(
        app_id="test.mcp",
        granted_capabilities=granted if granted is not None else set(MCP_CAPABILITIES),
        state_provider=lambda: {},
        app_call_timeout_s=app_call_timeout_s,
    )


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


def _drain_in_background(bridge: McpRuntimeBridge, stop: threading.Event) -> threading.Thread:
    def _loop() -> None:
        while not stop.is_set():
            bridge.drain_app_calls()
            time.sleep(0.005)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread


class AppHookRegistrationTests(unittest.TestCase):
    def test_register_app_hooks_adds_tools_to_listing(self) -> None:
        bridge = _make_bridge()
        app = _HookApp()
        registered = bridge.register_app_hooks(app)
        self.assertEqual(registered, 2)
        listing = bridge.dispatcher().handle_payload({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listing is not None
        names = [tool["name"] for tool in listing["result"]["tools"]]
        self.assertIn("demo_get_count", names)
        self.assertIn("demo_boom", names)
        wire = {tool["name"]: tool for tool in listing["result"]["tools"]}
        self.assertEqual(wire["demo_get_count"]["description"], "Get the loop count.")
        self.assertEqual(wire["demo_get_count"]["inputSchema"], {"type": "object", "properties": {}})

    def test_app_tools_hidden_without_app_capability(self) -> None:
        bridge = _make_bridge(granted={"mcp.inspect", "mcp.input", "mcp.control"})
        bridge.register_app_hooks(_HookApp())
        listing = bridge.dispatcher().handle_payload({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listing is not None
        names = [tool["name"] for tool in listing["result"]["tools"]]
        self.assertNotIn("demo_get_count", names)
        response = _call_tool(bridge, "demo_get_count")
        self.assertEqual(response["error"]["code"], -32601)
        self.assertIn("mcp.app", response["error"]["message"])

    def test_builtin_name_collision_is_skipped_with_warning(self) -> None:
        class _BadApp(_HookApp):
            def mcp_tools(self) -> list[dict]:
                return [
                    {"name": "app_state", "description": "Collision.", "inputSchema": {}},
                    {"name": "demo_ok", "description": "Fine.", "inputSchema": {"type": "object"}},
                ]

        bridge = _make_bridge()
        with self.assertLogs("luvatrix_core.core.mcp_runtime", level="WARNING") as captured:
            registered = bridge.register_app_hooks(_BadApp())
        self.assertEqual(registered, 1)
        self.assertTrue(any("app_state" in line for line in captured.output))
        # The built-in still resolves to the bridge handler, not app code.
        payload = _tool_payload(_call_tool(bridge, "app_state"))
        self.assertEqual(payload["app_id"], "test.mcp")

    def test_invalid_tool_entries_are_skipped(self) -> None:
        class _BadApp(_HookApp):
            def mcp_tools(self) -> list[dict]:
                return [
                    {"description": "missing name"},
                    {"name": "demo_ok", "description": "Fine.", "inputSchema": {"type": "object"}},
                ]

        bridge = _make_bridge()
        with self.assertLogs("luvatrix_core.core.mcp_runtime", level="WARNING"):
            registered = bridge.register_app_hooks(_BadApp())
        self.assertEqual(registered, 1)

    def test_no_hooks_registers_nothing(self) -> None:
        bridge = _make_bridge()
        self.assertEqual(bridge.register_app_hooks(object()), 0)


class AppToolExecutionTests(unittest.TestCase):
    def test_app_tool_call_executes_on_drain(self) -> None:
        bridge = _make_bridge()
        app = _HookApp()
        app.count = 41
        bridge.register_app_hooks(app)
        stop = threading.Event()
        _drain_in_background(bridge, stop)
        try:
            response = _call_tool(bridge, "demo_get_count", {"verbose": True})
        finally:
            stop.set()
        payload = _tool_payload(response)
        self.assertEqual(payload, {"count": 41})
        self.assertEqual(app.calls, [("demo_get_count", {"verbose": True})])

    def test_app_tool_error_surfaces_as_tool_error(self) -> None:
        bridge = _make_bridge()
        bridge.register_app_hooks(_HookApp())
        stop = threading.Event()
        _drain_in_background(bridge, stop)
        try:
            response = _call_tool(bridge, "demo_boom")
        finally:
            stop.set()
        self.assertTrue(response["result"]["isError"])
        self.assertIn("boom from app", response["result"]["content"][0]["text"])

    def test_app_tool_call_times_out_without_drain(self) -> None:
        bridge = _make_bridge(app_call_timeout_s=0.05)
        bridge.register_app_hooks(_HookApp())
        response = bridge.dispatcher().handle_payload(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "demo_get_count", "arguments": {}},
            }
        )
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        self.assertIn("runtime thread", response["result"]["content"][0]["text"])

    def test_mcp_state_merged_into_app_state_after_drain(self) -> None:
        bridge = _make_bridge()
        app = _HookApp()
        app.count = 7
        bridge.register_app_hooks(app)
        # Before any drain, the app section is absent.
        payload = _tool_payload(_call_tool(bridge, "app_state"))
        self.assertNotIn("app", payload)
        bridge.drain_app_calls()
        payload = _tool_payload(_call_tool(bridge, "app_state"))
        self.assertEqual(payload["app"], {"count": 7})


class AppHooksEndToEndTests(unittest.TestCase):
    def test_app_hooks_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                'app_id = "test.mcp-hooks"\n'
                'protocol_version = "1"\n'
                'entrypoint = "app_main:create"\n'
                "required_capabilities = []\n"
                "optional_capabilities = []\n"
                "\n[mcp]\nenabled = true\n",
                encoding="utf-8",
            )
            (app_dir / "app_main.py").write_text(
                "class App:\n"
                "    def init(self, ctx): self.count = 0\n"
                "    def loop(self, ctx, dt): self.count += 1\n"
                "    def stop(self, ctx): pass\n"
                "    def mcp_tools(self):\n"
                "        return [{'name': 'demo_get_count', 'description': 'Get loop count.', 'inputSchema': {'type': 'object', 'properties': {}}}]\n"
                "    def mcp_call(self, name, arguments):\n"
                "        if name == 'demo_get_count':\n"
                "            return {'count': self.count}\n"
                "        raise KeyError(name)\n"
                "    def mcp_state(self): return {'count': self.count}\n"
                "def create(): return App()\n",
                encoding="utf-8",
            )
            runtime = UnifiedRuntime(
                matrix=WindowMatrix(width=2, height=2),
                target=_RecordingTarget(),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
                capability_decider=lambda _cap: True,
                mcp_enabled=True,
            )
            thread = threading.Thread(
                target=lambda: runtime.run_app(app_dir, max_ticks=None, target_fps=200),
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

            # The app-defined tool appears in the listing.
            status, body = _post_json(
                info["url"], {"jsonrpc": "2.0", "id": 50, "method": "tools/list"}, token=info["token"]
            )
            self.assertEqual(status, 200)
            names = [tool["name"] for tool in body["result"]["tools"]]
            self.assertIn("demo_get_count", names)

            # Calling it executes app code on the runtime thread.
            result = call(1, "demo_get_count")
            self.assertGreaterEqual(result["count"], 1)

            # mcp_state flows into app_state once drained.
            state_deadline = time.monotonic() + 5.0
            while True:
                state = call(2, "app_state")
                if "app" in state and state["app"]["count"] >= 1:
                    break
                if time.monotonic() > state_deadline:
                    self.fail("mcp_state never appeared in app_state")
                time.sleep(0.02)
            self.assertGreaterEqual(state["app"]["count"], result["count"] - 1)

            call(3, "app_stop")
            thread.join(timeout=10.0)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
