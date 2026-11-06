"""Runtime-side MCP bridge: tool registry, capability gating, and the
discovery file that lets local MCP clients find a running app session.

The bridge owns no sockets. ``McpHttpServer`` (see ``mcp_http``) serves the
dispatcher produced by :meth:`McpRuntimeBridge.dispatcher`.
"""
from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass
import dataclasses
import json
import logging
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Any, Callable, Iterable

from .mcp_protocol import (
    MCP_ALLOW_NAMES,
    MCP_CAPABILITIES,
    MCP_PROTOCOL_VERSION,
    McpDispatcher,
    McpToolSpec,
)

__all__ = [
    "MCP_ALLOW_NAMES",
    "MCP_CAPABILITIES",
    "McpRuntimeBridge",
    "McpScreenshot",
    "RingBufferLogHandler",
    "discovery_file_path",
    "generate_session_token",
    "mcp_capabilities_for_allow",
    "read_discovery_file",
    "remove_discovery_file",
    "scene_node_to_dict",
    "write_discovery_file",
]


@dataclass(frozen=True)
class McpScreenshot:
    """One raw-RGBA frame read back from the running app."""

    width: int
    height: int
    source: str  # "matrix" | "scene_retained"
    rgba: bytes


class RingBufferLogHandler(logging.Handler):
    """Thread-safe bounded capture of logging records for ``app_logs``."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__()
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        with self._lock:
            self._records.append(entry)

    def entries(self, limit: int) -> list[dict[str, Any]]:
        """Newest-last snapshot, capped to the most recent ``limit`` entries."""
        with self._lock:
            items = list(self._records)
        if limit <= 0:
            return []
        return items[-limit:]


def scene_node_to_dict(node: object) -> dict[str, Any]:
    """Serialize one scene-graph node for ``app_scene_tree``."""
    payload: dict[str, Any] = {"type": type(node).__name__}
    if dataclasses.is_dataclass(node):
        payload.update(dataclasses.asdict(node))
    return payload

_DISCOVERY_DIRNAME = ".luvatrix"
_DISCOVERY_FILENAME = "mcp-session.json"


def mcp_capabilities_for_allow(allow: Iterable[str]) -> set[str]:
    """Map ``[mcp] allow`` short names (``inspect`` ...) to capability strings."""
    return {f"mcp.{name}" for name in allow}


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def discovery_file_path(app_dir: str | Path) -> Path:
    return Path(app_dir) / _DISCOVERY_DIRNAME / _DISCOVERY_FILENAME


def write_discovery_file(
    app_dir: str | Path,
    *,
    url: str,
    token: str,
    app_id: str,
    capabilities: Iterable[str],
) -> Path:
    """Write the MCP session discovery file with owner-only permissions."""
    path = discovery_file_path(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol_version": MCP_PROTOCOL_VERSION,
        "url": url,
        "token": token,
        "pid": os.getpid(),
        "app_id": app_id,
        "capabilities": sorted(capabilities),
        "started_at": time.time(),
    }
    # Write via a private temp file so the session file never exists with
    # permissive default modes, even briefly.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".mcp-session.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return path


def read_discovery_file(app_dir: str | Path) -> dict[str, Any]:
    with discovery_file_path(app_dir).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid MCP discovery file: {discovery_file_path(app_dir)}")
    return data


def remove_discovery_file(app_dir: str | Path) -> None:
    path = discovery_file_path(app_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class McpRuntimeBridge:
    """Holds MCP tool registrations for one running app.

    Slice 1 registers the built-in ``app_state`` and ``app_stop`` tools.
    Later slices add screenshots, scene tree, logs, input injection, stepping,
    and app-defined hooks; all of them flow through the same capability gate
    and audit logger.
    """

    def __init__(
        self,
        *,
        app_id: str,
        granted_capabilities: set[str],
        state_provider: Callable[[], dict[str, Any]],
        screenshot_provider: Callable[[], McpScreenshot] | None = None,
        scene_tree_provider: Callable[[], dict[str, Any]] | None = None,
        log_provider: Callable[[int], list[dict[str, Any]]] | None = None,
        audit_logger: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._app_id = app_id
        self._granted = set(granted_capabilities)
        self._state_provider = state_provider
        self._screenshot_provider = screenshot_provider
        self._scene_tree_provider = scene_tree_provider
        self._log_provider = log_provider
        self._stop_requested = False
        self._audit_mcp_capabilities(audit_logger)
        self._tools = self._build_tools()

    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def granted_capabilities(self) -> set[str]:
        return set(self._granted)

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def dispatcher(self) -> McpDispatcher:
        return McpDispatcher(
            app_id=self._app_id,
            tools=list(self._tools),
            granted_capabilities=self._granted,
            tool_handler=self._handle_tool,
        )

    def _audit_mcp_capabilities(self, audit_logger: Callable[[dict[str, Any]], None] | None) -> None:
        if audit_logger is None:
            return
        for capability in MCP_CAPABILITIES:
            granted = capability in self._granted
            audit_logger(
                {
                    "ts_ns": time.time_ns(),
                    "action": "granted_mcp_capability" if granted else "denied_mcp_capability",
                    "capability": capability,
                    "actor": "mcp_runtime",
                    "app_id": self._app_id,
                }
            )

    def _build_tools(self) -> list[McpToolSpec]:
        return [
            McpToolSpec(
                name="app_state",
                description="Return app id plus runtime telemetry for the running app.",
                input_schema={"type": "object", "properties": {}},
                capability="mcp.inspect",
            ),
            McpToolSpec(
                name="app_screenshot",
                description=(
                    "Read back the current frame as raw RGBA bytes (base64-encoded). "
                    "Prefers the retained scene frame when scene render mode produced one, "
                    "otherwise reads the window matrix."
                ),
                input_schema={"type": "object", "properties": {}},
                capability="mcp.inspect",
            ),
            McpToolSpec(
                name="app_scene_tree",
                description="Serialize the latest retained scene frame nodes (scene render mode only).",
                input_schema={"type": "object", "properties": {}},
                capability="mcp.inspect",
            ),
            McpToolSpec(
                name="app_logs",
                description="Return recent runtime and app log records, newest last.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100,
                            "description": "Maximum number of recent entries to return.",
                        }
                    },
                },
                capability="mcp.inspect",
            ),
            McpToolSpec(
                name="app_stop",
                description="Request a graceful stop of the app run loop.",
                input_schema={"type": "object", "properties": {}},
                capability="mcp.control",
            ),
        ]

    def _handle_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "app_state":
            return {"app_id": self._app_id, "runtime": self._state_provider()}
        if name == "app_screenshot":
            if self._screenshot_provider is None:
                raise RuntimeError("app_screenshot unavailable: no frame source configured")
            shot = self._screenshot_provider()
            return {
                "width": shot.width,
                "height": shot.height,
                "format": "raw_rgba",
                "source": shot.source,
                "data_base64": base64.b64encode(shot.rgba).decode("ascii"),
            }
        if name == "app_scene_tree":
            if self._scene_tree_provider is None:
                raise RuntimeError("app_scene_tree unavailable: no scene provider configured")
            return self._scene_tree_provider()
        if name == "app_logs":
            if self._log_provider is None:
                raise RuntimeError("app_logs unavailable: no log capture configured")
            try:
                limit = int(arguments.get("limit", 100))
            except (TypeError, ValueError):
                raise RuntimeError("app_logs limit must be an integer") from None
            limit = max(1, min(1000, limit))
            return {"entries": self._log_provider(limit)}
        if name == "app_stop":
            self._stop_requested = True
            return {"stopping": True}
        raise KeyError(f"unknown tool: {name}")
