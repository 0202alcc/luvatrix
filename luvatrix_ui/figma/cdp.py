"""Thin Chrome DevTools Protocol client for DOM capture.

This module owns all browser interaction behind small functions so tests can
inject fakes; `capture.compile_snapshot` stays a pure snapshot-to-Figma
compiler. All browser imports (subprocess, websockets, asyncio) are lazy so
public API and CLI import paths never load them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
import re
import shutil
from typing import Any

CHROME_CANDIDATES = (
    "/usr/local/bin/google-chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

STYLE_PROPS: tuple[str, ...] = (
    "display",
    "position",
    "visibility",
    "background-color",
    "background-image",
    "color",
    "font-family",
    "font-size",
    "font-weight",
    "font-style",
    "line-height",
    "letter-spacing",
    "text-transform",
    "text-decoration",
    "text-align",
    "overflow-x",
    "overflow-y",
    "mix-blend-mode",
    "backdrop-filter",
    "filter",
    "z-index",
    "opacity",
    "border-radius",
    "border-top-left-radius",
    "border-top-right-radius",
    "border-bottom-right-radius",
    "border-bottom-left-radius",
    "box-shadow",
    "width",
    "height",
    "border-width",
    "border-style",
    "border-color",
    "border-top-width",
    "border-top-style",
    "border-top-color",
    "border-right-width",
    "border-right-style",
    "border-right-color",
    "border-bottom-width",
    "border-bottom-style",
    "border-bottom-color",
    "border-left-width",
    "border-left-style",
    "border-left-color",
    "transform",
    "transform-origin",
)

_WS_RE = re.compile(r"ws://\S+/devtools/browser/\S+")
_DEFAULT_TIMEOUT = 30.0


class CDPError(RuntimeError):
    pass


def parse_ws_url(line: str) -> str | None:
    """Extract the browser WebSocket URL from a Chrome stderr line."""
    match = _WS_RE.search(line)
    return match.group(0).rstrip(".,;") if match else None


def find_chrome(
    candidates: Iterable[str | Path] = CHROME_CANDIDATES,
    *,
    exists: Any = None,
) -> Path | None:
    """First chrome-ish binary among `candidates`; `exists` is injectable for tests."""
    probe = exists or (lambda path: path.is_file() or shutil.which(path.name) is not None)
    for candidate in candidates:
        path = Path(candidate) if str(candidate).startswith("/") else Path(shutil.which(str(candidate)) or str(candidate))
        if probe(path):
            return path
    return None


class Chrome:
    """A headless Chrome process with its DevTools WebSocket URL."""

    def __init__(self, proc: Any, ws_url: str) -> None:
        self.proc = proc
        self.ws_url = ws_url

    @classmethod
    def launch(
        cls,
        chrome_path: str | Path | None,
        *,
        user_data_dir: Path | None = None,
        stderr_timeout: float = _DEFAULT_TIMEOUT,
    ) -> "Chrome":
        import time
        import subprocess

        binary = chrome_path or find_chrome()
        if binary is None:
            raise CDPError("no Chrome binary found; install google-chrome or pass --chrome")
        import tempfile

        profile = Path(tempfile.mkdtemp(prefix="luvatrix-capture-")) if user_data_dir is None else user_data_dir
        args = [
            str(binary),
            "--headless=new",
            "--remote-debugging-port=0",
            "--no-sandbox",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            f"--user-data-dir={profile}",
            "about:blank",
        ]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + stderr_timeout
        assert proc.stderr is not None
        while time.monotonic() < deadline:
            line = proc.stderr.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            url = parse_ws_url(line)
            if url:
                return cls(proc, url)
        proc.terminate()
        raise CDPError(f"Chrome did not report a DevTools endpoint ({binary})")

    def close(self) -> None:
        try:
            self.proc.terminate()
        except OSError:
            pass


class CDPConnection:
    """JSON-RPC over the browser WebSocket, routed by id across flat sessions."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._next_id = 0

    @classmethod
    async def connect(cls, ws_url: str) -> "CDPConnection":
        import websockets

        ws = await websockets.connect(ws_url, max_size=512 * 1024 * 1024)
        return cls(ws)

    async def call(self, method: str, params: dict[str, Any] | None = None, *, session: str | None = None) -> Any:
        import json

        self._next_id += 1
        request_id = self._next_id
        message: dict[str, Any] = {"id": request_id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        await self._ws.send(json.dumps(message))
        while True:
            reply = json.loads(await self._ws.recv())
            if reply.get("id") != request_id:
                continue
            if "error" in reply:
                raise CDPError(f"{method}: {reply['error'].get('message', reply['error'])}")
            return reply.get("result")

    async def close(self) -> None:
        await self._ws.close()


class CDPPage:
    """One browser tab driven over a CDP connection."""

    def __init__(self, conn: CDPConnection, session_id: str) -> None:
        self.conn = conn
        self.session_id = session_id

    @classmethod
    async def attach(cls, conn: CDPConnection) -> "CDPPage":
        targets = await conn.call("Target.getTargets")
        page_id = next((t["targetId"] for t in targets.get("targetInfos", ()) if t.get("type") == "page"), None)
        if page_id is None:
            raise CDPError("no page target to attach to")
        result = await conn.call("Target.attachToTarget", {"targetId": page_id, "flatten": True})
        return cls(conn, str(result["sessionId"]))

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return await self.conn.call(method, params, session=self.session_id)

    async def navigate(self, url: str) -> None:
        await self.call("Page.enable")
        await self.call("Page.navigate", {"url": url})

    async def evaluate(self, expression: str) -> Any:
        result = await self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return (result or {}).get("result", {}).get("value")

    async def set_viewport(self, width: int, height: int, scale: float = 3.0) -> None:
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": int(width), "height": int(height), "deviceScaleFactor": float(scale), "mobile": True},
        )

    async def ready(self, timeout: float = 10.0, *, extra_delay: float = 0.0) -> bool:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = await self.evaluate("document.readyState")
            if state in {"complete", "interactive"}:
                if extra_delay > 0:
                    await _sleep(extra_delay)
                    probe = await self.evaluate("document.readyState")
                    if probe not in {"complete", "interactive"}:
                        deadline = time.monotonic() + timeout
                        continue
                return True
            await _sleep(0.1)
        return False

    async def wait_for_selector(self, selector: str, timeout: float = 10.0) -> bool:
        import time

        deadline = time.monotonic() + timeout
        expression = f"document.querySelector({selector!r}) !== null"
        while time.monotonic() < deadline:
            if await self.evaluate(expression):
                return True
            await _sleep(0.1)
        return False

    async def capture_snapshot(self, style_props: Sequence[str] = STYLE_PROPS) -> dict[str, Any]:
        return await self.call(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles": list(style_props),
                "includePaintOrder": True,
                "includeDOMRects": True,
                "includeBlendedBackgroundColors": True,
            },
        )

    async def screenshot(self, clip: dict[str, float] | None = None, *, scale: float = 1.0) -> bytes:
        import base64

        params: dict[str, Any] = {"format": "png"}
        if clip:
            params["clip"] = dict(clip, scale=scale)
        result = await self.call("Page.captureScreenshot", params)
        return base64.b64decode(result["data"])


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)