"""HTTP transport boundary for Luvatrix networking.

Stdlib only: this module must run inside embedded CPython on iOS, where no
vendored wheels are available. `Transport` is a protocol so an NSURLSession
bridge can replace `UrllibTransport` on device without callers changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ssl
from typing import Iterator, Mapping, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_TIMEOUT_SECONDS = 30.0
STREAM_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class TransportError(RuntimeError):
    """The request never received an HTTP response (DNS, TLS, timeout, reset)."""


class HttpStream(Protocol):
    """A response whose body arrives incrementally, e.g. for SSE."""

    status: int
    headers: Mapping[str, str]

    def __iter__(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...

    def __enter__(self) -> "HttpStream": ...

    def __exit__(self, *args: object) -> None: ...


@runtime_checkable
class Transport(Protocol):
    """Synchronous HTTP transport.

    `send` buffers the whole response; `stream` exposes it incrementally.
    Both map onto NSURLSession data tasks (completion-handler and
    delegate-driven respectively), so a native bridge can implement the same
    two methods.
    """

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse: ...

    def stream(self, request: HttpRequest, *, timeout: float | None = None) -> HttpStream: ...


class _UrllibStream:
    def __init__(self, response) -> None:
        self._response = response
        self.status: int = response.status
        self.headers: Mapping[str, str] = dict(response.headers.items())

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self._response.read(STREAM_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk

    def close(self) -> None:
        self._response.close()

    def __enter__(self) -> "_UrllibStream":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class UrllibTransport:
    """`Transport` over `urllib.request` + `ssl`.

    HTTP error statuses come back as ordinary `HttpResponse` values (callers
    decide which statuses are exceptional); only transport-level failures
    raise `TransportError`. urllib follows redirects, matching NSURLSession's
    default.
    """

    def __init__(
        self,
        *,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        self._default_timeout = default_timeout
        self._ssl_context = ssl_context

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse:
        with self._open(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )

    def stream(self, request: HttpRequest, *, timeout: float | None = None) -> HttpStream:
        return _UrllibStream(self._open(request, timeout=timeout))

    def _open(self, request: HttpRequest, *, timeout: float | None):
        effective_timeout = self._default_timeout if timeout is None else timeout
        urllib_request = Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            return urlopen(urllib_request, timeout=effective_timeout, context=self._ssl_context)
        except HTTPError as exc:
            # An HTTP response arrived; surface it like any other status.
            return exc
        except URLError as exc:
            raise TransportError(f"request to {request.url} failed: {exc.reason}") from exc
        except OSError as exc:
            raise TransportError(f"request to {request.url} failed: {exc}") from exc
