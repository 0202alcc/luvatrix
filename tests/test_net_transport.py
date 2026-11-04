from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from luvatrix.net import (
    HttpRequest,
    HttpResponse,
    Transport,
    TransportError,
    UrllibTransport,
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/ok":
            self._respond(200, b'{"hello":"world"}', {"X-Test": "yes", "Content-Type": "application/json"})
        elif self.path == "/notfound":
            self._respond(404, b'{"error":"missing"}')
        elif self.path == "/slow":
            time.sleep(1.0)
            self._respond(200, b"slow")
        else:
            self._respond(500, b"oops")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        payload = json.dumps(
            {
                "contentType": self.headers.get("Content-Type"),
                "echo": body.decode("utf-8"),
                "xCustom": self.headers.get("X-Custom"),
            }
        ).encode("utf-8")
        self._respond(201, payload, {"Content-Type": "application/json"})

    def _respond(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture()
def server_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _unused_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_send_get_returns_status_headers_and_body(server_url: str) -> None:
    transport = UrllibTransport()

    response = transport.send(HttpRequest(method="GET", url=f"{server_url}/ok"))

    assert response.status == 200
    assert json.loads(response.body) == {"hello": "world"}
    assert response.headers["X-Test"] == "yes"


def test_send_post_delivers_headers_and_body(server_url: str) -> None:
    transport = UrllibTransport()

    response = transport.send(
        HttpRequest(
            method="POST",
            url=f"{server_url}/ok",
            headers={"Content-Type": "text/plain", "X-Custom": "abc"},
            body=b"payload-bytes",
        )
    )

    assert response.status == 201
    echoed = json.loads(response.body)
    assert echoed == {"contentType": "text/plain", "echo": "payload-bytes", "xCustom": "abc"}


def test_send_returns_error_status_without_raising(server_url: str) -> None:
    transport = UrllibTransport()

    response = transport.send(HttpRequest(method="GET", url=f"{server_url}/notfound"))

    assert response.status == 404
    assert json.loads(response.body) == {"error": "missing"}


def test_send_wraps_connection_failures() -> None:
    transport = UrllibTransport()

    with pytest.raises(TransportError):
        transport.send(HttpRequest(method="GET", url=f"http://127.0.0.1:{_unused_port()}/x"))


def test_send_wraps_timeouts(server_url: str) -> None:
    transport = UrllibTransport(default_timeout=10.0)

    with pytest.raises(TransportError):
        transport.send(HttpRequest(method="GET", url=f"{server_url}/slow"), timeout=0.15)


def test_urllib_transport_satisfies_transport_protocol() -> None:
    assert isinstance(UrllibTransport(), Transport)
    assert not isinstance(object(), Transport)


def test_stream_yields_status_headers_and_chunks(server_url: str) -> None:
    transport = UrllibTransport()

    with transport.stream(HttpRequest(method="GET", url=f"{server_url}/ok")) as stream:
        assert stream.status == 200
        assert stream.headers["X-Test"] == "yes"
        body = b"".join(stream)

    assert json.loads(body) == {"hello": "world"}


def test_stream_exposes_error_status(server_url: str) -> None:
    transport = UrllibTransport()

    with transport.stream(HttpRequest(method="GET", url=f"{server_url}/notfound")) as stream:
        assert stream.status == 404
        body = b"".join(stream)

    assert json.loads(body) == {"error": "missing"}


def test_http_response_is_immutable() -> None:
    response = HttpResponse(status=200, headers={}, body=b"x")
    with pytest.raises(AttributeError):
        response.status = 500  # type: ignore[misc]
