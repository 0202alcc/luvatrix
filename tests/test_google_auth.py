from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from io import BytesIO

import pytest

from luvatrix.auth import GoogleAuthError, GoogleOAuthClient, GoogleOAuthConfig, InMemoryTokenStore
from luvatrix.auth import google as google_module


def _config() -> GoogleOAuthConfig:
    return GoogleOAuthConfig(
        client_id="client-id.apps.googleusercontent.com",
        redirect_uri="com.example.calendar:/oauth2redirect",
        scopes=("https://www.googleapis.com/auth/calendar.readonly",),
    )


def test_authorization_request_uses_pkce_and_requested_scopes() -> None:
    client = GoogleOAuthClient(_config())

    request = client.start_authorization(state="test-state")
    query = parse_qs(urlparse(request.url).query)

    assert query["state"] == ["test-state"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert len(request.code_verifier) >= 43
    assert query["code_challenge"][0] != request.code_verifier
    assert request.matches_state("test-state")
    assert not request.matches_state("other-state")


def test_exchange_code_saves_google_token() -> None:
    requests: list[dict[str, str]] = []
    store = InMemoryTokenStore()

    def post_form(_url: str, payload: dict[str, str]) -> dict[str, object]:
        requests.append(payload)
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    client = GoogleOAuthClient(_config(), token_store=store, post_form=post_form, clock=lambda: 100.0)
    token = client.exchange_code("auth-code", code_verifier="verifier")

    assert requests[0]["grant_type"] == "authorization_code"
    assert token.expires_at == 3700.0
    assert store.load() == token


def test_current_token_refreshes_expired_token() -> None:
    store = InMemoryTokenStore()
    client = GoogleOAuthClient(
        _config(),
        token_store=store,
        clock=lambda: 100.0,
        post_form=lambda _url, payload: {
            "access_token": "refreshed-access-token",
            "expires_in": 3600,
            "scope": payload["grant_type"],
        },
    )
    store.save(
        client._token_from_response(
            {"access_token": "old-access-token", "refresh_token": "refresh-token", "expires_in": 1}
        )
    )

    token = client.current_token()

    assert token is not None
    assert token.access_token == "refreshed-access-token"
    assert token.refresh_token == "refresh-token"


def test_refresh_requires_refresh_token() -> None:
    client = GoogleOAuthClient(_config())

    with pytest.raises(GoogleAuthError, match="refresh token"):
        client.refresh()


def test_client_preserves_falsey_token_store() -> None:
    class FalseyTokenStore(InMemoryTokenStore):
        def __bool__(self) -> bool:
            return False

    store = FalseyTokenStore()

    client = GoogleOAuthClient(_config(), token_store=store)

    assert client.token_store is store


def test_token_transport_preserves_google_http_error(monkeypatch) -> None:
    response = HTTPError(
        "https://oauth2.googleapis.com/token",
        400,
        "Bad Request",
        {},
        BytesIO(b'{"error":"invalid_grant","error_description":"Authorization code expired"}'),
    )
    monkeypatch.setattr(google_module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(response))

    client = GoogleOAuthClient(_config())
    with pytest.raises(GoogleAuthError, match="Authorization code expired"):
        client.exchange_code("expired", code_verifier="verifier")


def test_token_transport_preserves_network_failure_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        google_module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("DNS unavailable")),
    )

    client = GoogleOAuthClient(_config())
    with pytest.raises(GoogleAuthError, match="DNS unavailable"):
        client.exchange_code("code", code_verifier="verifier")


@pytest.mark.parametrize("expires_in", ["nan", "inf", "-inf"])
def test_token_response_rejects_non_finite_expiry(expires_in: str) -> None:
    client = GoogleOAuthClient(_config(), clock=lambda: 100.0)

    with pytest.raises(GoogleAuthError, match="invalid expires_in"):
        client._token_from_response({"access_token": "access-token", "expires_in": expires_in})
