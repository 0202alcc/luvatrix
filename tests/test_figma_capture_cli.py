"""CLI wiring and output-layout tests for `luvatrix figma capture`."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from luvatrix_ui.figma import capture as capture_module
from luvatrix_ui.figma.capture import CaptureResult, parse_viewport, write_capture

from figma_capture_fixtures import SnapshotBuilder


def _result() -> CaptureResult:
    b = SnapshotBuilder(title="Cli")
    body = b.element("BODY")
    b.layout(body, 0, 0, 393, 852, **{"background-color": "rgb(255, 255, 255)"})
    compiled = capture_module.compile_snapshots([("/", b.build())])
    compiled.images["img-abc"] = {"url": "https://cdn.test/x.png", "data": b"png-bytes"}
    compiled.clickables.append({"nodeId": "1:9001", "name": "b", "selector": "button", "page": "/", "x": 1, "y": 2, "width": 3, "height": 4})
    return compiled


def test_parse_viewport() -> None:
    assert parse_viewport("393x852@3") == (393, 852, 3.0)
    assert parse_viewport("390x844") == (390, 844, 3.0)
    assert parse_viewport("1280x800@1.5") == (1280, 800, 1.5)


def test_write_capture_layout_matches_pull(tmp_path: Path) -> None:
    design = write_capture(_result(), tmp_path)

    assert design == tmp_path / "figma_file.json"
    assert json.loads(design.read_text(encoding="utf-8"))["document"]["children"][0]["children"][0]["name"] == "Cli"
    assert (tmp_path / "images" / "img-abc.png").read_bytes() == b"png-bytes"
    clickables = json.loads((tmp_path / "clickables.json").read_text(encoding="utf-8"))
    assert clickables[0]["selector"] == "button"
    report = json.loads((tmp_path / "capture_report.json").read_text(encoding="utf-8"))
    assert report["pages"][0]["path"] == "/"


def test_write_capture_keeps_jpeg_extension(tmp_path: Path) -> None:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(buf, format="JPEG")
    result = _result()
    result.images["img-jpg"] = {"url": "https://cdn.test/x.jpg", "data": buf.getvalue()}

    write_capture(result, tmp_path)

    assert (tmp_path / "images" / "img-jpg.jpg").is_file()


def test_main_cli_capture_passes_options_and_prints_summary(tmp_path: Path) -> None:
    from main import main

    click_map = tmp_path / "clicks.json"
    click_map.write_text(json.dumps({"/ -> button": "/settings"}), encoding="utf-8")
    argv = [
        "luvatrix", "figma", "capture", "https://example.test/app",
        "--out", str(tmp_path / "cap"),
        "--pages", "/settings,/about",
        "--click-map", str(click_map),
        "--viewport", "393x852@3",
        "--wait", "1.5",
        "--selector-ready", "[data-app-ready]",
        "--full-page",
        "--chrome", "/opt/chrome",
    ]

    with patch.object(sys, "argv", argv), patch.object(capture_module, "capture_design", return_value=_result()) as design:
        main()

    out_dir = tmp_path / "cap"
    design.assert_called_once_with(
        "https://example.test/app",
        out_dir,
        pages=["/settings", "/about"],
        click_map_path=click_map,
        viewport="393x852@3",
        wait=1.5,
        selector_ready="[data-app-ready]",
        full_page=True,
        chrome_path="/opt/chrome",
        cookies=[],
        color_scheme=None,
    )
    assert (out_dir / "figma_file.json").is_file()


def test_main_cli_capture_passes_cookies_to_design(tmp_path: Path) -> None:
    from main import main

    argv = [
        "luvatrix", "figma", "capture", "https://example.test/app",
        "--out", str(tmp_path / "cap"),
        "--cookie", "wos-session=abc123",
        "--cookie", "nomic-instance=http%3A%2F%2Flocalhost%3A3000",
    ]

    with patch.object(sys, "argv", argv), patch.object(capture_module, "capture_design", return_value=_result()) as design:
        main()

    design.assert_called_once_with(
        "https://example.test/app",
        tmp_path / "cap",
        pages=[],
        click_map_path=None,
        viewport="393x852@3",
        wait=2.0,
        selector_ready=None,
        full_page=True,
        chrome_path=None,
        cookies=[("wos-session", "abc123"), ("nomic-instance", "http%3A%2F%2Flocalhost%3A3000")],
        color_scheme=None,
    )


def test_main_cli_capture_passes_color_scheme_to_design(tmp_path: Path) -> None:
    from main import main

    argv = [
        "luvatrix", "figma", "capture", "https://example.test/app",
        "--out", str(tmp_path / "cap"),
        "--color-scheme", "dark",
    ]

    with patch.object(sys, "argv", argv), patch.object(capture_module, "capture_design", return_value=_result()) as design:
        main()

    assert design.call_args.kwargs["color_scheme"] == "dark"


def test_parse_cookie_args_rejects_malformed_pair() -> None:
    with pytest.raises(capture_module.CaptureError):
        capture_module._parse_cookie_args(["novalue"])


def test_cdp_page_set_cookies_sends_each_cookie_for_page_url() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any], str | None]] = []

        async def call(self, method: str, params: dict[str, Any] | None = None, *, session: str | None = None) -> Any:
            self.calls.append((method, params or {}, session))
            return {}

    import asyncio

    from luvatrix_ui.figma.cdp import CDPPage

    async def run() -> list[tuple[str, dict[str, Any]]]:
        fake = FakeConnection()
        page = CDPPage(fake, "sid")
        await page.set_cookies(
            [("wos-session", "abc123"), ("nomic-instance", "http%3A%2F%2Flocalhost")],
            url="https://app.test/app",
        )
        return [(method, params) for method, params, _ in fake.calls]

    calls = asyncio.run(run())

    assert [(method, params["name"], params["value"]) for method, params in calls] == [
        ("Network.setCookie", "wos-session", "abc123"),
        ("Network.setCookie", "nomic-instance", "http%3A%2F%2Flocalhost"),
    ]
    for _, params in calls:
        assert params["url"] == "https://app.test/app"


def test_capture_help_does_not_import_browser_modules() -> None:
    import subprocess

    code = (
        "import sys; sys.argv = ['luvatrix', 'figma', 'capture', '--help']; "
        "import main\n"
        "try:\n    main.main()\nexcept SystemExit:\n    pass\n"
        "assert 'websockets' not in sys.modules, 'websockets imported eagerly'\n"
        "assert 'luvatrix_ui.figma.capture' not in sys.modules, 'capture imported eagerly'\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower() or "ok" in proc.stdout