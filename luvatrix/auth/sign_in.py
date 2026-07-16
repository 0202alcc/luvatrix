"""Event-driven Google sign-in orchestration for Luvatrix apps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
from threading import RLock
import time
from typing import Callable, Mapping, Protocol
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from .google import GoogleAuthError, GoogleAuthorizationRequest, GoogleOAuthClient, GoogleOAuthToken


GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleSignInState(str, Enum):
    IDLE = "idle"
    OPENING = "opening"
    WAITING = "waiting"
    EXCHANGING = "exchanging"
    LOADING_PROFILE = "loading_profile"
    SIGNED_IN = "signed_in"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class GoogleProfile:
    subject: str
    email: str | None = None
    name: str | None = None
    picture_url: str | None = None
    email_verified: bool | None = None


class GoogleAuthSession(Protocol):
    """Trusted platform browser session used to collect an OAuth callback."""

    def open(self, authorization_url: str, callback: Callable[[str | None], None]) -> None: ...

    def cancel(self) -> None: ...


class PlatformGoogleAuthSession:
    """Bridge a trusted platform browser launcher to native callback delivery."""

    def __init__(self, *, open_browser: Callable[[str], object]) -> None:
        self._open_browser = open_browser
        self._callback: Callable[[str | None], None] | None = None
        self._lock = RLock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._callback is not None

    def open(self, authorization_url: str, callback: Callable[[str | None], None]) -> None:
        with self._lock:
            if self._callback is not None:
                raise GoogleAuthError("A platform authentication session is already active")
            self._callback = callback
        try:
            opened = self._open_browser(authorization_url)
            if opened is False:
                raise GoogleAuthError("The platform could not open the Google sign-in page")
        except Exception:
            with self._lock:
                self._callback = None
            raise

    def deliver_callback(self, callback_url: str) -> bool:
        with self._lock:
            callback = self._callback
            self._callback = None
        if callback is None:
            return False
        callback(callback_url)
        return True

    def cancel(self) -> None:
        with self._lock:
            callback = self._callback
            self._callback = None
        if callback is not None:
            callback(None)


class SecureTokenStore:
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

    def load(self) -> GoogleOAuthToken | None:
        encoded = self._read_secret(self._key)
        if encoded is None:
            return None
        try:
            payload = json.loads(encoded)
            if not isinstance(payload, dict):
                raise ValueError
            return GoogleOAuthToken(
                access_token=str(payload["access_token"]),
                token_type=str(payload["token_type"]),
                expires_at=float(payload["expires_at"]),
                refresh_token=str(payload["refresh_token"]) if payload.get("refresh_token") else None,
                scope=str(payload["scope"]) if payload.get("scope") else None,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GoogleAuthError("The securely stored Google token is invalid") from exc

    def save(self, token: GoogleOAuthToken) -> None:
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


@dataclass(frozen=True)
class PendingGoogleAuthorization:
    """A short-lived PKCE request saved while the system browser is open."""

    request: GoogleAuthorizationRequest
    redirect_uri: str
    created_at: float


class AuthorizationRequestStore(Protocol):
    """Persistence boundary for a pending OAuth request."""

    def load(self) -> PendingGoogleAuthorization | None: ...

    def save(
        self,
        request: GoogleAuthorizationRequest,
        *,
        redirect_uri: str,
        created_at: float,
    ) -> None: ...

    def clear(self) -> None: ...


class SecureAuthorizationRequestStore:
    """Persist pending Google PKCE state using platform secure storage."""

    def __init__(
        self,
        *,
        read_secret: Callable[[str], str | None],
        write_secret: Callable[[str, str], None],
        delete_secret: Callable[[str], None],
        key: str,
    ) -> None:
        if not key.strip():
            raise ValueError("secure authorization request store key is required")
        self._read_secret = read_secret
        self._write_secret = write_secret
        self._delete_secret = delete_secret
        self._key = key

    def load(self) -> PendingGoogleAuthorization | None:
        encoded = self._read_secret(self._key)
        if encoded is None:
            return None
        try:
            payload = json.loads(encoded)
            if not isinstance(payload, dict):
                raise ValueError
            created_at = float(payload["created_at"])
            if not math.isfinite(created_at):
                raise ValueError
            request = GoogleAuthorizationRequest(
                url=str(payload["url"]),
                state=str(payload["state"]),
                code_verifier=str(payload["code_verifier"]),
            )
            redirect_uri = str(payload["redirect_uri"])
            if not all((request.url, request.state, request.code_verifier, redirect_uri)):
                raise ValueError
            return PendingGoogleAuthorization(request, redirect_uri, created_at)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GoogleAuthError("The securely stored Google authorization request is invalid") from exc

    def save(
        self,
        request: GoogleAuthorizationRequest,
        *,
        redirect_uri: str,
        created_at: float,
    ) -> None:
        timestamp = float(created_at)
        if not math.isfinite(timestamp):
            raise ValueError("authorization request timestamp must be finite")
        self._write_secret(
            self._key,
            json.dumps(
                {
                    "url": request.url,
                    "state": request.state,
                    "code_verifier": request.code_verifier,
                    "redirect_uri": redirect_uri,
                    "created_at": timestamp,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )

    def clear(self) -> None:
        self._delete_secret(self._key)


ProfileFetcher = Callable[[GoogleOAuthToken], Mapping[str, object]]


class GoogleSignInController:
    """Coordinate trusted browser UI, OAuth exchange, profile loading, and app redraws."""

    def __init__(
        self,
        oauth: GoogleOAuthClient,
        *,
        session: GoogleAuthSession,
        fetch_profile: ProfileFetcher | None = None,
        invalidate: Callable[[], None] | None = None,
        pending_authorization_store: AuthorizationRequestStore | None = None,
        authorization_max_age_seconds: float = 600.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if "openid" not in oauth.config.scopes:
            raise ValueError("GoogleSignInController requires the 'openid' OAuth scope")
        self.oauth = oauth
        self.session = session
        self._fetch_profile = fetch_profile or _fetch_google_profile
        self._invalidate = invalidate
        max_age = float(authorization_max_age_seconds)
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError("authorization_max_age_seconds must be finite and positive")
        self._pending_authorization_store = pending_authorization_store
        self._authorization_max_age_seconds = max_age
        self._clock = clock
        self._lock = RLock()
        self.state = GoogleSignInState.IDLE
        self.token: GoogleOAuthToken | None = None
        self.profile: GoogleProfile | None = None
        self.error: GoogleAuthError | None = None
        self._authorization: GoogleAuthorizationRequest | None = None

    @property
    def pending_state(self) -> str | None:
        with self._lock:
            return self._authorization.state if self._authorization is not None else None

    @property
    def signed_in(self) -> bool:
        return self.state is GoogleSignInState.SIGNED_IN

    @property
    def busy(self) -> bool:
        return self.state in {
            GoogleSignInState.OPENING,
            GoogleSignInState.WAITING,
            GoogleSignInState.EXCHANGING,
            GoogleSignInState.LOADING_PROFILE,
        }

    def sign_in(self) -> None:
        with self._lock:
            if self.busy:
                raise GoogleAuthError("Google sign-in is already in progress")
            self.error = None
            self.profile = None
            self._authorization = self.oauth.start_authorization()
            authorization_url = self._authorization.url
            self.state = GoogleSignInState.OPENING
            authorization = self._authorization
        self._notify()
        try:
            if self._pending_authorization_store is not None:
                self._pending_authorization_store.save(
                    authorization,
                    redirect_uri=self.oauth.config.redirect_uri,
                    created_at=self._clock(),
                )
            self.session.open(authorization_url, self.handle_callback)
        except Exception as exc:
            self._fail("Could not open the Google sign-in session", exc)
            return
        with self._lock:
            if self.state is GoogleSignInState.OPENING:
                self.state = GoogleSignInState.WAITING
        self._notify()

    def deliver_callback(self, callback_url: str) -> bool:
        """Deliver a native callback, restoring saved PKCE state after process death."""
        session_delivery = getattr(self.session, "deliver_callback", None)
        if callable(session_delivery) and session_delivery(callback_url):
            return True
        with self._lock:
            authorization_active = self._authorization is not None and self.busy
        if authorization_active:
            self.handle_callback(callback_url)
            return True
        store = self._pending_authorization_store
        if store is None:
            return False
        try:
            pending = store.load()
            if pending is None:
                return False
            if pending.redirect_uri != self.oauth.config.redirect_uri:
                raise GoogleAuthError("Saved Google sign-in request used a different redirect URI")
            age = self._clock() - pending.created_at
            if not math.isfinite(age) or age < 0 or age > self._authorization_max_age_seconds:
                raise GoogleAuthError("Saved Google sign-in request expired")
        except GoogleAuthError as exc:
            self._fail(str(exc), exc)
            return False
        except Exception as exc:
            self._fail("Saved Google sign-in request could not be restored", exc)
            return False
        with self._lock:
            self._authorization = pending.request
            self.error = None
            self.state = GoogleSignInState.WAITING
        self.handle_callback(callback_url)
        return True

    def handle_callback(self, callback_url: str | None) -> None:
        if callback_url is None:
            self._cancelled()
            return
        with self._lock:
            authorization = self._authorization
        if authorization is None or not self.busy:
            self._fail("No Google sign-in request is active")
            return
        try:
            query = _validated_callback_query(callback_url, self.oauth.config.redirect_uri)
            returned_state = _one(query, "state")
            if not authorization.matches_state(returned_state):
                raise GoogleAuthError("Google sign-in callback state did not match")
            provider_error = _one(query, "error")
            if provider_error:
                if provider_error == "access_denied":
                    self._cancelled()
                    return
                detail = _one(query, "error_description") or provider_error
                raise GoogleAuthError(f"Google sign-in failed: {detail}")
            code = _one(query, "code")
            if not code:
                raise GoogleAuthError("Google sign-in callback did not include an authorization code")
            self._set_state(GoogleSignInState.EXCHANGING)
            token = self.oauth.exchange_code(code, code_verifier=authorization.code_verifier)
            self._set_state(GoogleSignInState.LOADING_PROFILE)
            profile = _profile_from_payload(self._fetch_profile(token))
        except GoogleAuthError as exc:
            self._fail(str(exc), exc)
            return
        except Exception as exc:
            self._fail("Google sign-in could not be completed", exc)
            return
        with self._lock:
            self.token = token
            self.profile = profile
            self.error = None
            self._authorization = None
            self.state = GoogleSignInState.SIGNED_IN
        self._clear_pending_authorization()
        self._notify()

    def restore(self) -> GoogleOAuthToken | None:
        try:
            token = self.oauth.current_token()
            if token is None:
                self.sign_out()
                return None
            profile = _profile_from_payload(self._fetch_profile(token))
        except Exception as exc:
            self._fail("Saved Google sign-in could not be restored", exc)
            return None
        with self._lock:
            self.token = token
            self.profile = profile
            self.error = None
            self.state = GoogleSignInState.SIGNED_IN
        self._notify()
        return token

    def cancel(self) -> None:
        if self.busy:
            try:
                self.session.cancel()
            finally:
                self._cancelled()

    def sign_out(self) -> None:
        self.oauth.token_store.clear()
        self._clear_pending_authorization()
        with self._lock:
            self.token = None
            self.profile = None
            self.error = None
            self._authorization = None
            self.state = GoogleSignInState.IDLE
        self._notify()

    def _set_state(self, state: GoogleSignInState) -> None:
        with self._lock:
            self.state = state
        self._notify()

    def _cancelled(self) -> None:
        with self._lock:
            self.error = None
            self._authorization = None
            self.state = GoogleSignInState.CANCELLED
        self._clear_pending_authorization()
        self._notify()

    def _fail(self, message: str, cause: Exception | None = None) -> None:
        error = cause if isinstance(cause, GoogleAuthError) else GoogleAuthError(message)
        if cause is not None and error is not cause:
            error.__cause__ = cause
        with self._lock:
            self.error = error
            self._authorization = None
            self.state = GoogleSignInState.FAILED
        self._clear_pending_authorization()
        self._notify()

    def _clear_pending_authorization(self) -> None:
        if self._pending_authorization_store is None:
            return
        try:
            self._pending_authorization_store.clear()
        except Exception:
            pass

    def _notify(self) -> None:
        if self._invalidate is not None:
            self._invalidate()


def _validated_callback_query(callback_url: str, redirect_uri: str) -> dict[str, list[str]]:
    callback = urlparse(callback_url)
    expected = urlparse(redirect_uri)
    if (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path):
        raise GoogleAuthError("Google sign-in callback did not match the configured redirect URI")
    return parse_qs(callback.query, keep_blank_values=True)


def _one(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _profile_from_payload(payload: Mapping[str, object]) -> GoogleProfile:
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise GoogleAuthError("Google profile response did not include a subject")
    verified = payload.get("email_verified")
    return GoogleProfile(
        subject=subject,
        email=str(payload.get("email") or "") or None,
        name=str(payload.get("name") or "") or None,
        picture_url=str(payload.get("picture") or "") or None,
        email_verified=verified if isinstance(verified, bool) else None,
    )


def _fetch_google_profile(token: GoogleOAuthToken) -> Mapping[str, object]:
    request = Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": f"{token.token_type} {token.access_token}"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise GoogleAuthError("Google profile request failed") from exc
    if not isinstance(payload, dict):
        raise GoogleAuthError("Google profile response was not a JSON object")
    return payload
