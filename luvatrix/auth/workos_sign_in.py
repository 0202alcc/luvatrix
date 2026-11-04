"""Event-driven WorkOS Connect sign-in orchestration for Luvatrix apps.

`WorkosSignInCoordinator` ties together the platform-neutral
`WorkosConnectClient` PKCE machinery, a platform browser session (on iOS,
ASWebAuthenticationSession behind the bridge in
``luvatrix_core.platform.ios.auth_session``), and a secure token store. On
launch the app calls ``restore`` for a silent sign-in from the stored
refresh token; when no usable session exists it calls ``begin_sign_in`` and
the platform delivers the `ainomic://auth/callback` URL back into
``handle_callback``. ``access_token`` is a plain callable ready for
`luvatrix.net.HttpClient` bearer auth; a spent grant clears the store and
re-prompts instead of failing requests.

Configuration comes from the app's ``app.toml`` (``[auth.workos]``) with
environment overrides, until the instance discovery endpoint lands:

    [auth.workos]
    instance_url = "https://app.nomic.ai"
    authkit_domain = "https://login.nomic.ai"
    client_id = "client_01J..."

Environment variables (matching the drive-next names) win over app.toml:
``NOMIC_INSTANCE_URL``, ``WORKOS_AUTHKIT_DOMAIN``, ``NOMIC_IOS_CLIENT_ID``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from threading import RLock
import time
import tomllib
from typing import Callable, Mapping, Protocol
from urllib.parse import parse_qs, urlparse

from .workos import (
    WorkosAuthError,
    WorkosAuthorizationRequest,
    WorkosConnectClient,
    WorkosConnectConfig,
    WorkosIdentity,
    WorkosSessionExpiredError,
    WorkosToken,
    WorkosTokenStore,
)

DEFAULT_REDIRECT_URI = "ainomic://auth/callback"

ENV_INSTANCE_URL = "NOMIC_INSTANCE_URL"
ENV_AUTHKIT_DOMAIN = "WORKOS_AUTHKIT_DOMAIN"
ENV_CLIENT_ID = "NOMIC_IOS_CLIENT_ID"

APP_TOML_SECTION = ("auth", "workos")


class WorkosSignInState(str, Enum):
    SIGNED_OUT = "signed_out"
    OPENING = "opening"
    WAITING = "waiting"
    EXCHANGING = "exchanging"
    SIGNED_IN = "signed_in"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkosSignInConfig:
    """Everything sign-in needs: the Nomic instance plus its WorkOS Connect app."""

    instance_url: str
    authkit_domain: str
    client_id: str
    redirect_uri: str = DEFAULT_REDIRECT_URI

    def __post_init__(self) -> None:
        instance_url = self.instance_url.strip().rstrip("/")
        parsed = urlparse(instance_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"instance_url must be an http(s) URL: {self.instance_url!r}")
        if not self.authkit_domain.strip():
            raise ValueError("authkit_domain is required")
        if not self.client_id.strip():
            raise ValueError("client_id is required")
        if not self.redirect_uri.strip():
            raise ValueError("redirect_uri is required")
        object.__setattr__(self, "instance_url", instance_url)


def load_workos_sign_in_config(
    *,
    app_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> WorkosSignInConfig:
    """Merge ``[auth.workos]`` from app.toml with environment overrides."""
    values = _read_app_toml_auth(Path(app_dir) / "app.toml") if app_dir is not None else {}
    env = os.environ if environ is None else environ
    for key, env_var in (
        ("instance_url", ENV_INSTANCE_URL),
        ("authkit_domain", ENV_AUTHKIT_DOMAIN),
        ("client_id", ENV_CLIENT_ID),
    ):
        override = env.get(env_var, "").strip()
        if override:
            values[key] = override
    missing = [key for key in ("instance_url", "authkit_domain", "client_id") if not values.get(key)]
    if missing:
        raise WorkosAuthError(
            "WorkOS sign-in is not configured; missing "
            + ", ".join(missing)
            + ". Set them in app.toml [auth.workos] or via "
            + ", ".join((ENV_INSTANCE_URL, ENV_AUTHKIT_DOMAIN, ENV_CLIENT_ID))
            + "."
        )
    return WorkosSignInConfig(
        instance_url=str(values["instance_url"]),
        authkit_domain=str(values["authkit_domain"]),
        client_id=str(values["client_id"]),
        redirect_uri=str(values.get("redirect_uri") or DEFAULT_REDIRECT_URI),
    )


def _read_app_toml_auth(path: Path) -> dict[str, str]:
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    section: object = raw
    for key in APP_TOML_SECTION:
        if not isinstance(section, Mapping):
            return {}
        section = section.get(key)
    if not isinstance(section, Mapping):
        return {}
    return {str(key): str(value) for key, value in section.items() if isinstance(value, str)}


class WorkosAuthSession(Protocol):
    """Trusted platform browser session used to collect the OAuth callback."""

    def open(self, authorization_url: str, callback: Callable[[str | None], None]) -> None: ...

    def cancel(self) -> None: ...


class WorkosSignInCoordinator:
    """Coordinate browser UI, PKCE exchange, token persistence, and app redraws."""

    def __init__(
        self,
        config: WorkosSignInConfig,
        *,
        session: WorkosAuthSession,
        token_store: WorkosTokenStore | None = None,
        transport=None,
        clock: Callable[[], float] = time.time,
        invalidate: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.session = session
        self.client = WorkosConnectClient(
            WorkosConnectConfig(
                authkit_domain=config.authkit_domain,
                client_id=config.client_id,
                redirect_uri=config.redirect_uri,
            ),
            token_store=token_store,
            transport=transport,
            clock=clock,
        )
        self._invalidate = invalidate
        self._lock = RLock()
        self.state = WorkosSignInState.SIGNED_OUT
        self.identity: WorkosIdentity | None = None
        self.error: WorkosAuthError | None = None
        self._authorization: WorkosAuthorizationRequest | None = None

    @property
    def pending_state(self) -> str | None:
        with self._lock:
            return self._authorization.state if self._authorization is not None else None

    @property
    def pending_nonce(self) -> str | None:
        with self._lock:
            return self._authorization.nonce if self._authorization is not None else None

    @property
    def signed_in(self) -> bool:
        return self.state is WorkosSignInState.SIGNED_IN

    @property
    def busy(self) -> bool:
        return self.state in {
            WorkosSignInState.OPENING,
            WorkosSignInState.WAITING,
            WorkosSignInState.EXCHANGING,
        }

    def restore(self) -> WorkosToken | None:
        """Silent sign-in on launch from the stored token, refreshing if needed."""
        try:
            token = self.client.current_token()
        except WorkosSessionExpiredError:
            self.client.token_store.clear()
            self._set_state(WorkosSignInState.SIGNED_OUT)
            return None
        except WorkosAuthError as exc:
            # Transient failures (offline launch) keep the stored session so the
            # next launch can retry the refresh.
            self._fail("Saved WorkOS sign-in could not be restored", exc)
            return None
        with self._lock:
            if token is None:
                self.state = WorkosSignInState.SIGNED_OUT
            else:
                self.error = None
                self.state = WorkosSignInState.SIGNED_IN
        self._notify()
        return token

    def begin_sign_in(self) -> None:
        with self._lock:
            if self.busy:
                raise WorkosAuthError("WorkOS sign-in is already in progress")
            self.error = None
            self._authorization = self.client.start_authorization()
            authorization_url = self._authorization.url
            self.state = WorkosSignInState.OPENING
        self._notify()
        try:
            self.session.open(authorization_url, self.handle_callback)
        except Exception as exc:
            self._fail("Could not open the WorkOS sign-in session", exc)
            return
        with self._lock:
            if self.state is WorkosSignInState.OPENING:
                self.state = WorkosSignInState.WAITING
        self._notify()

    def handle_callback(self, callback_url: str | None) -> None:
        if callback_url is None:
            self._cancelled()
            return
        with self._lock:
            authorization = self._authorization
        if authorization is None or not self.busy:
            self._fail("No WorkOS sign-in request is active")
            return
        try:
            query = _validated_callback_query(callback_url, self.config.redirect_uri)
            returned_state = _one(query, "state")
            if not authorization.matches_state(returned_state):
                raise WorkosAuthError("WorkOS sign-in callback state did not match")
            provider_error = _one(query, "error")
            if provider_error:
                if provider_error == "access_denied":
                    self._cancelled()
                    return
                detail = _one(query, "error_description") or provider_error
                raise WorkosAuthError(f"WorkOS sign-in failed: {detail}")
            code = _one(query, "code")
            if not code:
                raise WorkosAuthError("WorkOS sign-in callback did not include an authorization code")
            self._set_state(WorkosSignInState.EXCHANGING)
            _token, identity = self.client.exchange_code(
                code,
                code_verifier=authorization.code_verifier,
                nonce=authorization.nonce,
            )
        except WorkosAuthError as exc:
            self._fail(str(exc), exc)
            return
        except Exception as exc:
            self._fail("WorkOS sign-in could not be completed", exc)
            return
        with self._lock:
            self.identity = identity
            self.error = None
            self._authorization = None
            self.state = WorkosSignInState.SIGNED_IN
        self._notify()

    def cancel(self) -> None:
        if self.busy:
            try:
                self.session.cancel()
            finally:
                self._cancelled()

    def sign_out(self) -> None:
        self.client.token_store.clear()
        with self._lock:
            self.identity = None
            self.error = None
            self._authorization = None
            self.state = WorkosSignInState.SIGNED_OUT
        self._notify()

    def access_token(self) -> str | None:
        """A live access token for `HttpClient`, re-prompting when the grant is spent."""
        try:
            return self.client.access_token()
        except WorkosSessionExpiredError:
            self.client.token_store.clear()
            with self._lock:
                self.identity = None
            try:
                self.begin_sign_in()
            except WorkosAuthError:
                self._set_state(WorkosSignInState.SIGNED_OUT)
            return None

    def _set_state(self, state: WorkosSignInState) -> None:
        with self._lock:
            self.state = state
        self._notify()

    def _cancelled(self) -> None:
        with self._lock:
            self.error = None
            self._authorization = None
            self.state = WorkosSignInState.CANCELLED
        self._notify()

    def _fail(self, message: str, cause: Exception | None = None) -> None:
        error = cause if isinstance(cause, WorkosAuthError) else WorkosAuthError(message)
        if cause is not None and error is not cause:
            error.__cause__ = cause
        with self._lock:
            self.error = error
            self._authorization = None
            self.state = WorkosSignInState.FAILED
        self._notify()

    def _notify(self) -> None:
        if self._invalidate is not None:
            self._invalidate()


def _validated_callback_query(callback_url: str, redirect_uri: str) -> dict[str, list[str]]:
    callback = urlparse(callback_url)
    expected = urlparse(redirect_uri)
    if (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path):
        raise WorkosAuthError("WorkOS sign-in callback did not match the configured redirect URI")
    return parse_qs(callback.query, keep_blank_values=True)


def _one(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None
