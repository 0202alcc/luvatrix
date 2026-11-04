from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from luvatrix.auth import (
    InMemoryWorkosTokenStore,
    SecureWorkosTokenStore,
    WorkosAuthError,
    WorkosConnectClient,
    WorkosConnectConfig,
    WorkosSessionExpiredError,
    WorkosToken,
)
from luvatrix.net import HttpRequest, HttpResponse, TransportError

AUTHKIT = "https://login.nomic.ai"


def _b64url(payload: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")


def _id_token(claims: dict[str, object]) -> str:
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(claims)}.signature"


def _token_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "token_type": "Bearer",
        "id_token": _id_token({"email": "ada@example.com", "name": "Ada Lovelace", "nonce": "test-nonce"}),
    }
    payload.update(overrides)
    return payload


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self._queue: list[HttpResponse | Exception] = []

    def queue(self, status: int, payload: object) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self._queue.append(HttpResponse(status=status, headers={}, body=body))

    def queue_error(self, error: Exception) -> None:
        self._queue.append(error)

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse:
        self.requests.append(request)
        assert self._queue, "FakeTransport received an unqueued request"
        queued = self._queue.pop(0)
        if isinstance(queued, Exception):
            raise queued
        return queued


def _config(**overrides: object) -> WorkosConnectConfig:
    values: dict[str, object] = {
        "authkit_domain": AUTHKIT,
        "client_id": "client_01JTEST",
        "redirect_uri": "nomic-ios://auth/callback",
    }
    values.update(overrides)
    return WorkosConnectConfig(**values)  # type: ignore[arg-type]


def _client(
    transport: FakeTransport,
    store: InMemoryWorkosTokenStore | None = None,
    **config_overrides: object,
) -> WorkosConnectClient:
    return WorkosConnectClient(
        _config(**config_overrides),
        token_store=store if store is not None else InMemoryWorkosTokenStore(),
        transport=transport,
        clock=lambda: 100.0,
    )


def _posted_form(request: HttpRequest) -> dict[str, list[str]]:
    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    return parse_qs((request.body or b"").decode("utf-8"))


