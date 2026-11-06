"""Tests for MCP mode: manifest config, JSON-RPC protocol, HTTP transport,
discovery file, capability gating, and run-loop integration.

Slice 1 scope: session infra + handshake + bearer auth + capability gating +
`app_state` / `app_stop` tools. Screenshots, input injection, stepping, and
app-defined hooks land in later slices.
"""
from __future__ import annotations

import json
import os
import stat
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import tempfile
import unittest

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.mcp_http import McpHttpServer
from luvatrix_core.core.mcp_protocol import (
    MCP_PROTOCOL_VERSION,
    McpDispatcher,
    McpToolSpec,
)
from luvatrix_core.core.mcp_runtime import (
    MCP_CAPABILITIES,
    McpRuntimeBridge,
    discovery_file_path,
    mcp_capabilities_for_allow,
    read_discovery_file,
    remove_discovery_file,
    write_discovery_file,
)
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.unified_runtime import UnifiedRuntime
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.targets.base import DisplayFrame, RenderTarget


class _NoopHDISource:
    def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
        return []


class _FakeSensorManager(SensorManagerThread):
    def __init__(self) -> None:
        super().__init__(providers={})


class _RecordingTarget(RenderTarget):
    def __init__(self) -> None:
        self.presented: list[DisplayFrame] = []

    def start(self) -> None:
        pass

    def present_frame(self, frame: DisplayFrame) -> None:
        self.presented.append(frame)

    def stop(self) -> None:
        pass

    def pump_events(self) -> None:
        pass

    def should_close(self) -> bool:
        return False


def _write_app(app_dir: Path, *, extra_toml: str = "", lifecycle: str | None = None) -> None:
    (app_dir / "app.toml").write_text(
        'app_id = "test.mcp"\n'
        'protocol_version = "1"\n'
        'entrypoint = "app_main:create"\n'
        'required_capabilities = []\n'
        'optional_capabilities = []\n'
        + extra_toml,
        encoding="utf-8",
    )
    (app_dir / "app_main.py").write_text(
        lifecycle
        or (
            "class App:\n"
            "    def init(self, ctx): pass\n"
            "    def loop(self, ctx, dt): pass\n"
            "    def stop(self, ctx): pass\n"
            "def create(): return App()\n"
        ),
        encoding="utf-8",
    )


def _post_json(url: str, payload: object, *, token: str | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, json.loads(raw) if raw else {}


def _make_bridge(
    *,
    app_id: str = "test.mcp",
    granted: set[str] | None = None,
    state: dict | None = None,
    audit: list[dict] | None = None,
) -> McpRuntimeBridge:
    return McpRuntimeBridge(
        app_id=app_id,
        granted_capabilities=granted if granted is not None else set(MCP_CAPABILITIES),
        state_provider=lambda: dict(state or {}),
        audit_logger=audit.append if audit is not None else None,
    )


class ManifestMcpConfigTests(unittest.TestCase):
    def test_mcp_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir)
            manifest = AppRuntime(
                matrix=WindowMatrix(width=2, height=2),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
            ).load_manifest(app_dir)
            self.assertFalse(manifest.mcp.enabled)
            self.assertEqual(manifest.mcp.allow, ("inspect", "input", "control", "app"))

    def test_mcp_enabled_parses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir, extra_toml="\n[mcp]\nenabled = true\n")
            manifest = AppRuntime(
                matrix=WindowMatrix(width=2, height=2),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
            ).load_manifest(app_dir)
            self.assertTrue(manifest.mcp.enabled)
            self.assertEqual(manifest.mcp.allow, ("inspect", "input", "control", "app"))

    def test_mcp_allow_subset_parses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir, extra_toml='\n[mcp]\nenabled = true\nallow = ["inspect"]\n')
            manifest = AppRuntime(
                matrix=WindowMatrix(width=2, height=2),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
            ).load_manifest(app_dir)
            self.assertTrue(manifest.mcp.enabled)
            self.assertEqual(manifest.mcp.allow, ("inspect",))
            self.assertEqual(mcp_capabilities_for_allow(manifest.mcp.allow), {"mcp.inspect"})

    def test_mcp_allow_unknown_entry_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir, extra_toml='\n[mcp]\nenabled = true\nallow = ["inspect", "bogus"]\n')
            with self.assertRaises(ValueError) as ctx:
                AppRuntime(
                    matrix=WindowMatrix(width=2, height=2),
                    hdi=HDIThread(source=_NoopHDISource()),
                    sensor_manager=_FakeSensorManager(),
                ).load_manifest(app_dir)
            self.assertIn("bogus", str(ctx.exception))

    def test_mcp_enabled_non_bool_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir, extra_toml='\n[mcp]\nenabled = "yes"\n')
            with self.assertRaises(ValueError):
                AppRuntime(
                    matrix=WindowMatrix(width=2, height=2),
                    hdi=HDIThread(source=_NoopHDISource()),
                    sensor_manager=_FakeSensorManager(),
                ).load_manifest(app_dir)


