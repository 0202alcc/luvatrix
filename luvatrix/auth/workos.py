"""WorkOS Connect OAuth provider for the native Nomic client.

Authorization-code flow with PKCE (S256) against the workspace's AuthKit
domain, mirroring the first-party Nomic Connect clients (the Revit add-in and
the Outlook add-in in drive-next):

- authorize: ``GET {authkit_domain}/oauth2/authorize`` with ``state``,
  ``nonce``, and an S256 ``code_challenge``;
- exchange: ``POST {authkit_domain}/oauth2/token`` with the code and verifier,
  returning an access token, a refresh token, and an ID token that carries the
  user's identity;
- refresh: same endpoint with ``grant_type=refresh_token``. WorkOS rotates the
  refresh token on use; when the response omits one, the old token stays valid.

The ID token is decoded without verifying its signature, which OIDC allows for
a token received straight from the token endpoint over TLS; the access token
is what the Nomic API actually checks.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import secrets
import time
from typing import Callable, Mapping, Protocol
from urllib.parse import urlencode

from ..net import HttpRequest, Transport, TransportError, UrllibTransport

WORKOS_AUTHORIZE_PATH = "/oauth2/authorize"
WORKOS_TOKEN_PATH = "/oauth2/token"
DEFAULT_WORKOS_SCOPES = ("openid", "profile", "email", "offline_access")


class WorkosAuthError(RuntimeError):
    """WorkOS rejected or could not complete an OAuth operation."""


class WorkosSessionExpiredError(WorkosAuthError):
    """The grant is spent (``invalid_grant``): the user must sign in again."""


@dataclass(frozen=True)
class WorkosConnectConfig:
    """One first-party WorkOS Connect OAuth app registration."""

    authkit_domain: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = DEFAULT_WORKOS_SCOPES

    def __post_init__(self) -> None:
        if not self.authkit_domain.strip():
            raise ValueError("authkit_domain is required")
        if not self.client_id.strip():
            raise ValueError("client_id is required")
        if not self.redirect_uri.strip():
            raise ValueError("redirect_uri is required")
        if not self.scopes:
            raise ValueError("at least one OAuth scope is required")
        object.__setattr__(self, "authkit_domain", self.authkit_domain.rstrip("/"))


@dataclass(frozen=True)
class WorkosAuthorizationRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str

    def matches_state(self, returned_state: str | None) -> bool:
        return bool(returned_state) and secrets.compare_digest(self.state, returned_state)


@dataclass(frozen=True)
class WorkosToken:
    access_token: str
    token_type: str
    expires_at: float
    refresh_token: str | None = None
    scope: str | None = None

    def is_expired(self, *, now: float | None = None, leeway_seconds: float = 60.0) -> bool:
        return float(now if now is not None else time.time()) >= self.expires_at - leeway_seconds


@dataclass(frozen=True)
class WorkosIdentity:
    email: str
    name: str | None = None


class WorkosTokenStore(Protocol):
    """Persistence boundary for WorkOS tokens; implementations should be secure."""

    def load(self) -> WorkosToken | None: ...

    def save(self, token: WorkosToken) -> None: ...

    def clear(self) -> None: ...


class InMemoryWorkosTokenStore:
    """Ephemeral token store suited to tests and short-lived app sessions."""

    def __init__(self) -> None:
        self._token: WorkosToken | None = None

    def load(self) -> WorkosToken | None:
        return self._token

    def save(self, token: WorkosToken) -> None:
        self._token = token

    def clear(self) -> None:
        self._token = None


class SecureWorkosTokenStore:
    """Token store backed by platform-provided Keychain or Keystore operations."""

    def __init__(
        self,
        *,
        read_secret: Callable[[str], str | None],
        write_secret: Callable[[str, str], None],
        delete_secret: Callable[[str], None],
        key: str,
    ) -> None:
        if not key.strip():
            raise ValueError("secure token store key is required")
        self._read_secret = read_secret
        self._write_secret = write_secret
        self._delete_secret = delete_secret
        self._key = key

    def load(self) -> WorkosToken | None:
        encoded = self._read_secret(self._key)
        if encoded is None:
            return None
        try:
            payload = json.loads(encoded)
            if not isinstance(payload, dict):
                raise ValueError
            return WorkosToken(
                access_token=str(payload["access_token"]),
                token_type=str(payload["token_type"]),
                expires_at=float(payload["expires_at"]),
                refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
                scope=str(payload["scope"]) if payload.get("scope") else None,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkosAuthError("The securely stored WorkOS token is invalid") from exc

    def save(self, token: WorkosToken) -> None:
        self._write_secret(
            self._key,
            json.dumps(
                {
                    "access_token": token.access_token,
                    "token_type": token.token_type,
                    "expires_at": token.expires_at,
                    "refresh_token": token.refresh_token,
                    "scope": token.scope,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    def clear(self) -> None:
        self._delete_secret(self._key)


class WorkosConnectClient:
    """Platform-neutral WorkOS Connect client using authorization code + PKCE."""

    def __init__(
        self,
        config: WorkosConnectConfig,
        *,
        token_store: WorkosTokenStore | None = None,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.token_store = token_store if token_store is not None else InMemoryWorkosTokenStore()
        self._transport = transport if transport is not None else UrllibTransport()
        self._clock = clock

    def start_authorization(
        self,
        *,
        state: str | None = None,
        nonce: str | None = None,
    ) -> WorkosAuthorizationRequest:
        state = state or secrets.token_urlsafe(24)
        nonce = nonce or secrets.token_urlsafe(24)
        code_verifier = secrets.token_urlsafe(64)
        parameters = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        url = f"{self.config.authkit_domain}{WORKOS_AUTHORIZE_PATH}?{urlencode(parameters)}"
        return WorkosAuthorizationRequest(
            url=url,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )

    def exchange_code(
        self,
        code: str,
        *,
        code_verifier: str,
        nonce: str,
    ) -> tuple[WorkosToken, WorkosIdentity]:
        if not code.strip():
            raise ValueError("authorization code is required")
        if not code_verifier.strip():
            raise ValueError("PKCE code_verifier is required")
        status, payload = self._post_form(
            {
                "grant_type": "authorization_code",
                "client_id": self.config.client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": self.config.redirect_uri,
            }
        )
        token = self._token_from_response(status, payload)
        identity = self._identity_from_response(payload, nonce=nonce)
        self.token_store.save(token)
        return token, identity

    def refresh(self, token: WorkosToken | None = None) -> WorkosToken:
        token = token or self.token_store.load()
        if token is None or not token.refresh_token:
            raise WorkosAuthError("no refresh token is available")
        status, payload = self._post_form(
            {
                "grant_type": "refresh_token",
                "client_id": self.config.client_id,
                "refresh_token": token.refresh_token,
            }
        )
        refreshed = self._token_from_response(status, payload, fallback_refresh_token=token.refresh_token)
        self.token_store.save(refreshed)
        return refreshed

    def current_token(self, *, refresh_if_needed: bool = True) -> WorkosToken | None:
        token = self.token_store.load()
        if token is not None and refresh_if_needed and token.is_expired(now=self._clock()):
            return self.refresh(token)
        return token

    def access_token(self) -> str | None:
        """A live access token for `HttpClient` bearer auth, refreshing as needed."""
        token = self.current_token()
        return token.access_token if token is not None else None

    def _post_form(self, payload: dict[str, str]) -> tuple[int, dict[str, object]]:
        request = HttpRequest(
            method="POST",
            url=f"{self.config.authkit_domain}{WORKOS_TOKEN_PATH}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(payload).encode("utf-8"),
        )
        try:
            response = self._transport.send(request)
        except TransportError as exc:
            raise WorkosAuthError(f"WorkOS token request failed: {exc}") from exc
        try:
            parsed = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WorkosAuthError(
                f"WorkOS token response was not valid JSON (HTTP {response.status})"
            ) from exc
        if not isinstance(parsed, dict):
            raise WorkosAuthError(f"WorkOS token response was not a JSON object (HTTP {response.status})")
        return response.status, parsed

    def _token_from_response(
        self,
        status: int,
        payload: Mapping[str, object],
        *,
        fallback_refresh_token: str | None = None,
    ) -> WorkosToken:
        if not 200 <= status < 300:
            detail = str(payload.get("error") or f"HTTP {status}")
            if status == 400 and payload.get("error") == "invalid_grant":
                raise WorkosSessionExpiredError(detail)
            raise WorkosAuthError(f"WorkOS token request failed ({status}, {detail})")
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            # A 200 without tokens is a WorkOS bug, not a spent grant: callers
            # keep the session and retry rather than signing the user out.
            raise WorkosAuthError("WorkOS token response did not include an access token")
        try:
            expires_in = float(payload.get("expires_in", 3600))
        except (TypeError, ValueError) as exc:
            raise WorkosAuthError("WorkOS token response has an invalid expires_in value") from exc
        if not math.isfinite(expires_in):
            raise WorkosAuthError("WorkOS token response has an invalid expires_in value")
        refresh_token = str(payload.get("refresh_token") or "") or fallback_refresh_token
        return WorkosToken(
            access_token=access_token,
            token_type=str(payload.get("token_type") or "Bearer"),
            expires_at=self._clock() + max(0.0, expires_in),
            refresh_token=refresh_token,
            scope=str(payload.get("scope") or "") or None,
        )

    def _identity_from_response(self, payload: Mapping[str, object], *, nonce: str) -> WorkosIdentity:
        id_token = str(payload.get("id_token") or "")
        if not id_token:
            raise WorkosAuthError("WorkOS token response did not include an ID token")
        claims = _decode_id_token(id_token)
        if claims is None:
            raise WorkosAuthError("WorkOS ID token was malformed")
        if claims.get("nonce") != nonce:
            raise WorkosAuthError("WorkOS sign-in answer was not for this sign-in (nonce mismatch)")
        email = str(claims.get("email") or "").strip()
        if not email:
            raise WorkosAuthError("WorkOS ID token did not include an email")
        name = str(claims.get("name") or "").strip()
        if not name:
            parts = [str(claims.get(key) or "").strip() for key in ("given_name", "family_name")]
            name = " ".join(part for part in parts if part)
        return WorkosIdentity(email=email, name=name or None)


def _pkce_challenge(code_verifier: str) -> str:
    digest = sha256(code_verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _decode_id_token(id_token: str) -> dict[str, object] | None:
    parts = id_token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        claims = json.loads(urlsafe_b64decode(payload + padding))
    except (ValueError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None
