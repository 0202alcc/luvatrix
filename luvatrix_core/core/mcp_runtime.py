"""Runtime-side MCP bridge: tool registry, capability gating, and the
discovery file that lets local MCP clients find a running app session.

The bridge owns no sockets. ``McpHttpServer`` (see ``mcp_http``) serves the
dispatcher produced by :meth:`McpRuntimeBridge.dispatcher`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import tempfile
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
    "discovery_file_path",
    "generate_session_token",
    "mcp_capabilities_for_allow",
    "read_discovery_file",
    "remove_discovery_file",
    "write_discovery_file",
]

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
        audit_logger: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._app_id = app_id
        self._granted = set(granted_capabilities)
        self._state_provider = state_provider
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
                name="app_stop",
                description="Request a graceful stop of the app run loop.",
                input_schema={"type": "object", "properties": {}},
                capability="mcp.control",
            ),
        ]

    def _handle_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "app_state":
            return {"app_id": self._app_id, "runtime": self._state_provider()}
        if name == "app_stop":
            self._stop_requested = True
            return {"stopping": True}
        raise KeyError(f"unknown tool: {name}")
