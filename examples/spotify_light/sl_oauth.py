"""Spotify OAuth (Authorization Code + PKCE) primitives. Stub module — see tests."""
from __future__ import annotations

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_PORT = 8888

SCOPES = (
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


class OAuthError(Exception):
    pass


class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str
    token_type: str

    def needs_refresh(self, now: float) -> bool: raise NotImplementedError
    def with_fallback_refresh(self, previous: "TokenSet") -> "TokenSet": raise NotImplementedError
    def to_json(self) -> dict: raise NotImplementedError

    @staticmethod
    def from_json(payload: dict) -> "TokenSet": raise NotImplementedError


def generate_verifier() -> str: raise NotImplementedError
def challenge_s256(verifier: str) -> str: raise NotImplementedError
def generate_state() -> str: raise NotImplementedError
def redirect_uri_for_port(port: int) -> str: raise NotImplementedError
def authorize_url(*, client_id: str, redirect_uri: str, challenge: str, state: str) -> str: raise NotImplementedError
def parse_callback_query(query: str, expected_state: str) -> str: raise NotImplementedError
def extract_callback_query(request_line: str) -> str | None: raise NotImplementedError
def parse_token_response(body: str, *, now: float) -> TokenSet: raise NotImplementedError
def exchange_code(*, client_id: str, redirect_uri: str, code: str, verifier: str, http_post=None, now: float = 0.0) -> TokenSet: raise NotImplementedError
def refresh_tokens(client_id: str, refresh_token: str, *, http_post=None, now: float = 0.0) -> TokenSet: raise NotImplementedError


class LoopbackReceiver:
    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port

    def start(self) -> None: raise NotImplementedError
    def wait_for_code(self, *, expected_state: str, timeout: float) -> str: raise NotImplementedError
    def close(self) -> None: raise NotImplementedError
