"""Slice 2 MCP tools: app_screenshot (raw RGBA), app_scene_tree, app_logs."""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest

from luvatrix_core import accel
from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
from luvatrix_core.core.mcp_runtime import (
    MCP_CAPABILITIES,
    McpRuntimeBridge,
    McpScreenshot,
    RingBufferLogHandler,
    discovery_file_path,
    read_discovery_file,
    scene_node_to_dict,
)
from luvatrix_core.core.scene_graph import ClearNode, RectNode, SceneFrame
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.unified_runtime import UnifiedRuntime
from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch
from luvatrix_core.targets.base import DisplayFrame, RenderTarget
from luvatrix_core.targets.cpu_scene_target import CpuSceneTarget

from test_mcp_runtime import _post_json


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


def _make_bridge(
    *,
    granted: set[str] | None = None,
    screenshot_provider=None,
    scene_tree_provider=None,
    log_provider=None,
) -> McpRuntimeBridge:
    return McpRuntimeBridge(
        app_id="test.mcp",
        granted_capabilities=granted if granted is not None else set(MCP_CAPABILITIES),
        state_provider=lambda: {},
        screenshot_provider=screenshot_provider,
        scene_tree_provider=scene_tree_provider,
        log_provider=log_provider,
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


class InspectToolBridgeTests(unittest.TestCase):
    def test_app_screenshot_returns_raw_rgba(self) -> None:
        rgba = bytes([255, 0, 0, 255] * 4)
        bridge = _make_bridge(
            screenshot_provider=lambda: McpScreenshot(width=2, height=2, source="matrix", rgba=rgba)
        )
        payload = _tool_payload(_call_tool(bridge, "app_screenshot"))
        self.assertEqual(payload["width"], 2)
        self.assertEqual(payload["height"], 2)
        self.assertEqual(payload["format"], "raw_rgba")
        self.assertEqual(payload["source"], "matrix")
        decoded = base64.b64decode(payload["data_base64"])
        self.assertEqual(decoded, rgba)
        self.assertEqual(len(decoded), 2 * 2 * 4)

    def test_inspect_tools_require_inspect_capability(self) -> None:
        bridge = _make_bridge(
            granted={"mcp.control"},
            screenshot_provider=lambda: McpScreenshot(width=1, height=1, source="matrix", rgba=b"\0" * 4),
            scene_tree_provider=lambda: {"available": False, "nodes": []},
            log_provider=lambda limit: [],
        )
        listing = bridge.dispatcher().handle_payload({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listing is not None
        names = [tool["name"] for tool in listing["result"]["tools"]]
        for hidden in ("app_screenshot", "app_scene_tree", "app_logs"):
            self.assertNotIn(hidden, names)
        for hidden in ("app_screenshot", "app_scene_tree", "app_logs"):
            response = _call_tool(bridge, hidden)
            self.assertEqual(response["error"]["code"], -32601)
            self.assertIn("mcp.inspect", response["error"]["message"])

    def test_inspect_tools_without_provider_report_tool_error(self) -> None:
        bridge = _make_bridge()
        for name in ("app_screenshot", "app_scene_tree", "app_logs"):
            response = _call_tool(bridge, name)
            self.assertTrue(response["result"]["isError"], name)
            self.assertIn("unavailable", response["result"]["content"][0]["text"])

    def test_app_scene_tree_passes_provider_payload(self) -> None:
        tree = {
            "available": True,
            "revision": 7,
            "nodes": [{"type": "RectNode", "x": 0, "y": 0, "width": 4, "height": 2}],
        }
        bridge = _make_bridge(scene_tree_provider=lambda: tree)
        payload = _tool_payload(_call_tool(bridge, "app_scene_tree"))
        self.assertEqual(payload, tree)

    def test_app_logs_respects_limit(self) -> None:
        entries = [{"message": f"line-{index}"} for index in range(10)]
        bridge = _make_bridge(log_provider=lambda limit: entries[-limit:])
        payload = _tool_payload(_call_tool(bridge, "app_logs", {"limit": 3}))
        self.assertEqual([entry["message"] for entry in payload["entries"]], ["line-7", "line-8", "line-9"])
        payload = _tool_payload(_call_tool(bridge, "app_logs"))
        self.assertEqual(len(payload["entries"]), 10)


class RingBufferLogHandlerTests(unittest.TestCase):
    def test_captures_records_newest_last_with_capacity(self) -> None:
        handler = RingBufferLogHandler(capacity=3)
        logger = logging.getLogger("test.mcp.ring")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            for index in range(5):
                logger.info("message-%d", index)
        finally:
            logger.removeHandler(handler)
        entries = handler.entries(10)
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry["message"] for entry in entries], ["message-2", "message-3", "message-4"])
        self.assertEqual(entries[-1]["level"], "INFO")
        self.assertEqual(entries[-1]["logger"], "test.mcp.ring")

    def test_entries_limit_returns_newest_slice(self) -> None:
        handler = RingBufferLogHandler(capacity=10)
        logger = logging.getLogger("test.mcp.ring2")
        logger.addHandler(handler)
        try:
            for index in range(6):
                logger.warning("w-%d", index)
        finally:
            logger.removeHandler(handler)
        self.assertEqual([entry["message"] for entry in handler.entries(2)], ["w-4", "w-5"])


class SceneNodeSerializationTests(unittest.TestCase):
    def test_rect_node_serializes_type_and_fields(self) -> None:
        payload = scene_node_to_dict(RectNode(x=1, y=2, width=3, height=4, color_rgba=(9, 8, 7, 255)))
        self.assertEqual(payload["type"], "RectNode")
        self.assertEqual(payload["x"], 1)
        self.assertEqual(payload["width"], 3)
        self.assertEqual(list(payload["color_rgba"]), [9, 8, 7, 255])


class RuntimeProviderTests(unittest.TestCase):
    def _runtime(self, *, scene: bool = False, width: int = 1, height: int = 1) -> UnifiedRuntime:
        target = _RecordingTarget()
        return UnifiedRuntime(
            matrix=WindowMatrix(width=width, height=height),
            target=target,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=_FakeSensorManager(),
            capability_decider=lambda _cap: True,
            scene_target=CpuSceneTarget(target) if scene else None,
            render_mode="scene" if scene else "auto",
        )

    def test_matrix_screenshot_reads_back_written_pixels(self) -> None:
        runtime = self._runtime()
        frame = accel.from_sequence([10, 20, 30, 40], (1, 1, 4))
        runtime._matrix.submit_write_batch(WriteBatch([FullRewrite(frame)]))
        shot = runtime._mcp_screenshot()
        self.assertEqual((shot.width, shot.height), (1, 1))
        self.assertEqual(shot.source, "matrix")
        self.assertEqual(shot.rgba, bytes([10, 20, 30, 40]))

    def test_scene_screenshot_rasterizes_latest_retained_frame(self) -> None:
        runtime = self._runtime(scene=True, width=2, height=2)
        assert runtime._scene_buffer is not None
        runtime._scene_buffer.submit(
            SceneFrame(
                revision=3,
                logical_width=2,
                logical_height=2,
                display_width=2,
                display_height=2,
                ts_ns=1,
                nodes=(
                    ClearNode((0, 0, 0, 255)),
                    RectNode(x=0, y=0, width=1, height=1, color_rgba=(255, 0, 0, 255)),
                ),
                retained=True,
            )
        )
        shot = runtime._mcp_screenshot()
        self.assertEqual((shot.width, shot.height), (2, 2))
        self.assertEqual(shot.source, "scene_retained")
        self.assertEqual(len(shot.rgba), 2 * 2 * 4)
        self.assertEqual(shot.rgba[0:4], bytes([255, 0, 0, 255]))  # top-left rect pixel
        self.assertEqual(shot.rgba[12:16], bytes([0, 0, 0, 255]))  # bottom-right clear pixel

    def test_scene_tree_serializes_latest_frame(self) -> None:
        runtime = self._runtime(scene=True, width=2, height=2)
        assert runtime._scene_buffer is not None
        runtime._scene_buffer.submit(
            SceneFrame(
                revision=9,
                logical_width=2,
                logical_height=2,
                display_width=2,
                display_height=2,
                ts_ns=1,
                nodes=(
                    ClearNode((1, 2, 3, 255)),
                    RectNode(x=0, y=1, width=2, height=1, color_rgba=(4, 5, 6, 255)),
                ),
                retained=True,
            )
        )
        tree = runtime._mcp_scene_tree()
        self.assertTrue(tree["available"])
        # SceneGraphBuffer owns the revision counter; first submit lands at 1.
        self.assertEqual(tree["revision"], 1)
        self.assertTrue(tree["retained"])
        self.assertEqual([node["type"] for node in tree["nodes"]], ["ClearNode", "RectNode"])
        rect = tree["nodes"][1]
        self.assertEqual((rect["y"], rect["height"]), (1, 1))
        self.assertEqual(list(rect["color_rgba"]), [4, 5, 6, 255])

    def test_scene_tree_unavailable_without_scene_mode(self) -> None:
        runtime = self._runtime()
        tree = runtime._mcp_scene_tree()
        self.assertFalse(tree["available"])
        self.assertEqual(tree["nodes"], [])

    def test_scene_tree_reports_when_no_frame_yet(self) -> None:
        runtime = self._runtime(scene=True, width=2, height=2)
        tree = runtime._mcp_scene_tree()
        self.assertFalse(tree["available"])
        self.assertIn("no scene frame", tree["reason"])


class McpInspectEndToEndTests(unittest.TestCase):
    def test_screenshot_scene_tree_and_logs_over_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "app.toml").write_text(
                'app_id = "test.mcp-inspect"\n'
                'protocol_version = "1"\n'
                'entrypoint = "app_main:create"\n'
                'required_capabilities = ["window.write"]\n'
                "optional_capabilities = []\n"
                "\n[mcp]\nenabled = true\n",
                encoding="utf-8",
            )
            (app_dir / "app_main.py").write_text(
                "import logging\n"
                "from luvatrix_core import accel\n"
                "from luvatrix_core.core.window_matrix import FullRewrite, WriteBatch\n"
                "class App:\n"
                "    def init(self, ctx):\n"
                "        frame = accel.from_sequence([200, 201, 202, 255], (1, 1, 4))\n"
                "        ctx.submit_write_batch(WriteBatch([FullRewrite(frame)]))\n"
                "    def loop(self, ctx, dt): logging.getLogger('test.mcp-inspect.app').info('tick')\n"
                "    def stop(self, ctx): pass\n"
                "def create(): return App()\n",
                encoding="utf-8",
            )
            runtime = UnifiedRuntime(
                matrix=WindowMatrix(width=1, height=1),
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

            # Screenshot: poll until the app's first write lands in the matrix.
            expected = bytes([200, 201, 202, 255])
            decoded = b""
            while time.monotonic() < deadline:
                status, body = _post_json(
                    info["url"],
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "app_screenshot", "arguments": {}},
                    },
                    token=info["token"],
                )
                self.assertEqual(status, 200)
                shot = json.loads(body["result"]["content"][0]["text"])
                self.assertEqual((shot["width"], shot["height"]), (1, 1))
                self.assertEqual(shot["format"], "raw_rgba")
                decoded = base64.b64decode(shot["data_base64"])
                if decoded == expected:
                    break
                time.sleep(0.05)
            self.assertEqual(decoded, expected)
            self.assertEqual(shot["source"], "matrix")

            # Scene tree: matrix-only app reports unavailable.
            status, body = _post_json(
                info["url"],
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "app_scene_tree", "arguments": {}},
                },
                token=info["token"],
            )
            self.assertEqual(status, 200)
            tree = json.loads(body["result"]["content"][0]["text"])
            self.assertFalse(tree["available"])

            # Logs: the app's per-tick log line shows up in the ring buffer.
            found_tick = False
            while time.monotonic() < deadline and not found_tick:
                status, body = _post_json(
                    info["url"],
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "app_logs", "arguments": {"limit": 50}},
                    },
                    token=info["token"],
                )
                self.assertEqual(status, 200)
                logs = json.loads(body["result"]["content"][0]["text"])
                found_tick = any(
                    entry["logger"] == "test.mcp-inspect.app" and entry["message"] == "tick"
                    for entry in logs["entries"]
                )
                if not found_tick:
                    time.sleep(0.05)
            self.assertTrue(found_tick)

            _post_json(
                info["url"],
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "app_stop", "arguments": {}},
                },
                token=info["token"],
            )
            thread.join(timeout=10.0)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
