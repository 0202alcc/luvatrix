"""Google OAuth 2.0 authorization-code flow with PKCE for Luvatrix apps."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import secrets
import time
from typing import Callable, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleAuthError(RuntimeError):
    """Raised when Google rejects or cannot complete an OAuth operation."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...]
    client_secret: str | None = None

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("client_id is required")
        if not self.redirect_uri.strip():
            raise ValueError("redirect_uri is required")
        if not self.scopes:
            raise ValueError("at least one OAuth scope is required")


@dataclass(frozen=True)
class GoogleAuthorizationRequest:
    url: str
    state: str
    code_verifier: str

    def matches_state(self, returned_state: str | None) -> bool:
        return bool(returned_state) and secrets.compare_digest(self.state, returned_state)


@dataclass(frozen=True)
class GoogleOAuthToken:
    access_token: str
    token_type: str
    expires_at: float
    refresh_token: str | None = None
    scope: str | None = None

    def is_expired(self, *, now: float | None = None, leeway_seconds: float = 60.0) -> bool:
        return float(now if now is not None else time.time()) >= self.expires_at - leeway_seconds


class TokenStore(Protocol):
    """Persistence boundary for OAuth tokens; implementations should be secure."""

    def load(self) -> GoogleOAuthToken | None: ...

    def save(self, token: GoogleOAuthToken) -> None: ...

    def clear(self) -> None: ...


class InMemoryTokenStore:
    """Ephemeral token store suited to tests and short-lived app sessions."""

    def __init__(self) -> None:
        self._token: GoogleOAuthToken | None = None

    def load(self) -> GoogleOAuthToken | None:
        return self._token

    def save(self, token: GoogleOAuthToken) -> None:
        self._token = token

    def clear(self) -> None:
        self._token = None


FormPost = Callable[[str, dict[str, str]], dict[str, object]]


class GoogleOAuthClient:
    """Platform-neutral Google OAuth client using authorization code + PKCE."""

    def __init__(
        self,
        config: GoogleOAuthConfig,
        *,
        token_store: TokenStore | None = None,
        post_form: FormPost | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.token_store = token_store if token_store is not None else InMemoryTokenStore()
        self._post_form = post_form or _post_form
        self._clock = clock

    def start_authorization(self, *, state: str | None = None) -> GoogleAuthorizationRequest:
        state = state or secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        parameters = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.config.scopes),
            "state": state,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return GoogleAuthorizationRequest(
            url=f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}",
            state=state,
            code_verifier=code_verifier,
        )

    def exchange_code(self, code: str, *, code_verifier: str) -> GoogleOAuthToken:
        if not code.strip():
            raise ValueError("authorization code is required")
        if not code_verifier.strip():
            raise ValueError("PKCE code_verifier is required")
        payload = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret
        token = self._token_from_response(self._post_form(GOOGLE_TOKEN_ENDPOINT, payload))
        self.token_store.save(token)
        return token

    def refresh(self, token: GoogleOAuthToken | None = None) -> GoogleOAuthToken:
        token = token or self.token_store.load()
        if token is None or not token.refresh_token:
            raise GoogleAuthError("no refresh token is available")
        payload = {
            "client_id": self.config.client_id,
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret
        refreshed = self._token_from_response(
            self._post_form(GOOGLE_TOKEN_ENDPOINT, payload),
            refresh_token=token.refresh_token,
        )
        self.token_store.save(refreshed)
        return refreshed

    def current_token(self, *, refresh_if_needed: bool = True) -> GoogleOAuthToken | None:
        token = self.token_store.load()
        if token is not None and refresh_if_needed and token.is_expired(now=self._clock()):
            return self.refresh(token)
        return token

    def _token_from_response(
        self,
        payload: dict[str, object],
        *,
        refresh_token: str | None = None,
    ) -> GoogleOAuthToken:
        if "error" in payload:
            detail = str(payload.get("error_description") or payload["error"])
            raise GoogleAuthError(detail)
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise GoogleAuthError("Google token response did not include an access token")
        try:
            expires_in = float(payload.get("expires_in", 3600))
        except (TypeError, ValueError) as exc:
            raise GoogleAuthError("Google token response has an invalid expires_in value") from exc
        if not math.isfinite(expires_in):
            raise GoogleAuthError("Google token response has an invalid expires_in value")
        response_refresh_token = str(payload.get("refresh_token") or "")
        return GoogleOAuthToken(
            access_token=access_token,
            token_type=str(payload.get("token_type") or "Bearer"),
            expires_at=self._clock() + max(0.0, expires_in),
            refresh_token=response_refresh_token or refresh_token,
            scope=str(payload.get("scope") or "") or None,
        )


def _pkce_challenge(code_verifier: str) -> str:
    digest = sha256(code_verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _post_form(url: str, payload: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise GoogleAuthError("Google token request failed") from exc
    if not isinstance(data, dict):
        raise GoogleAuthError("Google token response was not a JSON object")
    return data
