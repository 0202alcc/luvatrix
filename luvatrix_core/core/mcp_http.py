"""HTTP transport for Luvatrix MCP mode.

Stdlib-only streamable-HTTP transport: one ``POST /mcp`` endpoint guarded by
a per-session bearer token, bound to loopback on an ephemeral port. SSE
streams (GET) are not served in v1.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any

from .mcp_protocol import McpDispatcher

_MAX_BODY_BYTES = 4 * 1024 * 1024


class McpHttpServer:
    """Serves one :class:`McpDispatcher` over HTTP on a background thread."""

    def __init__(self, dispatcher: McpDispatcher, *, token: str, host: str = "127.0.0.1", port: int = 0) -> None:
        self._dispatcher = dispatcher
        self._token = token
        self._host = host
        self._requested_port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._requested_port
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/mcp"

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("MCP HTTP server already started")
        token = self._token
        dispatcher = self._dispatcher

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib name
                # Keep the app console clean; audit hooks capture security events.
                return

            def _send_json(self, status: int, payload: Any) -> None:
                body = json.dumps(payload).encode("utf-8") if payload is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _authorized(self) -> bool:
                header = self.headers.get("Authorization", "")
                return header == f"Bearer {token}"

            def do_GET(self) -> None:  # noqa: N802 - stdlib naming
                self.send_response(405)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802 - stdlib naming
                if self.path != "/mcp":
                    self._send_json(404, {"error": "not found"})
                    return
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized: bearer token required"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(400, {"error": "invalid Content-Length"})
                    return
                if length <= 0 or length > _MAX_BODY_BYTES:
                    self._send_json(400, {"error": "invalid Content-Length"})
                    return
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._send_json(
                        400,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32700, "message": "parse error"},
                        },
                    )
                    return
                response = dispatcher.handle_payload(payload)
                if response is None:
                    # Pure notification: accepted, nothing to return.
                    self._send_json(202, None)
                    return
                self._send_json(200, response)

        self._server = ThreadingHTTPServer((self._host, self._requested_port), _Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="luvatrix-mcp-http",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._server = None
        self._thread = None
