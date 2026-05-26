from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from luvatrix_core.core.app_runtime import AppRuntime
from luvatrix_core.core.hdi_thread import HDIThread
from luvatrix_core.core.scene_graph import CircleNode, ClearNode, SceneFrame, ShaderRectNode, TextNode
from luvatrix_core.core.sensor_manager import SensorManagerThread
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.platform.web.build import build_web_app
from luvatrix_core.platform.web.command_buffer import OP_CIRCLE, OP_CLEAR, OP_SHADER_RECT, OP_TEXT, encode_scene_frame


ROOT = Path(__file__).resolve().parents[1]
FULL_SUITE = ROOT / "examples" / "full_suite_interactive"


def _runtime() -> AppRuntime:
    return AppRuntime(
        matrix=WindowMatrix(height=1, width=1),
        hdi=HDIThread(source=None),
        sensor_manager=SensorManagerThread(providers={}),
        host_os="web",
    )


def test_manifest_parses_web_config() -> None:
    manifest = _runtime().load_manifest(FULL_SUITE)

    assert "web" in manifest.platform_support
    assert manifest.web.pyodide_packages == []
    assert manifest.web.assets == []
    assert manifest.web.api_base_url == "/api"


def test_build_web_writes_static_runtime(tmp_path: Path) -> None:
    result = build_web_app(FULL_SUITE, tmp_path / "dist")

    assert result.index_path.exists()
    assert (result.out_dir / "runtime" / "luvatrix-web.js").exists()
    assert (result.out_dir / "runtime" / "command-buffer.js").exists()
    assert (result.out_dir / "runtime" / "renderers.js").exists()
    assert (result.out_dir / "py" / "luvatrix" / "app.py").exists()
    assert (result.out_dir / "app" / "app_main.py").exists()
    assert (result.out_dir / "app_manifest.json").exists()
    assert (result.out_dir / "app_files.json").exists()
    payload = json.loads((result.out_dir / "app_manifest.json").read_text(encoding="utf-8"))
    assert payload["web"]["api_base_url"] == "/api"
    assert payload["entrypoint"] == "app_main:create"


def test_command_buffer_encodes_v1_opcodes() -> None:
    frame = SceneFrame(
        revision=1,
        logical_width=320,
        logical_height=240,
        display_width=320,
        display_height=240,
        ts_ns=1,
        nodes=(
            ClearNode((1, 2, 3, 255)),
            ShaderRectNode(0, 0, 320, 240, shader="full_suite_background", uniforms=(1.0, 2.0, 3.0)),
            CircleNode(10, 20, 5, (255, 0, 0, 128)),
            TextNode("hello", 4, 8, font_size_px=12),
        ),
    )

    encoded = encode_scene_frame(frame)
    opcodes = [encoded.headers[0], encoded.headers[4], encoded.headers[8], encoded.headers[12]]

    assert opcodes == [OP_CLEAR, OP_SHADER_RECT, OP_CIRCLE, OP_TEXT]
    assert encoded.strings[0] == "hello"
    assert encoded.width == 320
    assert encoded.height == 240


def test_browser_shim_runs_full_suite_one_frame(tmp_path: Path) -> None:
    dist = build_web_app(FULL_SUITE, tmp_path / "dist").out_dir
    script = f"""
import importlib, sys
sys.path.insert(0, {str(dist / "py")!r})
sys.path.insert(0, {str(dist / "app")!r})
module = importlib.import_module("app_main")
app = module.create()
manifest = {{"display": {{"default_coordinate_frame": "screen_tl"}}}}
app.init_browser(width=320, height=640, input_provider=lambda: {{"mouse_x": 10, "mouse_y": 20, "mouse_in_window": True}}, manifest=manifest)
frame = app.loop_browser(1 / 60)
assert frame["headers"][0] == 1
assert 2 in frame["headers"]
assert 4 in frame["headers"]
assert 5 in frame["headers"]
"""
    completed = subprocess.run([sys.executable, "-c", script], check=False, text=True, capture_output=True)

    assert completed.returncode == 0, completed.stderr


def test_python_shim_command_builder_emits_text() -> None:
    shim_path = ROOT / "luvatrix_core" / "platform" / "web" / "python_shim" / "luvatrix" / "app.py"
    spec = importlib.util.spec_from_file_location("luvatrix_web_shim_for_test", shim_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    builder = module.CommandBufferBuilder(100, 80)
    builder.clear((0, 0, 0, 255))
    builder.text("abc", x=1, y=2)
    encoded = builder.finish()

    assert encoded["headers"][0] == module.OP_CLEAR
    assert encoded["headers"][4] == module.OP_TEXT
    assert encoded["strings"][0] == "abc"


def test_node_runtime_assets_when_node_available() -> None:
    node = shutil_which("node")
    if node is None:
        pytest.skip("node is not installed")
    completed = subprocess.run(
        [node, "--test", str(ROOT / "tests" / "web_runtime" / "command_buffer_test.mjs")],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


def shutil_which(binary: str) -> str | None:
    from shutil import which

    return which(binary)
