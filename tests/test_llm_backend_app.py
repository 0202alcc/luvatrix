"""Tests for examples/llm_backend — a mini LLM backend app over luvatrix MCP mode.

The app exposes three app-defined MCP tools (llm_ask / llm_result / llm_status)
backed by a pluggable provider: an offline deterministic echo provider and an
OpenAI-compatible chat-completions provider (GLM, OpenRouter, Ollama, ...).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "examples" / "llm_backend"

LLM_ENV_VARS = (
    "LUVATRIX_LLM_PROVIDER",
    "LUVATRIX_LLM_BASE_URL",
    "LUVATRIX_LLM_API_KEY",
    "LUVATRIX_LLM_MODEL",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses look up sys.modules[cls.__module__]
    # while processing decorators.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


providers = _load_module("llm_backend_providers", APP_DIR / "providers.py")
app_main = _load_module("llm_backend_app_main", APP_DIR / "app_main.py")


class EchoProviderTests(unittest.TestCase):
    def test_answer_shape_and_determinism(self) -> None:
        provider = providers.EchoProvider()
        first = provider.ask("What is Valkey?")
        second = provider.ask("What is Valkey?")
        self.assertEqual(first.answer, second.answer)
        self.assertIn("What is Valkey?", first.answer)
        self.assertEqual(first.model, provider.model)
        self.assertIsInstance(first.elapsed_ms, int)
        self.assertGreaterEqual(first.elapsed_ms, 0)

    def test_context_included_when_given(self) -> None:
        provider = providers.EchoProvider()
        answer = provider.ask("Summarize", context="web pod runs Next.js")
        self.assertIn("web pod runs Next.js", answer.answer)

    def test_empty_question_raises(self) -> None:
        provider = providers.EchoProvider()
        with self.assertRaises(ValueError):
            provider.ask("   ")


class _StubChatHandler(BaseHTTPRequestHandler):
    """Canned OpenAI-compatible chat.completions endpoint for tests."""

    payload: dict = {}
    requests: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        payload = type(self).payload
        status = int(payload.get("status", 200))
        data = json.dumps(payload.get("json", {})).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args: object) -> None:
        pass


class OpenAICompatProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        _StubChatHandler.payload = {}
        _StubChatHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _StubChatHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5.0)

    def test_chat_completion_request_and_parse(self) -> None:
        _StubChatHandler.payload = {
            "json": {"choices": [{"message": {"content": "KEDA scales on queue depth."}}]}
        }
        provider = providers.OpenAICompatProvider(
            base_url=self.base_url, api_key="secret", model="glm-4.5-flash"
        )
        answer = provider.ask("What metric drives KEDA?", context="alec tab")
        self.assertEqual(answer.answer, "KEDA scales on queue depth.")
        self.assertEqual(answer.model, "glm-4.5-flash")
        self.assertIsInstance(answer.elapsed_ms, int)

        self.assertEqual(len(_StubChatHandler.requests), 1)
        request = _StubChatHandler.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["authorization"], "Bearer secret")
        self.assertEqual(request["body"]["model"], "glm-4.5-flash")
        contents = [m["content"] for m in request["body"]["messages"]]
        self.assertTrue(any("What metric drives KEDA?" in c for c in contents))
        self.assertTrue(any("alec tab" in c for c in contents))

    def test_http_error_raises_provider_error(self) -> None:
        _StubChatHandler.payload = {"status": 500, "json": {"error": "boom"}}
        provider = providers.OpenAICompatProvider(
            base_url=self.base_url, api_key=None, model="glm-4.5-flash"
        )
        with self.assertRaises(providers.LLMProviderError):
            provider.ask("hi")

    def test_malformed_response_raises_provider_error(self) -> None:
        _StubChatHandler.payload = {"json": {"choices": []}}
        provider = providers.OpenAICompatProvider(
            base_url=self.base_url, api_key=None, model="glm-4.5-flash"
        )
        with self.assertRaises(providers.LLMProviderError):
            provider.ask("hi")


class ResolveProviderTests(unittest.TestCase):
    def test_defaults_to_echo_with_warning(self) -> None:
        provider = providers.resolve_provider({})
        self.assertIsInstance(provider, providers.EchoProvider)
        self.assertTrue(any("echo" in w for w in provider.warnings))

    def test_explicit_echo_has_no_warnings(self) -> None:
        provider = providers.resolve_provider({"LUVATRIX_LLM_PROVIDER": "echo"})
        self.assertIsInstance(provider, providers.EchoProvider)
        self.assertEqual(provider.warnings, ())

    def test_openai_compat_from_base_url(self) -> None:
        provider = providers.resolve_provider(
            {
                "LUVATRIX_LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
                "LUVATRIX_LLM_API_KEY": "key",
                "LUVATRIX_LLM_MODEL": "glm-4.5-flash",
            }
        )
        self.assertIsInstance(provider, providers.OpenAICompatProvider)
        self.assertEqual(provider.model, "glm-4.5-flash")
        self.assertEqual(provider.warnings, ())

    def test_missing_api_key_warns_and_model_defaults(self) -> None:
        provider = providers.resolve_provider(
            {"LUVATRIX_LLM_BASE_URL": "http://127.0.0.1:11434/v1"}
        )
        self.assertIsInstance(provider, providers.OpenAICompatProvider)
        self.assertEqual(provider.model, "glm-4.5-flash")
        self.assertTrue(any("API_KEY" in w for w in provider.warnings))

    def test_explicit_openai_compat_requires_base_url(self) -> None:
        with self.assertRaises(providers.LLMProviderError):
            providers.resolve_provider({"LUVATRIX_LLM_PROVIDER": "openai-compat"})

    def test_unknown_provider_name_raises(self) -> None:
        with self.assertRaises(providers.LLMProviderError):
            providers.resolve_provider({"LUVATRIX_LLM_PROVIDER": "bogus"})

    def test_blank_env_values_count_as_unset(self) -> None:
        provider = providers.resolve_provider(
            {"LUVATRIX_LLM_BASE_URL": "  ", "LUVATRIX_LLM_PROVIDER": "echo"}
        )
        self.assertIsInstance(provider, providers.EchoProvider)


class LLMBackendAppTests(unittest.TestCase):
    def _make_app(self, provider: object | None = None):
        return app_main.LLMBackendApp(provider or providers.EchoProvider())

    def test_tools_listing(self) -> None:
        names = [tool["name"] for tool in self._make_app().mcp_tools()]
        self.assertEqual(names, ["llm_ask", "llm_result", "llm_status"])
        for tool in self._make_app().mcp_tools():
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)

    def test_ask_then_result_completes(self) -> None:
        app = self._make_app()
        app.init(ctx=None)
        try:
            ack = app.mcp_call("llm_ask", {"question": "What is Valkey?"})
            self.assertEqual(ack["status"], "pending")
            self.assertTrue(ack["job_id"])
            deadline = time.monotonic() + 5.0
            while True:
                result = app.mcp_call("llm_result", {"job_id": ack["job_id"]})
                if result["status"] != "pending":
                    break
                if time.monotonic() > deadline:
                    self.fail("job never completed")
                time.sleep(0.01)
            self.assertEqual(result["status"], "done")
            self.assertIn("What is Valkey?", result["answer"])
            self.assertEqual(result["model"], "echo-deterministic")
            self.assertIsInstance(result["elapsed_ms"], int)
        finally:
            app.stop(ctx=None)

    def test_result_unknown_job_reports_error(self) -> None:
        result = self._make_app().mcp_call("llm_result", {"job_id": "nope"})
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown job_id", result["error"])

    def test_ask_empty_question_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._make_app().mcp_call("llm_ask", {"question": "  "})

    def test_unknown_tool_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self._make_app().mcp_call("bogus_tool", {})

    def test_status_reports_provider_without_secrets(self) -> None:
        app = app_main.LLMBackendApp(
            providers.OpenAICompatProvider(
                base_url="http://127.0.0.1:9/v1", api_key="supersecret", model="glm-4.5-flash"
            )
        )
        status = app.mcp_call("llm_status", {})
        self.assertEqual(status["provider"], "openai-compat")
        self.assertEqual(status["model"], "glm-4.5-flash")
        self.assertIn("jobs", status)
        self.assertNotIn("supersecret", json.dumps(status))

    def test_mcp_state_reports_counts(self) -> None:
        state = self._make_app().mcp_state()
        self.assertEqual(state["provider"], "echo")
        self.assertIn("jobs_total", state)

    def test_failed_job_surfaces_provider_error(self) -> None:
        class _BoomProvider:
            name = "boom"
            model = "boom-0"
            warnings: tuple = ()

            def ask(self, question: str, context: str | None = None, timeout_s: float = 60.0):
                raise providers.LLMProviderError("upstream down")

        app = self._make_app(_BoomProvider())
        app.init(ctx=None)
        try:
            ack = app.mcp_call("llm_ask", {"question": "hi"})
            deadline = time.monotonic() + 5.0
            while True:
                result = app.mcp_call("llm_result", {"job_id": ack["job_id"]})
                if result["status"] != "pending":
                    break
                if time.monotonic() > deadline:
                    self.fail("job never settled")
                time.sleep(0.01)
            self.assertEqual(result["status"], "error")
            self.assertIn("upstream down", result["error"])
        finally:
            app.stop(ctx=None)


class ManifestTests(unittest.TestCase):
    def test_manifest_enables_mcp_and_validates_headless(self) -> None:
        from luvatrix.app import check_app_install, load_app_manifest

        manifest = load_app_manifest(APP_DIR)
        self.assertEqual(manifest.app_id, "examples.llm_backend")
        self.assertTrue(manifest.mcp.enabled)
        validation = check_app_install(APP_DIR, render="headless")
        self.assertTrue(validation.ok, validation.missing_modules)


class EndToEndTests(unittest.TestCase):
    def test_llm_tools_over_http(self) -> None:
        from luvatrix_core.core.hdi_thread import HDIThread
        from luvatrix_core.core.mcp_runtime import discovery_file_path, read_discovery_file
        from luvatrix_core.core.unified_runtime import UnifiedRuntime
        from luvatrix_core.core.window_matrix import WindowMatrix

        from test_mcp_app_hooks import _FakeSensorManager, _NoopHDISource, _RecordingTarget
        from test_mcp_runtime import _post_json

        blank_env = {name: "" for name in LLM_ENV_VARS}
        with tempfile.TemporaryDirectory() as td, unittest.mock.patch.dict(os.environ, blank_env):
            app_dir = Path(td)
            for name in ("app.toml", "app_main.py", "providers.py"):
                shutil.copy(APP_DIR / name, app_dir / name)
            runtime = UnifiedRuntime(
                matrix=WindowMatrix(width=2, height=2),
                target=_RecordingTarget(),
                hdi=HDIThread(source=_NoopHDISource()),
                sensor_manager=_FakeSensorManager(),
                capability_decider=lambda _cap: True,
                mcp_enabled=True,
            )
            thread = threading.Thread(
                target=lambda: runtime.run_app(app_dir, max_ticks=None, target_fps=200),
                daemon=True,
            )
            thread.start()
            discovery = discovery_file_path(app_dir)
            deadline = time.monotonic() + 10.0
            while not discovery.exists():
                if time.monotonic() > deadline:
                    self.fail("MCP discovery file was not created")
                time.sleep(0.01)
            info = read_discovery_file(app_dir)

            def call(req_id: int, name: str, arguments: dict | None = None) -> dict:
                status, body = _post_json(
                    info["url"],
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments or {}},
                    },
                    token=info["token"],
                )
                self.assertEqual(status, 200)
                self.assertFalse(body["result"]["isError"], body)
                return json.loads(body["result"]["content"][0]["text"])

            status, body = _post_json(
                info["url"],
                {"jsonrpc": "2.0", "id": 50, "method": "tools/list"},
                token=info["token"],
            )
            self.assertEqual(status, 200)
            names = [tool["name"] for tool in body["result"]["tools"]]
            self.assertIn("llm_ask", names)
            self.assertIn("llm_result", names)
            self.assertIn("llm_status", names)

            ack = call(1, "llm_ask", {"question": "What is Valkey?"})
            self.assertEqual(ack["status"], "pending")
            result_deadline = time.monotonic() + 10.0
            while True:
                result = call(2, "llm_result", {"job_id": ack["job_id"]})
                if result["status"] != "pending":
                    break
                if time.monotonic() > result_deadline:
                    self.fail("llm job never completed over MCP")
                time.sleep(0.02)
            self.assertEqual(result["status"], "done")
            self.assertIn("What is Valkey?", result["answer"])
            self.assertEqual(result["model"], "echo-deterministic")

            status_payload = call(3, "llm_status")
            self.assertEqual(status_payload["provider"], "echo")

            call(4, "app_stop")
            thread.join(timeout=10.0)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
