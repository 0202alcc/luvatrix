"""Opt-in HTTPS smoke check for embedded runtimes.

The iOS runner de-risks urllib-over-TLS on device (versus NSURLSession) by
running one real GET through `UrllibTransport` inside the app and recording
the outcome. The app passes ``--smoke-net <url>`` (or sets
``LUVATRIX_SMOKE_NET_URL``); the result lands in ``status.json`` — inside the
app container's Documents on iOS — with the HTTP status, byte count, and the
TLS version the host negotiated. Stdlib only, like the rest of this package.
"""

from __future__ import annotations

from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import ssl
import sys
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse

from .transport import DEFAULT_TIMEOUT_SECONDS, HttpRequest, Transport, UrllibTransport

SMOKE_NET_ARG = "--smoke-net"
SMOKE_NET_ENV_VAR = "LUVATRIX_SMOKE_NET_URL"
SMOKE_NET_STATUS_ENV_VAR = "LUVATRIX_SMOKE_NET_STATUS_PATH"

TlsProbe = Callable[[str], "str | None"]


def parse_smoke_net_args(argv: Sequence[str]) -> str | None:
    """The ``--smoke-net <url>`` (or ``--smoke-net=<url>``) value from an argv tail."""
    args = list(argv)
    for index, arg in enumerate(args):
        if arg == SMOKE_NET_ARG:
            if index + 1 >= len(args):
                raise ValueError(f"{SMOKE_NET_ARG} requires a URL")
            return args[index + 1]
        if arg.startswith(f"{SMOKE_NET_ARG}="):
            value = arg.partition("=")[2]
            if not value:
                raise ValueError(f"{SMOKE_NET_ARG} requires a URL")
            return value
    return None


def resolve_smoke_net_url(
    argv: Sequence[str] = (),
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """The smoke URL from argv (winning) or ``LUVATRIX_SMOKE_NET_URL``; None when off."""
    env = os.environ if environ is None else environ
    url = parse_smoke_net_args(argv) or env.get(SMOKE_NET_ENV_VAR, "").strip() or None
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"smoke-net URL must be an http(s) URL: {url!r}")
    return url


def default_status_path(*, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get(SMOKE_NET_STATUS_ENV_VAR, "").strip()
    if override:
        return Path(override)
    if sys.platform == "ios":
        # The app container home; Documents is where the runner's reports live.
        return Path.home() / "Documents" / "status.json"
    return Path.cwd() / "status.json"


def probe_tls_version(
    url: str,
    *,
    ssl_context: ssl.SSLContext | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """The TLS version the URL's host negotiates (e.g. ``TLSv1.3``); None for http."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    host = parsed.hostname
    if not host:
        raise ValueError(f"cannot probe TLS for {url!r}: no host")
    context = ssl_context if ssl_context is not None else ssl.create_default_context()
    connection = http.client.HTTPSConnection(host, parsed.port or 443, context=context, timeout=timeout)
    try:
        connection.connect()
        sock = connection.sock
        return sock.version() if sock is not None else None
    finally:
        connection.close()


def run_smoke_net(
    url: str,
    *,
    transport: Transport | None = None,
    tls_probe: TlsProbe | None = None,
    status_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run one HTTPS GET and write the outcome to status.json; returns the payload."""
    http_transport = transport if transport is not None else UrllibTransport()
    probe = tls_probe if tls_probe is not None else probe_tls_version
    payload: dict[str, object] = {
        "url": url,
        "ok": False,
        "status": None,
        "bytes": None,
        "tls_version": None,
        "error": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        response = http_transport.send(HttpRequest(method="GET", url=url), timeout=timeout)
        payload["status"] = response.status
        payload["bytes"] = len(response.body)
        payload["ok"] = 200 <= response.status < 400
    except Exception as exc:  # noqa: BLE001 — the smoke records, never raises
        payload["error"] = f"{type(exc).__name__}: {exc}"
    if urlparse(url).scheme == "https" and payload["error"] is None:
        try:
            payload["tls_version"] = probe(url)
        except Exception as exc:  # noqa: BLE001
            payload["error"] = f"tls probe failed: {type(exc).__name__}: {exc}"
    path = status_path if status_path is not None else default_status_path(environ=environ)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        # The log line the app prints still carries the payload to the runner.
        print(f"[net_smoke] could not write {path}: {exc}", file=sys.stderr, flush=True)
    return payload
