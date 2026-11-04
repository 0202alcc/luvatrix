"""ASWebAuthenticationSession browser boundary for WorkOS sign-in.

The Swift side of the native scaffold (`Luvatrix/AuthSessionBridge.swift`)
presents the session and reports the result two ways:

- the session's completion handler calls ``complete_auth_session`` with the
  callback URL, or None when the user cancelled;
- the scene delegate may deliver the same `ainomic://` callback through
  ``url_router.handle_open_url`` (custom-scheme open URL, including cold
  start), which this module funnels into the waiting callback as well.

Python reaches the Swift `LuvatrixAuthSession` ObjC class through rubicon-objc
on first use; Linux tests pass a fake via ``IOSWebAuthenticationSession(bridge=...)``.
The class implements the browser-session protocol `WorkosSignInCoordinator`
consumes: ``open(url, callback)`` / ``cancel()``.
"""

from __future__ import annotations

import threading
from typing import Callable

from .url_router import UrlRouter, default_router

AuthCallback = Callable[[str | None], None]

DEFAULT_CALLBACK_SCHEME = "ainomic"


class IOSAuthSessionError(RuntimeError):
    """The native web-auth session could not be presented or was misused."""


class IOSWebAuthenticationSession:
    """Browser-session protocol over the Swift ASWebAuthenticationSession bridge."""

    def __init__(
        self,
        *,
        bridge: object | None = None,
        callback_scheme: str = DEFAULT_CALLBACK_SCHEME,
        router: UrlRouter | None = None,
    ) -> None:
        self._bridge = bridge
        self._callback_scheme = callback_scheme.strip().lower() or DEFAULT_CALLBACK_SCHEME
        self._router = router if router is not None else default_router()
        self._callback: AuthCallback | None = None
        self._lock = threading.RLock()
        self._router.register(self._callback_scheme, self._route_open_url)

    @property
    def callback_scheme(self) -> str:
        return self._callback_scheme

    @property
    def active(self) -> bool:
        with self._lock:
            return self._callback is not None

    def open(self, authorization_url: str, callback: AuthCallback) -> None:
        with self._lock:
            if self._callback is not None:
                raise IOSAuthSessionError("an iOS web-authentication session is already active")
            self._callback = callback
        try:
            started = self._bridge_obj().startSession_callbackScheme_(
                authorization_url,
                self._callback_scheme,
            )
        except Exception as exc:
            with self._lock:
                self._callback = None
            raise IOSAuthSessionError(f"the iOS web-authentication session failed to start: {exc}") from exc
        if not started:
            with self._lock:
                self._callback = None
            raise IOSAuthSessionError("the iOS web-authentication session could not be presented")
        _set_active_session(self)

    def deliver_callback(self, callback_url: str) -> bool:
        with self._lock:
            callback = self._callback
            self._callback = None
        if callback is None:
            return False
        _clear_active_session(self)
        callback(callback_url)
        return True

    def complete_from_swift(self, callback_url: str | None) -> None:
        """Entry point for the Swift completion handler."""
        if callback_url is None:
            self._finish_cancelled()
        else:
            self.deliver_callback(callback_url)

    def cancel(self) -> None:
        with self._lock:
            had_callback = self._callback is not None
        if had_callback:
            try:
                self._bridge_obj().cancelSession()
            except Exception:
                pass
        self._finish_cancelled()

    def close(self) -> None:
        """Detach from the URL router when the session object is retired."""
        self._router.unregister(self._callback_scheme)

    def _finish_cancelled(self) -> None:
        with self._lock:
            callback = self._callback
            self._callback = None
        _clear_active_session(self)
        if callback is not None:
            callback(None)

    def _route_open_url(self, url: str) -> bool:
        if not self.active:
            return False
        return self.deliver_callback(url)

    def _bridge_obj(self) -> object:
        if self._bridge is None:
            try:
                from rubicon.objc import ObjCClass

                self._bridge = ObjCClass("LuvatrixAuthSession")
            except Exception as exc:
                raise IOSAuthSessionError(
                    "the native iOS web-authentication bridge is unavailable; run inside "
                    "the Luvatrix iOS scaffold (LuvatrixAuthSession)"
                ) from exc
        return self._bridge


_active_lock = threading.Lock()
_active_session: IOSWebAuthenticationSession | None = None


def _set_active_session(session: IOSWebAuthenticationSession) -> None:
    with _active_lock:
        global _active_session
        _active_session = session


def _clear_active_session(session: IOSWebAuthenticationSession) -> None:
    with _active_lock:
        global _active_session
        if _active_session is session:
            _active_session = None


def complete_auth_session(callback_url: str | None) -> bool:
    """Entry point the Swift completion handler calls into (via PyRunSimpleString)."""
    with _active_lock:
        session = _active_session
    if session is None:
        return False
    session.complete_from_swift(callback_url)
    return True


def make_workos_auth_session(
    *,
    callback_scheme: str = DEFAULT_CALLBACK_SCHEME,
    bridge: object | None = None,
    router: UrlRouter | None = None,
) -> IOSWebAuthenticationSession:
    return IOSWebAuthenticationSession(
        bridge=bridge,
        callback_scheme=callback_scheme,
        router=router,
    )


def build_ios_workos_coordinator(
    *,
    app_dir: str | None = None,
    environ: dict[str, str] | None = None,
    transport: object | None = None,
    invalidate: Callable[[], None] | None = None,
):
    """Assemble a `WorkosSignInCoordinator` wired to Keychain + ASWebAuthenticationSession.

    Imports stay lazy so this module loads on any platform; the Keychain and
    web-auth bridges only resolve when sign-in actually runs on device.
    """
    from luvatrix.auth.workos_sign_in import WorkosSignInCoordinator, load_workos_sign_in_config

    from .keychain import secure_workos_token_store

    config = load_workos_sign_in_config(app_dir=app_dir, environ=environ)
    return WorkosSignInCoordinator(
        config,
        session=make_workos_auth_session(callback_scheme=_scheme_of(config.redirect_uri)),
        token_store=secure_workos_token_store(config.instance_url),
        transport=transport,
        invalidate=invalidate,
    )


def _scheme_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).scheme.lower() or DEFAULT_CALLBACK_SCHEME
