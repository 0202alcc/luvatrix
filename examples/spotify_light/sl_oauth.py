"""Spotify OAuth: Authorization Code flow with PKCE over a loopback redirect.

No client secret is used or stored; the app is a public client. Tokens come
from https://accounts.spotify.com/api/token and are handled by `TokenSet`.
HTTP boundaries are injectable callables so tests need no network.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import string
import time
import urllib.parse
import urllib.request

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_PORT = 8888
REDIRECT_PATH = "/callback"
REFRESH_SKEW_SECS = 60
DEFAULT_EXPIRES_IN_SECS = 3600

_SCOPES = (
    "user-read-private",
    "user-read-email",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-top-read",
)
SCOPES = _SCOPES

_VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"


class OAuthError(Exception):
    """Authorization failed or was denied."""


class TokenSet:
    __slots__ = ("access_token", "refresh_token", "expires_at", "scope", "token_type")

    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str | None,
        expires_at: float,
        scope: str = "",
        token_type: str = "Bearer",
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = float(expires_at)
        self.scope = scope
        self.token_type = token_type

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TokenSet):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __repr__(self) -> str:
        return f"TokenSet(expires_at={self.expires_at!r}, scope={self.scope!r})"

    def needs_refresh(self, now: float) -> bool:
        return float(now) >= self.expires_at - REFRESH_SKEW_SECS

    def with_fallback_refresh(self, previous: "TokenSet | None") -> "TokenSet":
        if self.refresh_token or previous is None:
            return self
        return TokenSet(
            access_token=self.access_token,
            refresh_token=previous.refresh_token,
            expires_at=self.expires_at,
            scope=self.scope or previous.scope,
            token_type=self.token_type,
        )

    def to_json(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
        }

    @staticmethod
    def from_json(payload: dict) -> "TokenSet":
        return TokenSet(
            access_token=str(payload["access_token"]),
            refresh_token=payload.get("refresh_token"),
            expires_at=float(payload.get("expires_at", 0.0)),
            scope=str(payload.get("scope", "")),
            token_type=str(payload.get("token_type", "Bearer")),
        )


def generate_verifier() -> str:
    return "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(64))


def challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    return "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(32))


def redirect_uri_for_port(port: int) -> str:
    return f"http://127.0.0.1:{port}{REDIRECT_PATH}"


def authorize_url(*, client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        "scope": " ".join(SCOPES),
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def parse_callback_query(query: str, expected_state: str) -> str:
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    error = params.get("error", [None])[0]
    if error:
        raise OAuthError(f"Spotify authorization failed: {error}")
    state = params.get("state", [""])[0]
    if state != expected_state:
        raise OAuthError("OAuth state mismatch; rejecting callback (possible CSRF)")
    code = params.get("code", [""])[0]
    if not code:
        raise OAuthError("OAuth callback did not include an authorization code")
    return code


def parse_callback_url(url: str, expected_state: str) -> str:
    """Full loopback callback URL -> authorization code.

    Used by the embedded web-view flow, which intercepts the redirect before
    any request hits the loopback receiver.
    """
    return parse_callback_query(urllib.parse.urlsplit(url).query, expected_state)


def extract_callback_query(request_line: str) -> str | None:
    parts = request_line.split(" ")
    if len(parts) < 2 or parts[0] != "GET":
        return None
    target = parts[1]
    if not target.startswith(REDIRECT_PATH):
        return None
    _, sep, query = target.partition("?")
    return query if sep else ""


def parse_token_response(body: str, *, now: float) -> TokenSet:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OAuthError(f"token endpoint returned a non-JSON response: {exc}") from exc
    if not isinstance(payload, dict):
        raise OAuthError("token endpoint returned an unexpected payload")
    if "error" in payload:
        description = payload.get("error_description") or payload.get("error") or "unknown error"
        raise OAuthError(str(description))
    access_token = payload.get("access_token")
    if not access_token:
        raise OAuthError("token endpoint response did not include an access token")
    expires_in = payload.get("expires_in", DEFAULT_EXPIRES_IN_SECS)
    try:
        lifetime = float(expires_in)
    except (TypeError, ValueError):
        lifetime = float(DEFAULT_EXPIRES_IN_SECS)
    return TokenSet(
        access_token=str(access_token),
        refresh_token=payload.get("refresh_token"),
        expires_at=float(now) + lifetime,
        scope=str(payload.get("scope", "")),
        token_type=str(payload.get("token_type", "Bearer")),
    )


def _default_http_post(url: str, form: dict[str, str], headers: dict[str, str] | None = None) -> str:
    data = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Surface Spotify's error body (invalid_grant etc.) to the caller.
        return exc.read().decode("utf-8")


def exchange_code(
    *,
    client_id: str,
    redirect_uri: str,
    code: str,
    verifier: str,
    http_post=None,
    now: float | None = None,
) -> TokenSet:
    post = http_post or _default_http_post
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    body = post(TOKEN_URL, form)
    return parse_token_response(body, now=time.time() if now is None else now)


def refresh_tokens(
    client_id: str,
    refresh_token: str,
    *,
    http_post=None,
    now: float | None = None,
) -> TokenSet:
    post = http_post or _default_http_post
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    body = post(TOKEN_URL, form)
    return parse_token_response(body, now=time.time() if now is None else now)


_SUCCESS_HTML = b"""<!doctype html><html><head><title>Spotify Light</title></head>
<body style="font-family:sans-serif;background:#121212;color:#fff;text-align:center;padding-top:4em">
<h2>Connected to Spotify Light</h2><p>You can close this tab and return to the app.</p>
</body></html>"""


class LoopbackReceiver:
    """One-shot HTTP receiver for the OAuth loopback redirect."""

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.requested_port = port
        self.port = port
        self._sock: socket.socket | None = None

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.requested_port))
        sock.listen(1)
        sock.settimeout(0.2)
        self._sock = sock
        self.port = int(sock.getsockname()[1])

    def wait_for_code(self, *, expected_state: str, timeout: float) -> str:
        if self._sock is None:
            raise OAuthError("loopback receiver is not started")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                raise OAuthError(f"loopback receiver stopped: {exc}") from exc
            with conn:
                request_line = self._read_request_line(conn)
                query = extract_callback_query(request_line) if request_line else None
                if query is None:
                    self._respond(conn, 404, b"not found")
                    continue
                self._respond(conn, 200, _SUCCESS_HTML)
                return parse_callback_query(query, expected_state)
        raise OAuthError(f"Spotify login timed out after {timeout:.0f}s")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    @staticmethod
    def _read_request_line(conn: socket.socket) -> str:
        data = b""
        conn.settimeout(2.0)
        while b"\r\n" not in data and len(data) < 8192:
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
        return data.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")

    @staticmethod
    def _respond(conn: socket.socket, status: int, body: bytes) -> None:
        reason = b"OK" if status == 200 else b"Not Found"
        head = (
            f"HTTP/1.1 {status} {reason.decode()}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1")
        conn.sendall(head + body)