def test_authorization_url_uses_workos_connect_shape() -> None:
    client = _client(FakeTransport())

    request = client.start_authorization(state="state-1", nonce="nonce-1")

    parsed = urlparse(request.url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{AUTHKIT}/oauth2/authorize"
    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["client_01JTEST"]
    assert query["redirect_uri"] == ["nomic-ios://auth/callback"]
    assert query["scope"] == ["openid profile email offline_access"]
    assert query["state"] == ["state-1"]
    assert query["nonce"] == ["nonce-1"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(request.code_verifier) >= 43
    assert query["code_challenge"][0] != request.code_verifier
    assert request.matches_state("state-1")
    assert not request.matches_state("state-2")


def test_authorization_url_generates_state_and_nonce() -> None:
    client = _client(FakeTransport())

    first = client.start_authorization()
    second = client.start_authorization()

    assert first.state and first.nonce
    assert first.state != second.state
    assert first.nonce != second.nonce


def test_authkit_domain_trailing_slash_is_normalized() -> None:
    client = _client(FakeTransport(), authkit_domain=f"{AUTHKIT}/")

    request = client.start_authorization(state="s", nonce="n")

    assert request.url.startswith(f"{AUTHKIT}/oauth2/authorize?")


def test_config_requires_values() -> None:
    with pytest.raises(ValueError):
        _config(client_id=" ")
    with pytest.raises(ValueError):
        _config(redirect_uri="")
    with pytest.raises(ValueError):
        _config(authkit_domain="")


def test_exchange_code_posts_authorization_code_grant() -> None:
    transport = FakeTransport()
    transport.queue(200, _token_payload())
    store = InMemoryWorkosTokenStore()
    client = _client(transport, store)

    token, identity = client.exchange_code("code-1", code_verifier="verifier-1", nonce="test-nonce")

    request = transport.requests[0]
    assert request.url == f"{AUTHKIT}/oauth2/token"
    form = _posted_form(request)
    assert form["grant_type"] == ["authorization_code"]
    assert form["client_id"] == ["client_01JTEST"]
    assert form["code"] == ["code-1"]
    assert form["code_verifier"] == ["verifier-1"]
    assert form["redirect_uri"] == ["nomic-ios://auth/callback"]

    assert token.access_token == "access-1"
    assert token.refresh_token == "refresh-1"
    assert token.token_type == "Bearer"
    assert token.expires_at == 3700.0
    assert identity.email == "ada@example.com"
    assert identity.name == "Ada Lovelace"
    assert store.load() == token


def test_exchange_code_rejects_nonce_mismatch() -> None:
    transport = FakeTransport()
    transport.queue(200, _token_payload())
    store = InMemoryWorkosTokenStore()
    client = _client(transport, store)

    with pytest.raises(WorkosAuthError):
        client.exchange_code("code-1", code_verifier="v", nonce="other-nonce")
    assert store.load() is None


def test_exchange_code_requires_email_claim() -> None:
    transport = FakeTransport()
    transport.queue(200, _token_payload(id_token=_id_token({"nonce": "test-nonce"})))
    client = _client(transport)

    with pytest.raises(WorkosAuthError):
        client.exchange_code("code-1", code_verifier="v", nonce="test-nonce")


def test_exchange_code_invalid_grant_raises_session_expired() -> None:
    transport = FakeTransport()
    transport.queue(400, {"error": "invalid_grant"})
    client = _client(transport)

    with pytest.raises(WorkosSessionExpiredError):
        client.exchange_code("spent-code", code_verifier="v", nonce="n")


def test_exchange_code_server_error_is_transient() -> None:
    transport = FakeTransport()
    transport.queue(500, {"error": "temporarily_unavailable"})
    client = _client(transport)

    with pytest.raises(WorkosAuthError) as caught:
        client.exchange_code("code-1", code_verifier="v", nonce="n")
    assert not isinstance(caught.value, WorkosSessionExpiredError)


def test_exchange_code_non_json_response_raises() -> None:
    transport = FakeTransport()
    transport.queue(200, b"<html>proxy error</html>")
    client = _client(transport)

    with pytest.raises(WorkosAuthError):
        client.exchange_code("code-1", code_verifier="v", nonce="n")


def test_exchange_code_response_without_access_token_raises() -> None:
    transport = FakeTransport()
    transport.queue(200, {"expires_in": 5})
    client = _client(transport)

    with pytest.raises(WorkosAuthError):
        client.exchange_code("code-1", code_verifier="v", nonce="n")


def _stored_token(store: InMemoryWorkosTokenStore, **overrides: object) -> WorkosToken:
    values: dict[str, object] = {
        "access_token": "old-access",
        "token_type": "Bearer",
        "expires_at": 50.0,
        "refresh_token": "refresh-1",
    }
    values.update(overrides)
    token = WorkosToken(**values)  # type: ignore[arg-type]
    store.save(token)
    return token


def test_current_token_returns_unexpired_without_network() -> None:
    transport = FakeTransport()
    store = InMemoryWorkosTokenStore()
    _stored_token(store, expires_at=10_000.0)
    client = _client(transport, store)

    token = client.current_token()

    assert token is not None and token.access_token == "old-access"
    assert transport.requests == []


def test_current_token_none_when_signed_out() -> None:
    assert _client(FakeTransport()).current_token() is None


def test_expired_token_refreshes_and_rotates_refresh_token() -> None:
    transport = FakeTransport()
    transport.queue(200, {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 60})
    store = InMemoryWorkosTokenStore()
    _stored_token(store)
    client = _client(transport, store)

    token = client.current_token()

    assert token is not None
    assert token.access_token == "access-2"
    assert token.refresh_token == "refresh-2"
    assert token.expires_at == 160.0
    assert store.load() == token
    form = _posted_form(transport.requests[0])
    assert form["grant_type"] == ["refresh_token"]
    assert form["client_id"] == ["client_01JTEST"]
    assert form["refresh_token"] == ["refresh-1"]


def test_refresh_keeps_old_refresh_token_when_response_omits_one() -> None:
    transport = FakeTransport()
    transport.queue(200, {"access_token": "access-2", "expires_in": 60})
    store = InMemoryWorkosTokenStore()
    _stored_token(store)
    client = _client(transport, store)

    token = client.refresh()

    assert token.refresh_token == "refresh-1"
    assert store.load() == token


def test_refresh_invalid_grant_raises_session_expired() -> None:
    transport = FakeTransport()
    transport.queue(400, {"error": "invalid_grant"})
    store = InMemoryWorkosTokenStore()
    _stored_token(store)
    client = _client(transport, store)

    with pytest.raises(WorkosSessionExpiredError):
        client.refresh()


def test_refresh_without_refresh_token_raises() -> None:
    store = InMemoryWorkosTokenStore()
    _stored_token(store, refresh_token=None)
    client = _client(FakeTransport(), store)

    with pytest.raises(WorkosAuthError):
        client.refresh()


def test_transport_failure_raises_workos_auth_error() -> None:
    transport = FakeTransport()
    transport.queue_error(TransportError("connection reset"))
    store = InMemoryWorkosTokenStore()
    _stored_token(store)
    client = _client(transport, store)

    with pytest.raises(WorkosAuthError):
        client.refresh()


def test_access_token_helpers_feed_http_client_auth() -> None:
    transport = FakeTransport()
    store = InMemoryWorkosTokenStore()
    _stored_token(store, expires_at=10_000.0)
    client = _client(transport, store)

    assert client.access_token() == "old-access"

    empty = _client(FakeTransport())
    assert empty.access_token() is None


def test_secure_token_store_round_trip() -> None:
    values: dict[str, str] = {}
    store = SecureWorkosTokenStore(
        read_secret=values.get,
        write_secret=values.__setitem__,
        delete_secret=values.pop,
        key="nomic.workos",
    )
    assert store.load() is None

    token = WorkosToken(
        access_token="a",
        token_type="Bearer",
        expires_at=123.0,
        refresh_token="r",
        scope="openid profile email offline_access",
    )
    store.save(token)

    assert store.load() == token
    store.clear()
    assert store.load() is None


def test_secure_token_store_rejects_corrupt_value() -> None:
    store = SecureWorkosTokenStore(
        read_secret=lambda _key: '{"access_token": 1}',
        write_secret=lambda _key, _value: None,
        delete_secret=lambda _key: None,
        key="nomic.workos",
    )

    with pytest.raises(WorkosAuthError):
        store.load()