class McpDispatcherTests(unittest.TestCase):
    def _tools(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                name="app_state",
                description="Return runtime state.",
                input_schema={"type": "object", "properties": {}},
                capability="mcp.inspect",
            ),
            McpToolSpec(
                name="app_stop",
                description="Stop the app.",
                input_schema={"type": "object", "properties": {}},
                capability="mcp.control",
            ),
        ]

    def _dispatcher(self, granted: set[str]) -> McpDispatcher:
        return McpDispatcher(
            app_id="test.mcp",
            tools=self._tools(),
            granted_capabilities=granted,
            tool_handler=lambda name, args: {"echo": name, "args": args},
        )

    def test_initialize_handshake(self) -> None:
        response = self._dispatcher(set(MCP_CAPABILITIES)).handle_payload(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "x"}}
        )
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["id"], 1)
        result = response["result"]
        self.assertEqual(result["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(result["serverInfo"]["name"], "luvatrix-mcp")
        self.assertIn("tools", result["capabilities"])

    def test_ping(self) -> None:
        response = self._dispatcher(set()).handle_payload({"jsonrpc": "2.0", "id": 7, "method": "ping"})
        self.assertEqual(response, {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_notification_returns_no_response(self) -> None:
        response = self._dispatcher(set()).handle_payload(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self.assertIsNone(response)

    def test_tools_list_filters_by_granted_capabilities(self) -> None:
        response = self._dispatcher({"mcp.inspect"}).handle_payload(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert response is not None
        tools = response["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["app_state"])
        self.assertEqual(tools[0]["inputSchema"], {"type": "object", "properties": {}})

    def test_tools_call_runs_handler(self) -> None:
        response = self._dispatcher(set(MCP_CAPABILITIES)).handle_payload(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "app_state", "arguments": {"verbose": True}},
            }
        )
        assert response is not None
        result = response["result"]
        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload, {"echo": "app_state", "args": {"verbose": True}})

    def test_tools_call_denied_capability(self) -> None:
        response = self._dispatcher({"mcp.inspect"}).handle_payload(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "app_stop", "arguments": {}},
            }
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32601)
        self.assertIn("mcp.control", response["error"]["message"])

    def test_tools_call_unknown_tool(self) -> None:
        response = self._dispatcher(set(MCP_CAPABILITIES)).handle_payload(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32601)

    def test_tools_call_missing_name_is_invalid_params(self) -> None:
        response = self._dispatcher(set(MCP_CAPABILITIES)).handle_payload(
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"arguments": {}}}
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32602)

    def test_unknown_method_with_id(self) -> None:
        response = self._dispatcher(set()).handle_payload(
            {"jsonrpc": "2.0", "id": 8, "method": "resources/list"}
        )
        assert response is not None
        self.assertEqual(response["error"]["code"], -32601)

    def test_invalid_jsonrpc_version(self) -> None:
        response = self._dispatcher(set()).handle_payload({"jsonrpc": "1.0", "id": 9, "method": "ping"})
        assert response is not None
        self.assertEqual(response["error"]["code"], -32600)

    def test_batch_payload(self) -> None:
        response = self._dispatcher(set()).handle_payload(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
        )
        self.assertIsInstance(response, list)
        assert isinstance(response, list)
        self.assertEqual(len(response), 2)
        self.assertEqual([item["id"] for item in response], [1, 2])


