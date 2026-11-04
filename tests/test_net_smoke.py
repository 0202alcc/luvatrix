from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import pytest

from luvatrix.net import HttpRequest, HttpResponse, TransportError
from luvatrix.net.smoke import (
    SMOKE_NET_ENV_VAR,
    SMOKE_NET_STATUS_ENV_VAR,
    default_status_path,
    parse_smoke_net_args,
    probe_tls_version,
    resolve_smoke_net_url,
    run_smoke_net,
)


class FakeTransport:
    def __init__(self, response: HttpResponse | Exception) -> None:
        self._response = response
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse:
        self.requests.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class ParseSmokeNetArgsTests(unittest.TestCase):
    def test_flag_with_separate_value(self) -> None:
        self.assertEqual(
            parse_smoke_net_args(["--smoke-net", "https://app.nomic.ai/api/v0/openapi.json"]),
            "https://app.nomic.ai/api/v0/openapi.json",
        )

    def test_flag_with_equals_value(self) -> None:
        self.assertEqual(
            parse_smoke_net_args(["--smoke-net=https://app.nomic.ai/api/v0/openapi.json"]),
            "https://app.nomic.ai/api/v0/openapi.json",
        )

    def test_absent_flag_returns_none(self) -> None:
        self.assertIsNone(parse_smoke_net_args([]))
        self.assertIsNone(parse_smoke_net_args(["--ticks", "1"]))

    def test_flag_without_value_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_smoke_net_args(["--smoke-net"])
        with pytest.raises(ValueError):
            parse_smoke_net_args(["--smoke-net="])


class ResolveSmokeNetUrlTests(unittest.TestCase):
    def test_env_var_used_when_no_argv(self) -> None:
        self.assertEqual(
            resolve_smoke_net_url([], {SMOKE_NET_ENV_VAR: "https://app.nomic.ai/"}),
            "https://app.nomic.ai/",
        )

    def test_argv_wins_over_env(self) -> None:
        self.assertEqual(
            resolve_smoke_net_url(
                ["--smoke-net", "https://argv.example/x"],
                {SMOKE_NET_ENV_VAR: "https://env.example/x"},
            ),
            "https://argv.example/x",
        )

    def test_disabled_without_flag_or_env(self) -> None:
        self.assertIsNone(resolve_smoke_net_url([], {}))

    def test_non_http_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            resolve_smoke_net_url(["--smoke-net", "ftp://example.com"], {})
        with pytest.raises(ValueError):
            resolve_smoke_net_url([], {SMOKE_NET_ENV_VAR: "not a url"})


class DefaultStatusPathTests(unittest.TestCase):
    def test_env_override_wins(self) -> None:
        path = default_status_path(environ={SMOKE_NET_STATUS_ENV_VAR: "/tmp/smoke/status.json"})
        self.assertEqual(path, Path("/tmp/smoke/status.json"))

    def test_fallback_is_a_status_json(self) -> None:
        self.assertEqual(default_status_path(environ={}).name, "status.json")


class RunSmokeNetTests(unittest.TestCase):
    def _run(self, transport_response, *, url="https://app.nomic.ai/api/v0/openapi.json", probe="TLSv1.3", status_path=None):
        transport = FakeTransport(transport_response)
        with tempfile.TemporaryDirectory() as td:
            path = status_path or Path(td) / "status.json"
            payload = run_smoke_net(
                url,
                transport=transport,
                tls_probe=lambda _url: probe,
                status_path=path,
            )
            written = json.loads(path.read_text(encoding="utf-8"))
        return payload, written, transport

    def test_success_records_status_bytes_and_tls_version(self) -> None:
        body = b'{"openapi": "3.0"}'
        payload, written, transport = self._run(HttpResponse(status=200, headers={}, body=body))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["bytes"], len(body))
        self.assertEqual(payload["tls_version"], "TLSv1.3")
        self.assertIsNone(payload["error"])
        self.assertEqual(written, payload)
        self.assertEqual(transport.requests[0].method, "GET")

    def test_http_error_status_is_not_ok(self) -> None:
        payload, _written, _transport = self._run(HttpResponse(status=503, headers={}, body=b"nope"))

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], 503)
        self.assertEqual(payload["bytes"], 4)

    def test_transport_failure_records_error(self) -> None:
        payload, _written, _transport = self._run(TransportError("connection reset"))

        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["status"])
        self.assertIn("connection reset", payload["error"])

    def test_tls_probe_failure_keeps_get_result(self) -> None:
        transport = FakeTransport(HttpResponse(status=200, headers={}, body=b"{}"))
        with tempfile.TemporaryDirectory() as td:
            payload = run_smoke_net(
                "https://app.nomic.ai/",
                transport=transport,
                tls_probe=_raise_tls_probe,
                status_path=Path(td) / "status.json",
            )

        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["tls_version"])
        self.assertIn("tls", payload["error"].lower())

    def test_tls_probe_skipped_for_plain_http(self) -> None:
        called: list[str] = []

        def probe(url: str) -> str:
            called.append(url)
            return "TLSv1.3"

        with tempfile.TemporaryDirectory() as td:
            payload = run_smoke_net(
                "http://localhost:3000/api/v0/openapi.json",
                transport=FakeTransport(HttpResponse(status=200, headers={}, body=b"{}")),
                tls_probe=probe,
                status_path=Path(td) / "status.json",
            )

        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["tls_version"])
        self.assertEqual(called, [])

    def test_status_path_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "status.json"
            payload = run_smoke_net(
                "https://app.nomic.ai/",
                transport=FakeTransport(HttpResponse(status=200, headers={}, body=b"{}")),
                tls_probe=lambda _url: "TLSv1.3",
                environ={SMOKE_NET_STATUS_ENV_VAR: str(path)},
            )
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)


def _raise_tls_probe(url: str) -> str:
    raise OSError("handshake failed")


class ProbeTlsVersionTests(unittest.TestCase):
    def test_plain_http_has_no_tls(self) -> None:
        self.assertIsNone(probe_tls_version("http://localhost:3000/"))


class NetSmokeExampleTests(unittest.TestCase):
    APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "net_smoke"

    def test_manifest_declares_ios_support(self) -> None:
        import tomllib

        manifest = tomllib.loads((self.APP_DIR / "app.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["platform_support"], ["ios"])
        self.assertEqual(manifest["entrypoint"], "app_main:create")

    def test_validates_for_ios_simulator(self) -> None:
        from luvatrix.app import validate_app_install

        self.assertTrue(validate_app_install(self.APP_DIR, render="ios-simulator").ok)

    def test_renders_idle_frame_without_smoke_config(self) -> None:
        from luvatrix_core.core.app_runtime import AppRuntime
        from luvatrix_core.core.hdi_thread import HDIEvent, HDIThread
        from luvatrix_core.core.sensor_manager import SensorManagerThread
        from luvatrix_core.core.window_matrix import WindowMatrix

        class _NoopHDISource:
            def poll(self, window_active: bool, ts_ns: int) -> list[HDIEvent]:
                return []

        matrix = WindowMatrix(32, 32)
        runtime = AppRuntime(
            matrix=matrix,
            hdi=HDIThread(source=_NoopHDISource()),
            sensor_manager=SensorManagerThread(providers={}),
            host_os="ios",
        )

        runtime.run(self.APP_DIR, max_ticks=1, target_fps=1000)

        self.assertGreater(int(matrix.read_snapshot().sum()), 0)


if __name__ == "__main__":
    unittest.main()
