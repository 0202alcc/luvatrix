"""JSON HTTP client over a `Transport`.

Base-url joining, bearer-token auth (a static token or a callable so a token
source with refresh can plug in), JSON helpers, and a multipart encoder for
file uploads. Stdlib only.
"""

from __future__ import annotations

import json
import secrets
from typing import Callable, Mapping

from .transport import HttpRequest, HttpResponse, Transport, UrllibTransport

BearerToken = str | Callable[[], str | None]


class ApiError(RuntimeError):
    """The server answered with an HTTP error status (>= 400)."""

    def __init__(self, status: int, body: bytes, *, url: str) -> None:
        self.status = status
        self.body = body
        self.url = url
        preview = body[:200].decode("utf-8", errors="replace")
        super().__init__(f"HTTP {status} from {url}: {preview}")

    def json(self) -> object | None:
        """The error body parsed as JSON, or None when it is not JSON."""
        try:
            return json.loads(self.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


class HttpClient:
    def __init__(
        self,
        base_url: str,
        transport: Transport | None = None,
        *,
        bearer_token: BearerToken | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")
        self._base_url = base_url.rstrip("/")
        self._transport = transport if transport is not None else UrllibTransport()
        self._bearer_token = bearer_token
        self._headers = dict(headers or {})
        self._timeout = timeout

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def base_url(self) -> str:
        return self._base_url

    def url_for(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self._base_url}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        url = self.url_for(path)
        merged = dict(self._headers)
        token = self._bearer_token() if callable(self._bearer_token) else self._bearer_token
        if token:
            merged["Authorization"] = f"Bearer {token}"
        merged.update(headers or {})
        response = self._transport.send(
            HttpRequest(method=method, url=url, headers=merged, body=body),
            timeout=self._timeout if timeout is None else timeout,
        )
        if response.status >= 400:
            raise ApiError(response.status, response.body, url=url)
        return response

    def get_json(self, path: str, *, headers: Mapping[str, str] | None = None) -> object:
        return _parse_json(self.request("GET", path, headers=headers))

    def post_json(
        self,
        path: str,
        payload: object,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        merged = {"Content-Type": "application/json", **(headers or {})}
        return _parse_json(
            self.request("POST", path, headers=merged, body=json.dumps(payload).encode("utf-8"))
        )

    def post_multipart(
        self,
        path: str,
        *,
        file_field: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        fields: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        body, boundary = encode_multipart(
            fields=fields,
            file_field=file_field,
            filename=filename,
            content=content,
            content_type=content_type,
        )
        merged = {"Content-Type": f"multipart/form-data; boundary={boundary}", **(headers or {})}
        return _parse_json(self.request("POST", path, headers=merged, body=body))


def encode_multipart(
    *,
    file_field: str,
    filename: str,
    content: bytes,
    content_type: str,
    fields: Mapping[str, str] | None = None,
) -> tuple[bytes, str]:
    """Encode one file plus optional text fields as `multipart/form-data`.

    Text fields come first so a streaming server can route on them before the
    file bytes arrive. Returns (body, boundary).
    """
    boundary = f"luvatrix-{secrets.token_hex(16)}"
    parts: list[bytes] = []
    for name, value in (fields or {}).items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{_quote(name)}"\r\n'
            f"\r\n"
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{_quote(file_field)}"; filename="{_quote(filename)}"\r\n'
        f"Content-Type: {content_type}\r\n"
        f"\r\n".encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def _quote(value: str) -> str:
    if any(char in value for char in ('"', "\r", "\n")):
        raise ValueError("multipart field names and filenames cannot contain quotes or newlines")
    return value


def _parse_json(response: HttpResponse) -> object:
    if not response.body:
        return None
    return json.loads(response.body)
