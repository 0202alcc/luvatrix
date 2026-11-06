"""Slice 5: luvatrix mcp-proxy — NDJSON stdio bridge to a running MCP session."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

from luvatrix_core.core.mcp_http import McpHttpServer
from luvatrix_core.core.mcp_protocol import MCP_PROTOCOL_VERSION
from luvatrix_core.core.mcp_proxy import load_session_info, run_proxy
from luvatrix_core.core.mcp_runtime import (
    MCP_CAPABILITIES,
    McpRuntimeBridge,
    write_discovery_file,
)


def _make_server() -> McpHttpServer:
    bridge = McpRuntimeBridge(
        app_id="test.mcp-proxy",
        granted_capabilities=set(MCP_CAPABILITIES),
        state_provider=lambda: {"app_loop_ticks": 3},
    )
    server = McpHttpServer(bridge.dispatcher(), token="proxy-token")
    server.start()
    return server


def _run_proxy_lines(target: Path, lines: list[str]) -> list[dict]:
    stdin = io.StringIO("".join(line + "\n" for line in lines))
    stdout = io.StringIO()
    exit_code = run_proxy(target, stdin=stdin, stdout=stdout)
    assert exit_code == 0
    output = stdout.getvalue()
    return [json.loads(line) for line in output.splitlines() if line.strip()]


class LoadSessionInfoTests(unittest.TestCase):
    def test_resolves_app_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            write_discovery_file(
                app_dir,
                url="http://127.0.0.1:1/mcp",
                token="tok",
                app_id="test.dir",
                capabilities=("mcp.inspect",),
            )
            info = load_session_info(app_dir)
            self.assertEqual(info["url"], "http://127.0.0.1:1/mcp")
            self.assertEqual(info["token"], "tok")

    def test_resolves_direct_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            path = write_discovery_file(
                app_dir,
                url="http://127.0.0.1:2/mcp",
                token="tok2",
                app_id="test.file",
                capabilities=("mcp.inspect",),
            )
            info = load_session_info(path)
            self.assertEqual(info["app_id"], "test.file")

    def test_missing_session_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError) as ctx:
                load_session_info(Path(td))
            self.assertIn("mcp-session.json", str(ctx.exception))


class RunProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _make_server()
        self.addCleanup(self.server.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app_dir = Path(self._tmp.name)
        write_discovery_file(
            self.app_dir,
            url=self.server.url,
            token="proxy-token",
            app_id="test.mcp-proxy",
            capabilities=tuple(sorted(MCP_CAPABILITIES)),
        )

    def test_initialize_roundtrip(self) -> None:
        responses = _run_proxy_lines(
            self.app_dir,
            [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})],
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)

    def test_tools_call_roundtrip(self) -> None:
        responses = _run_proxy_lines(
            self.app_dir,
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "app_state", "arguments": {}},
                    }
                )
            ],
        )
        self.assertEqual(len(responses), 1)
        payload = json.loads(responses[0]["result"]["content"][0]["text"])
        self.assertEqual(payload["app_id"], "test.mcp-proxy")

    def test_notifications_produce_no_output(self) -> None:
        responses = _run_proxy_lines(
            self.app_dir,
            [json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})],
        )
        self.assertEqual(responses, [])

    def test_blank_lines_are_skipped(self) -> None:
        responses = _run_proxy_lines(
            self.app_dir,
            ["", json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"})],
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["result"], {})

    def test_invalid_json_line_gets_parse_error(self) -> None:
        responses = _run_proxy_lines(self.app_dir, ["not json{{"])
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["error"]["code"], -32700)

    def test_unreachable_session_gets_error_response(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dead_dir = Path(td)
            write_discovery_file(
                dead_dir,
                url="http://127.0.0.1:1/mcp",  # nothing listens here
                token="tok",
                app_id="test.dead",
                capabilities=("mcp.inspect",),
            )
            responses = _run_proxy_lines(
                dead_dir,
                [json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})],
            )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 9)
        self.assertIn("error", responses[0])
        self.assertIn("unreachable", responses[0]["error"]["message"])


class McpProxyCliTests(unittest.TestCase):
    def test_cli_delegates_to_run_proxy(self) -> None:
        import sys
        from unittest.mock import patch

        from main import main

        with (
            patch.object(sys, "argv", ["luvatrix", "mcp-proxy", "some/app"]),
            patch("luvatrix_core.core.mcp_proxy.run_proxy", return_value=0) as proxy,
        ):
            with self.assertRaises(SystemExit) as ctx:
                main()
        self.assertEqual(ctx.exception.code, 0)
        (target,), kwargs = proxy.call_args
        self.assertEqual(str(target), "some/app")


if __name__ == "__main__":
    unittest.main()