class McpHttpServerTests(unittest.TestCase):
    def _start_server(self) -> tuple[McpHttpServer, str]:
        bridge = _make_bridge()
        server = McpHttpServer(bridge.dispatcher(), token="test-token")
        server.start()
        self.addCleanup(server.stop)
        return server, "test-token"

    def test_requires_bearer_token(self) -> None:
        server, token = self._start_server()
        status, _ = _post_json(server.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(status, 401)
        status, _ = _post_json(server.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token="wrong")
        self.assertEqual(status, 401)
        status, body = _post_json(server.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"], {})

    def test_initialize_roundtrip_over_http(self) -> None:
        server, token = self._start_server()
        status, body = _post_json(
            server.url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)

    def test_ephemeral_port_and_url_shape(self) -> None:
        server, _ = self._start_server()
        self.assertGreater(server.port, 0)
        self.assertTrue(server.url.startswith("http://127.0.0.1:"))
        self.assertTrue(server.url.endswith("/mcp"))


class DiscoveryFileTests(unittest.TestCase):
    def test_write_read_remove_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            path = write_discovery_file(
                app_dir,
                url="http://127.0.0.1:9999/mcp",
                token="secret-token",
                app_id="test.mcp",
                capabilities=("mcp.inspect", "mcp.control"),
            )
            self.assertEqual(path, discovery_file_path(app_dir))
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)
            info = read_discovery_file(app_dir)
            self.assertEqual(info["url"], "http://127.0.0.1:9999/mcp")
            self.assertEqual(info["token"], "secret-token")
            self.assertEqual(info["app_id"], "test.mcp")
            self.assertEqual(info["pid"], os.getpid())
            self.assertEqual(info["protocol_version"], MCP_PROTOCOL_VERSION)
            # Capabilities are stored sorted for deterministic diffs.
            self.assertEqual(tuple(info["capabilities"]), ("mcp.control", "mcp.inspect"))
            remove_discovery_file(app_dir)
            self.assertFalse(path.exists())


class McpBridgeToolTests(unittest.TestCase):
    def test_app_state_returns_app_id_and_telemetry(self) -> None:
        bridge = _make_bridge(state={"app_loop_ticks": 42, "frames_presented": 7})
        response = bridge.dispatcher().handle_payload(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "app_state", "arguments": {}},
            }
        )
        assert response is not None
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["app_id"], "test.mcp")
        self.assertEqual(payload["runtime"]["app_loop_ticks"], 42)
        self.assertEqual(payload["runtime"]["frames_presented"], 7)

    def test_app_state_hidden_without_inspect_capability(self) -> None:
        bridge = _make_bridge(granted={"mcp.control"})
        response = bridge.dispatcher().handle_payload(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert response is not None
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertNotIn("app_state", names)
        self.assertIn("app_stop", names)

    def test_app_stop_sets_stop_requested(self) -> None:
        bridge = _make_bridge()
        self.assertFalse(bridge.stop_requested)
        response = bridge.dispatcher().handle_payload(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "app_stop", "arguments": {}},
            }
        )
        assert response is not None
        self.assertFalse(response["result"]["isError"])
        self.assertTrue(bridge.stop_requested)

    def test_audit_entries_record_mcp_capability_decisions(self) -> None:
        audit: list[dict] = []
        _make_bridge(granted={"mcp.inspect", "mcp.control"}, audit=audit)
        by_capability = {entry["capability"]: entry["action"] for entry in audit}
        self.assertEqual(by_capability["mcp.inspect"], "granted_mcp_capability")
        self.assertEqual(by_capability["mcp.control"], "granted_mcp_capability")
        self.assertEqual(by_capability["mcp.input"], "denied_mcp_capability")
        self.assertEqual(by_capability["mcp.app"], "denied_mcp_capability")
        for entry in audit:
            self.assertEqual(entry["actor"], "mcp_runtime")


