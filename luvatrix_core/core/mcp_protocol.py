"""Pure JSON-RPC 2.0 / MCP protocol dispatch for Luvatrix MCP mode.

This module has no I/O. It turns decoded JSON-RPC payloads into response
payloads (or ``None`` for notifications). Transport lives in
``luvatrix_core.core.mcp_http``; tool behavior lives in
``luvatrix_core.core.mcp_runtime``.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

# MCP protocol revision spoken by this server (streamable HTTP era).
MCP_PROTOCOL_VERSION = "2025-03-26"

SERVER_NAME = "luvatrix-mcp"
SERVER_VERSION = "1"

JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

#: Runtime-side MCP capability families. ``[mcp] allow = [...]`` manifest
#: entries use the short names in ``MCP_ALLOW_NAMES``.
MCP_CAPABILITIES: tuple[str, ...] = ("mcp.inspect", "mcp.input", "mcp.control", "mcp.app")

MCP_ALLOW_NAMES: tuple[str, ...] = tuple(capability.removeprefix("mcp.") for capability in MCP_CAPABILITIES)


@dataclass(frozen=True)
class McpToolSpec:
    """Static description of one MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    capability: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _result(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


class McpDispatcher:
    """Dispatches JSON-RPC 2.0 messages for the MCP server.

    ``tool_handler`` receives ``(tool_name, arguments_dict)`` and returns a
    JSON-serializable payload. It is only invoked for tools whose capability
    is in ``granted_capabilities``.
    """

    def __init__(
        self,
        *,
        app_id: str,
        tools: list[McpToolSpec],
        granted_capabilities: set[str],
        tool_handler: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        self._app_id = app_id
        self._tools = {tool.name: tool for tool in tools}
        self._granted = set(granted_capabilities)
        self._tool_handler = tool_handler

    def handle_payload(self, payload: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Handle one decoded JSON payload. Returns None when there is nothing to send back."""
        if isinstance(payload, list):
            if not payload:
                return _error(None, JSONRPC_INVALID_REQUEST, "empty batch")
            responses = [self._handle_message(item) for item in payload]
            return [response for response in responses if response is not None]
        return self._handle_message(payload)

    def _handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error(None, JSONRPC_INVALID_REQUEST, "message must be an object")
        message_id = message.get("id")
        is_notification = "id" not in message
        if message.get("jsonrpc") != "2.0":
            if is_notification:
                return None
            return _error(message_id, JSONRPC_INVALID_REQUEST, "jsonrpc must be \"2.0\"")
        method = message.get("method")
        if not isinstance(method, str):
            if is_notification:
                return None
            return _error(message_id, JSONRPC_INVALID_REQUEST, "method must be a string")

        if method == "initialize":
            return None if is_notification else _result(message_id, self._initialize_result())
        if method == "ping":
            return None if is_notification else _result(message_id, {})
        if method == "tools/list":
            return None if is_notification else _result(message_id, {"tools": self._visible_tools()})
        if method == "tools/call":
            if is_notification:
                return None
            return self._handle_tool_call(message_id, message.get("params"))
        if method.startswith("notifications/"):
            return None
        if is_notification:
            return None
        return _error(message_id, JSONRPC_METHOD_NOT_FOUND, f"unknown method: {method}")

    def _initialize_result(self) -> dict[str, Any]:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION, "appId": self._app_id},
            "capabilities": {"tools": {"listChanged": False}},
        }

    def _visible_tools(self) -> list[dict[str, Any]]:
        return [tool.to_wire() for tool in self._tools.values() if tool.capability in self._granted]

    def _handle_tool_call(self, message_id: Any, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            return _error(message_id, JSONRPC_INVALID_PARAMS, "tools/call params must be an object")
        name = params.get("name")
        if not isinstance(name, str):
            return _error(message_id, JSONRPC_INVALID_PARAMS, "tools/call params.name must be a string")
        tool = self._tools.get(name)
        if tool is None:
            return _error(message_id, JSONRPC_METHOD_NOT_FOUND, f"unknown tool: {name}")
        if tool.capability not in self._granted:
            return _error(
                message_id,
                JSONRPC_METHOD_NOT_FOUND,
                f"tool not available: {name} (capability {tool.capability} not granted)",
            )
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(message_id, JSONRPC_INVALID_PARAMS, "tools/call params.arguments must be an object")
        try:
            payload = self._tool_handler(name, arguments)
        except Exception as exc:  # noqa: BLE001 - tool errors surface as MCP tool errors
            return _result(
                message_id,
                {"content": [{"type": "text", "text": f"tool error: {exc}"}], "isError": True},
            )
        return _result(
            message_id,
            {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "isError": False,
            },
        )
