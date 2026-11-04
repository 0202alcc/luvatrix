"""Route custom-scheme open-URL events from the Swift scene delegate into Python.

The Swift `SceneDelegate` forwards `scene(_:openURLContexts:)` and the
cold-start `connectionOptions.urlContexts` to ``handle_open_url`` through the
established PyRunSimpleString bridge. Handlers register per URL scheme; a URL
that arrives before its handler registers (a cold start races app startup) is
buffered and drained when the matching scheme registers.

A handler returns True when it consumed the URL. A declined URL is dropped,
not buffered: the handler saw it and said no.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable
from urllib.parse import urlparse

OpenUrlHandler = Callable[[str], bool]

DEFAULT_MAX_BUFFERED = 8


class UrlRouter:
    def __init__(self, *, max_buffered: int = DEFAULT_MAX_BUFFERED) -> None:
        if max_buffered < 1:
            raise ValueError("max_buffered must be positive")
        self._max_buffered = max_buffered
        self._handlers: dict[str, OpenUrlHandler] = {}
        self._buffered: list[str] = []
        self._lock = threading.RLock()

    def register(self, scheme: str, handler: OpenUrlHandler) -> None:
        scheme = _normalize_scheme(scheme)
        with self._lock:
            self._handlers[scheme] = handler
            pending = list(self._buffered)
        for url in pending:
            if _scheme_of(url) != scheme:
                continue
            if self._deliver(scheme, url):
                with self._lock:
                    if url in self._buffered:
                        self._buffered.remove(url)

    def unregister(self, scheme: str) -> None:
        with self._lock:
            self._handlers.pop(_normalize_scheme(scheme), None)

    def handle_open_url(self, url: str) -> bool:
        url = str(url)
        scheme = _scheme_of(url)
        with self._lock:
            handler = self._handlers.get(scheme) if scheme else None
        if handler is not None and self._deliver(scheme, url):
            return True
        if handler is None:
            with self._lock:
                self._buffered.append(url)
                del self._buffered[: max(0, len(self._buffered) - self._max_buffered)]
        return False

    def buffered(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._buffered)

    def _deliver(self, scheme: str, url: str) -> bool:
        with self._lock:
            handler = self._handlers.get(scheme)
        if handler is None:
            return False
        try:
            return bool(handler(url))
        except Exception as exc:  # noqa: BLE001 — a broken handler must not kill the router
            print(f"[ios-url] handler for {scheme}:// failed: {exc}", file=sys.stderr, flush=True)
            return False


def _normalize_scheme(scheme: str) -> str:
    scheme = scheme.strip().lower()
    if not scheme:
        raise ValueError("url scheme is required")
    return scheme


def _scheme_of(url: str) -> str:
    return urlparse(url).scheme.lower()


_default_lock = threading.Lock()
_default_router = UrlRouter()


def default_router() -> UrlRouter:
    with _default_lock:
        return _default_router


def register_scheme(scheme: str, handler: OpenUrlHandler) -> None:
    default_router().register(scheme, handler)


def unregister_scheme(scheme: str) -> None:
    default_router().unregister(scheme)


def handle_open_url(url: str) -> bool:
    """Entry point the Swift scene delegate calls for each open-URL event."""
    return default_router().handle_open_url(url)