class UnifiedRuntimeMcpTests(unittest.TestCase):
    def _build_runtime(self, *, mcp_enabled: bool) -> UnifiedRuntime:
        return UnifiedRuntime(
            matrix=WindowMatrix(width=4, height=4),
            target=_RecordingTarget(),
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=_FakeSensorManager(),
            mcp_enabled=mcp_enabled,
        )

    def test_mcp_flag_requires_manifest_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir)  # no [mcp] section
            runtime = self._build_runtime(mcp_enabled=True)
            with self.assertRaises(ValueError) as ctx:
                runtime.run_app(app_dir, max_ticks=1, target_fps=60)
            self.assertIn("[mcp]", str(ctx.exception))

    def test_mcp_rejects_process_runtime_kind(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(
                app_dir,
                extra_toml=(
                    "\n[mcp]\nenabled = true\n"
                    '\n[runtime]\nkind = "process"\ncommand = ["python3", "worker.py"]\n'
                ),
            )
            runtime = self._build_runtime(mcp_enabled=True)
            with self.assertRaises(ValueError) as ctx:
                runtime.run_app(app_dir, max_ticks=1, target_fps=60)
            self.assertIn("process", str(ctx.exception).lower())

    def test_mcp_disabled_by_default_runs_without_server(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir, extra_toml="\n[mcp]\nenabled = true\n")
            runtime = self._build_runtime(mcp_enabled=False)
            result = runtime.run_app(app_dir, max_ticks=2, target_fps=200)
            self.assertEqual(result.ticks_run, 2)
            self.assertFalse(discovery_file_path(app_dir).exists())

    def test_mcp_end_to_end_state_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            _write_app(app_dir, extra_toml='\n[mcp]\nenabled = true\nallow = ["inspect", "control"]\n')
            runtime = self._build_runtime(mcp_enabled=True)
            outcome: dict[str, object] = {}

            def _run() -> None:
                outcome["result"] = runtime.run_app(app_dir, max_ticks=None, target_fps=200)

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            discovery = discovery_file_path(app_dir)
            deadline = time.monotonic() + 10.0
            while not discovery.exists():
                if time.monotonic() > deadline:
                    self.fail("MCP discovery file was not created")
                time.sleep(0.01)
            info = read_discovery_file(app_dir)
            self.assertEqual(info["app_id"], "test.mcp")
            self.assertEqual(tuple(info["capabilities"]), ("mcp.control", "mcp.inspect"))

            status, body = _post_json(
                info["url"], {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, token=info["token"]
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)

            status, body = _post_json(
                info["url"], {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, token=info["token"]
            )
            self.assertEqual(status, 200)
            names = [tool["name"] for tool in body["result"]["tools"]]
            self.assertEqual(names, ["app_state", "app_stop"])

            status, body = _post_json(
                info["url"],
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "app_state", "arguments": {}},
                },
                token=info["token"],
            )
            self.assertEqual(status, 200)
            state = json.loads(body["result"]["content"][0]["text"])
            self.assertEqual(state["app_id"], "test.mcp")
            self.assertIn("app_loop_ticks", state["runtime"])

            status, body = _post_json(
                info["url"],
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "app_stop", "arguments": {}},
                },
                token=info["token"],
            )
            self.assertEqual(status, 200)

            thread.join(timeout=10.0)
            self.assertFalse(thread.is_alive())
            self.assertGreater(outcome["result"].ticks_run, 0)
            self.assertFalse(discovery.exists())


if __name__ == "__main__":
    unittest.main()
