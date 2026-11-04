from __future__ import annotations

import json

import pytest

from luvatrix.net import ApiError, HttpClient, HttpRequest, HttpResponse


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self.timeouts: list[float | None] = []
        self._queue: list[HttpResponse] = []

    def queue(self, status: int = 200, body: bytes = b"{}", headers: dict[str, str] | None = None) -> None:
        self._queue.append(HttpResponse(status=status, headers=headers or {}, body=body))

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        assert self._queue, "FakeTransport received an unqueued request"
        return self._queue.pop(0)


def _client(transport: FakeTransport, **kwargs: object) -> HttpClient:
    return HttpClient("https://tenant.example.com/api/v0", transport=transport, **kwargs)  # type: ignore[arg-type]


def test_url_for_joins_base_url_and_path() -> None:
    client = _client(FakeTransport())

    assert client.url_for("/agents") == "https://tenant.example.com/api/v0/agents"
    assert client.url_for("agents") == "https://tenant.example.com/api/v0/agents"

    trailing = HttpClient("https://tenant.example.com/api/v0/", transport=FakeTransport())
    assert trailing.url_for("/agents") == "https://tenant.example.com/api/v0/agents"


def test_url_for_passes_absolute_urls_through() -> None:
    client = _client(FakeTransport())
    assert client.url_for("https://other.example.com/x") == "https://other.example.com/x"


def test_get_json_sends_bearer_token_and_parses_body() -> None:
    transport = FakeTransport()
    transport.queue(body=b'{"data": []}')
    client = _client(transport, bearer_token="token-123")

    result = client.get_json("/agents")

    assert result == {"data": []}
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url == "https://tenant.example.com/api/v0/agents"
    assert request.headers["Authorization"] == "Bearer token-123"


def test_bearer_token_provider_is_resolved_per_request() -> None:
    transport = FakeTransport()
    transport.queue(body=b"{}")
    transport.queue(body=b"{}")
    current = {"token": "first"}
    client = _client(transport, bearer_token=lambda: current["token"])

    client.get_json("/a")
    current["token"] = "second"
    client.get_json("/b")

    assert transport.requests[0].headers["Authorization"] == "Bearer first"
    assert transport.requests[1].headers["Authorization"] == "Bearer second"


def test_request_without_token_omits_authorization_header() -> None:
    transport = FakeTransport()
    transport.queue(body=b"{}")
    client = _client(transport)

    client.get_json("/agents")

    assert "Authorization" not in transport.requests[0].headers


def test_post_json_serializes_payload_and_content_type() -> None:
    transport = FakeTransport()
    transport.queue(status=201, body=b'{"data": {"id": "a1"}}')
    client = _client(transport, bearer_token="t")

    result = client.post_json("/agents", {"prompt": {"text": "hello"}})

    assert result == {"data": {"id": "a1"}}
    request = transport.requests[0]
    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.body or b"") == {"prompt": {"text": "hello"}}


def test_api_error_carries_status_and_body() -> None:
    transport = FakeTransport()
    transport.queue(status=404, body=b'{"error": "Agent not found", "code": "not_found"}')
    client = _client(transport)

    with pytest.raises(ApiError) as caught:
        client.get_json("/agents/nope")

    error = caught.value
    assert error.status == 404
    assert error.body == b'{"error": "Agent not found", "code": "not_found"}'
    assert error.json() == {"error": "Agent not found", "code": "not_found"}


def test_default_and_per_request_headers_merge() -> None:
    transport = FakeTransport()
    transport.queue(body=b"{}")
    client = _client(transport, headers={"X-App": "nomic-ios", "X-Default": "d"})

    client.get_json("/x", headers={"X-Default": "overridden"})

    headers = transport.requests[0].headers
    assert headers["X-App"] == "nomic-ios"
    assert headers["X-Default"] == "overridden"


def test_client_default_timeout_flows_to_transport() -> None:
    transport = FakeTransport()
    transport.queue(body=b"{}")
    client = _client(transport, timeout=7.5)

    client.get_json("/x")

    assert transport.timeouts == [7.5]


def test_post_multipart_builds_form_data_body() -> None:
    transport = FakeTransport()
    transport.queue(body=b'{"id": "f1"}')
    client = _client(transport, bearer_token="t")

    result = client.post_multipart(
        "/files/upload",
        fields={"path": "reports/2026/quarterly.pdf"},
        file_field="file",
        filename="quarterly.pdf",
        content=b"%PDF-fake",
        content_type="application/pdf",
    )

    assert result == {"id": "f1"}
    request = transport.requests[0]
    assert request.method == "POST"
    content_type = request.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1].encode("utf-8")
    body = request.body or b""
    assert body.startswith(b"--" + boundary)
    assert body.rstrip().endswith(b"--" + boundary + b"--")
    assert b'Content-Disposition: form-data; name="path"' in body
    assert b"reports/2026/quarterly.pdf" in body
    assert b'Content-Disposition: form-data; name="file"; filename="quarterly.pdf"' in body
    assert b"Content-Type: application/pdf" in body
    assert b"%PDF-fake" in body
    # Field parts precede the file part so servers can route on them early.
    assert body.index(b'name="path"') < body.index(b'name="file"')
