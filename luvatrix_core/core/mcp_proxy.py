"""``luvatrix mcp-proxy``: bridge MCP stdio clients to a running app session.

MCP's stdio transport is newline-delimited JSON-RPC. This proxy reads NDJSON
messages from stdin, forwards each one to the app's streamable-HTTP endpoint
(from the session discovery file) with the bearer token, and writes each
response back to stdout as one line.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, TextIO
import urllib.error
import urllib.request

from .mcp_runtime import discovery_file_path, read_discovery_file

_MAX_LINE_BYTES = 4 * 1024 * 1024


def load_session_info(target: str | Path) -> dict[str, Any]:
    """Load session info from an app directory or a direct session file path."""
    path = Path(target)
    if path.is_dir():
        session_file = discovery_file_path(path)
        if not session_file.exists():
            raise FileNotFoundError(
                f"no MCP session file at {session_file} — is the app running with --mcp?"
            )
        return read_discovery_file(path)
    if not path.exists():
        raise FileNotFoundError(
            f"MCP session file not found: {path} — is the app running with --mcp?"
        )
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "url" not in data or "token" not in data:
        raise ValueError(f"invalid MCP session file: {path}")
    return data


def _forward(url: str, token: str, payload: Any, *, timeout_s: float = 30.0) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        raw = response.read().decode("utf-8")
        return response.status, (json.loads(raw) if raw else None)


def run_proxy(
    target: str | Path,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Forward NDJSON stdio messages to the app's MCP HTTP session until EOF."""
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout
    info = load_session_info(target)
    url = str(info["url"])
    token = str(info["token"])

    def _emit(message: dict[str, Any]) -> None:
        out_stream.write(json.dumps(message) + "\n")
        out_stream.flush()

    for line in in_stream:
        if len(line) > _MAX_LINE_BYTES:
            _emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "line too long"}})
            continue
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except ValueError:
            _emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        message_id = payload.get("id") if isinstance(payload, dict) else None
        try:
            status, body = _forward(url, token, payload)
        except (OSError, urllib.error.URLError):
            _emit(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {
                        "code": -32603,
                        "message": "MCP session unreachable (is the app still running?)",
                    },
                }
            )
            continue
        if status == 202 or body is None:
            # Pure notification: nothing to send back.
            continue
        _emit(body)
    return 0
