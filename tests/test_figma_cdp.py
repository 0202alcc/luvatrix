"""Tests for the thin Chrome DevTools Protocol client used by `figma capture`."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from luvatrix_ui.figma import cdp


def test_parse_ws_url_finds_the_browser_endpoint() -> None:
    line = "DevTools listening on ws://127.0.0.1:41149/devtools/browser/abc-123"
    assert cdp.parse_ws_url(line) == "ws://127.0.0.1:41149/devtools/browser/abc-123"


def test_parse_ws_url_ignores_other_lines() -> None:
    assert cdp.parse_ws_url("[12345:1] WARNING: some chrome noise") is None
    assert cdp.parse_ws_url("") is None


def test_find_chrome_returns_the_first_existing_candidate() -> None:
    calls: list[Path] = []

    def probe(path: Path) -> bool:
        calls.append(path)
        return path.name == "google-chrome"

    found = cdp.find_chrome(candidates=[Path("/nope"), Path("/usr/local/bin/google-chrome")], exists=probe)
    assert found == Path("/usr/local/bin/google-chrome")
    assert calls == [Path("/nope"), Path("/usr/local/bin/google-chrome")]


def test_find_chrome_returns_none_when_nothing_exists() -> None:
    assert cdp.find_chrome(candidates=[Path("/nope")], exists=lambda _p: False) is None


class _FakeWS:
    """Records sent commands and replays queued responses in order."""

    def __init__(self, responses: list[dict]) -> None:
        self.sent: list[dict] = []
        self.responses = list(responses)
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(__import__("json").loads(raw))

    async def recv(self) -> str:
        import json

        if not self.responses:
            raise AssertionError("fake ws ran out of responses")
        return __import__("json").dumps(self.responses.pop(0))

    async def close(self) -> None:
        self.closed = True


def test_connection_call_matches_replies_by_id() -> None:
    ws = _FakeWS([{"id": 1, "result": {"title": "ok"}}])

    async def run() -> dict:
        conn = cdp.CDPConnection(ws)
        return await conn.call("Page.navigate", {"url": "https://example.test"})

    result = asyncio.run(run())
    assert result == {"title": "ok"}
    sent = ws.sent[0]
    assert sent["method"] == "Page.navigate"
    assert sent["params"] == {"url": "https://example.test"}
    assert sent["id"] == 1


def test_connection_call_routes_by_id_across_sessions() -> None:
    ws = _FakeWS(
        [
            {"method": "Page.frameStartedLoading", "sessionId": "s1"},
            {"id": 7, "result": {"frameId": "f"}},
        ]
    )

    async def run() -> dict:
        conn = cdp.CDPConnection(ws)
        return await conn.call("Page.navigate", {"url": "u"}, session="s2")

    result = asyncio.run(run())
    assert result == {"frameId": "f"}
    assert ws.sent[0]["sessionId"] == "s2"


def test_connection_call_raises_on_protocol_error() -> None:
    ws = _FakeWS([{"id": 1, "error": {"message": "bad method"}}])

    async def run() -> None:
        conn = cdp.CDPConnection(ws)
        await conn.call("Nope.nope")

    with pytest.raises(cdp.CDPError, match="bad method"):
        asyncio.run(run())


def test_page_capture_snapshot_returns_the_snapshot_dict() -> None:
    snapshot = {"strings": [], "documents": []}
    ws = _FakeWS(
        [
            {"id": 1, "result": {}},  # Page.enable
            {"id": 2, "result": {}},  # Page.navigate
            {"id": 3, "result": {"result": {"type": "string", "value": "complete"}}},  # readyState
            {"id": 4, "result": snapshot},  # DOMSnapshot.captureSnapshot
        ]
    )

    async def run() -> dict:
        conn = cdp.CDPConnection(ws)
        page = cdp.CDPPage(conn, "session-1")
        await page.navigate("https://example.test")
        assert await page.ready(timeout=1.0)
        return await page.capture_snapshot(cdp.STYLE_PROPS)

    result = asyncio.run(run())
    assert result == snapshot
    sent_by_method = [m["method"] for m in ws.sent]
    assert sent_by_method == ["Page.enable", "Page.navigate", "Runtime.evaluate", "DOMSnapshot.captureSnapshot"]
    capture = ws.sent[3]
    assert capture["sessionId"] == "session-1"
    assert capture["params"]["computedStyles"] == list(cdp.STYLE_PROPS)


def test_page_ready_times_out() -> None:
    ws = _FakeWS([{"id": 1, "result": {"result": {"type": "string", "value": "loading"}}}])

    async def run() -> bool:
        conn = cdp.CDPConnection(ws)
        page = cdp.CDPPage(conn, "s")
        return await page.ready(timeout=0.05)

    assert asyncio.run(run()) is False


def test_launch_reads_the_ws_url_from_stderr(tmp_path: Path) -> None:
    stderr = io.StringIO("[1] noise\nDevTools listening on ws://127.0.0.1:9/devtools/browser/x\n")

    class _Proc:
        def __init__(self) -> None:
            self.stderr = stderr
            self.terminated = False

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            self.terminated = True

    proc = _Proc()
    argv: list[list[str]] = []

    def fake_popen(args, **kwargs):
        argv.append(list(args))
        return proc

    with patch.object(cdp.subprocess, "Popen", fake_popen):
        chrome = cdp.Chrome.launch(["/opt/chrome"], user_data_dir=tmp_path)

    assert chrome.ws_url == "ws://127.0.0.1:9/devtools/browser/x"
    assert chrome.proc is proc
    assert argv[0][0] == "/opt/chrome"
    assert "--remote-debugging-port=0" in argv[0]
    assert f"--user-data-dir={tmp_path}" in argv[0]
    chrome.close()
    assert proc.terminated