from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

import pytest

from luvatrix.auth import (
    InMemoryWorkosTokenStore,
    WorkosAuthError,
    WorkosSessionExpiredError,
    WorkosToken,
)
from luvatrix.auth.workos_sign_in import (
    WorkosSignInConfig,
    WorkosSignInCoordinator,
    WorkosSignInState,
    load_workos_sign_in_config,
)
from luvatrix.net import HttpRequest, HttpResponse, TransportError

AUTHKIT = "https://login.nomic.ai"
INSTANCE = "https://app.nomic.ai"


def _b64url(payload: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).rstrip(b"=").decode("ascii")


def _id_token(claims: dict[str, object]) -> str:
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(claims)}.signature"


def _token_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "token_type": "Bearer",
        "id_token": _id_token({"email": "ada@example.com", "name": "Ada Lovelace", "nonce": "unused"}),
    }
    payload.update(overrides)
    return payload


def _queue_exchange(transport: "FakeTransport", coordinator: "WorkosSignInCoordinator") -> None:
    """Queue a token response whose ID token carries the flow's nonce."""
    transport.queue(
        200,
        _token_payload(
            id_token=_id_token(
                {"email": "ada@example.com", "name": "Ada Lovelace", "nonce": coordinator.pending_nonce}
            )
        ),
    )


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self._queue: list[HttpResponse | Exception] = []

    def queue(self, status: int, payload: object) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self._queue.append(HttpResponse(status=status, headers={}, body=body))

    def queue_error(self, error: Exception) -> None:
        self._queue.append(error)

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse:
        self.requests.append(request)
        assert self._queue, "FakeTransport received an unqueued request"
        queued = self._queue.pop(0)
        if isinstance(queued, Exception):
            raise queued
        return queued


class FakeAuthSession:
    """In-memory browser session; tests deliver callbacks by hand."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.cancel_calls = 0
        self._callback = None

    def open(self, authorization_url: str, callback) -> None:
        self.opened.append(authorization_url)
        self._callback = callback

    def deliver(self, callback_url: str | None) -> None:
        callback, self._callback = self._callback, None
        assert callback is not None, "no sign-in is waiting for a callback"
        callback(callback_url)

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.deliver(None)


def _config(**overrides: object) -> WorkosSignInConfig:
    values: dict[str, object] = {
        "instance_url": INSTANCE,
        "authkit_domain": AUTHKIT,
        "client_id": "client_01JTEST",
    }
    values.update(overrides)
    return WorkosSignInConfig(**values)  # type: ignore[arg-type]


def _coordinator(
    transport: FakeTransport | None = None,
    *,
    store: InMemoryWorkosTokenStore | None = None,
    session: FakeAuthSession | None = None,
) -> tuple[WorkosSignInCoordinator, FakeTransport, FakeAuthSession, InMemoryWorkosTokenStore]:
    fake_transport = transport if transport is not None else FakeTransport()
    fake_session = session if session is not None else FakeAuthSession()
    token_store = store if store is not None else InMemoryWorkosTokenStore()
    coordinator = WorkosSignInCoordinator(
        _config(),
        session=fake_session,
        token_store=token_store,
        transport=fake_transport,
        clock=lambda: 100.0,
    )
    return coordinator, fake_transport, fake_session, token_store


def _stored_token(store: InMemoryWorkosTokenStore, **overrides: object) -> WorkosToken:
    values: dict[str, object] = {
        "access_token": "old-access",
        "token_type": "Bearer",
        "expires_at": 50.0,
        "refresh_token": "refresh-1",
    }
    values.update(overrides)
    token = WorkosToken(**values)  # type: ignore[arg-type]
    store.save(token)
    return token


def _begin(coordinator: WorkosSignInCoordinator, session: FakeAuthSession) -> str:
    coordinator.begin_sign_in()
    assert session.opened, "begin_sign_in did not open the browser session"
    query = parse_qs(urlparse(session.opened[-1]).query)
    return query["state"][0]


def _callback_url(state: str, **params: str) -> str:
    query = "&".join([f"state={state}", *[f"{key}={value}" for key, value in params.items()]])
    return f"ainomic://auth/callback?{query}"


class SignInConfigTests(unittest.TestCase):
    def test_default_redirect_uri_is_the_ainomic_callback(self) -> None:
        self.assertEqual(_config().redirect_uri, "ainomic://auth/callback")

    def test_loads_from_app_toml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "app.toml").write_text(
                "\n".join(
                    [
                        'app_id = "app.test"',
                        "[auth.workos]",
                        f'instance_url = "{INSTANCE}"',
                        f'authkit_domain = "{AUTHKIT}"',
                        'client_id = "client_01JTOML"',
                    ]
                ),
                encoding="utf-8",
            )
            config = load_workos_sign_in_config(app_dir=td, environ={})

        self.assertEqual(config.instance_url, INSTANCE)
        self.assertEqual(config.authkit_domain, AUTHKIT)
        self.assertEqual(config.client_id, "client_01JTOML")

    def test_environment_overrides_app_toml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "app.toml").write_text(
                "\n".join(
                    [
                        "[auth.workos]",
                        'instance_url = "https://ignored.example"',
                        f'authkit_domain = "{AUTHKIT}"',
                        'client_id = "client_01JTOML"',
                    ]
                ),
                encoding="utf-8",
            )
            config = load_workos_sign_in_config(
                app_dir=td,
                environ={"NOMIC_INSTANCE_URL": "https://app.eu.nomic.ai/"},
            )

        self.assertEqual(config.instance_url, "https://app.eu.nomic.ai")
        self.assertEqual(config.client_id, "client_01JTOML")

    def test_loads_entirely_from_environment(self) -> None:
        config = load_workos_sign_in_config(
            environ={
                "NOMIC_INSTANCE_URL": INSTANCE,
                "WORKOS_AUTHKIT_DOMAIN": AUTHKIT,
                "NOMIC_IOS_CLIENT_ID": "client_01JENV",
            }
        )
        self.assertEqual(config.client_id, "client_01JENV")

    def test_missing_keys_are_named(self) -> None:
        with pytest.raises(WorkosAuthError, match="client_id"):
            load_workos_sign_in_config(
                environ={"NOMIC_INSTANCE_URL": INSTANCE, "WORKOS_AUTHKIT_DOMAIN": AUTHKIT}
            )

    def test_instance_url_must_be_http(self) -> None:
        with pytest.raises(ValueError):
            _config(instance_url="ftp://example.com")

    def test_instance_url_trailing_slash_normalized(self) -> None:
        self.assertEqual(_config(instance_url=f"{INSTANCE}/").instance_url, INSTANCE)


class RestoreTests(unittest.TestCase):
    def test_restore_without_stored_token_stays_signed_out(self) -> None:
        coordinator, transport, _session, _store = _coordinator()

        self.assertIsNone(coordinator.restore())
        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_OUT)
        self.assertEqual(transport.requests, [])

    def test_restore_valid_token_signs_in_silently(self) -> None:
        coordinator, transport, _session, store = _coordinator()
        _stored_token(store, expires_at=10_000.0)

        token = coordinator.restore()

        self.assertIsNotNone(token)
        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_IN)
        self.assertEqual(coordinator.access_token(), "old-access")
        self.assertEqual(transport.requests, [])

    def test_restore_expired_token_refreshes_and_rotates(self) -> None:
        coordinator, transport, _session, store = _coordinator()
        _stored_token(store)
        transport.queue(200, {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 60})

        token = coordinator.restore()

        self.assertIsNotNone(token)
        self.assertEqual(token.access_token, "access-2")
        self.assertEqual(store.load().refresh_token, "refresh-2")
        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_IN)

    def test_restore_spent_grant_clears_store_and_signs_out(self) -> None:
        coordinator, transport, _session, store = _coordinator()
        _stored_token(store)
        transport.queue(400, {"error": "invalid_grant"})

        self.assertIsNone(coordinator.restore())

        self.assertIsNone(store.load())
        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_OUT)

    def test_restore_transient_failure_keeps_store(self) -> None:
        coordinator, transport, _session, store = _coordinator()
        _stored_token(store)
        transport.queue_error(TransportError("connection reset"))

        self.assertIsNone(coordinator.restore())

        self.assertIsNotNone(store.load())
        self.assertIs(coordinator.state, WorkosSignInState.FAILED)


class PkceFlowTests(unittest.TestCase):
    def test_full_pkce_round_trip(self) -> None:
        coordinator, transport, session, store = _coordinator()

        state = _begin(coordinator, session)
        self.assertIs(coordinator.state, WorkosSignInState.WAITING)
        _queue_exchange(transport, coordinator)
        session.deliver(_callback_url(state, code="code-1"))

        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_IN)
        self.assertEqual(coordinator.identity.email, "ada@example.com")
        self.assertEqual(coordinator.access_token(), "access-1")
        self.assertIsNotNone(store.load())

        form = parse_qs((transport.requests[0].body or b"").decode("utf-8"))
        self.assertEqual(form["grant_type"], ["authorization_code"])
        self.assertEqual(form["code"], ["code-1"])
        self.assertEqual(form["redirect_uri"], ["ainomic://auth/callback"])

    def test_authorize_url_uses_ainomic_redirect(self) -> None:
        coordinator, _transport, session, _store = _coordinator()
        _begin(coordinator, session)

        query = parse_qs(urlparse(session.opened[-1]).query)
        self.assertEqual(query["redirect_uri"], ["ainomic://auth/callback"])
        self.assertEqual(query["code_challenge_method"], ["S256"])

    def test_begin_while_waiting_raises(self) -> None:
        coordinator, _transport, session, _store = _coordinator()
        _begin(coordinator, session)

        with pytest.raises(WorkosAuthError):
            coordinator.begin_sign_in()

    def test_user_cancel_moves_to_cancelled(self) -> None:
        coordinator, transport, session, _store = _coordinator()
        _begin(coordinator, session)

        coordinator.cancel()

        self.assertIs(coordinator.state, WorkosSignInState.CANCELLED)
        self.assertEqual(transport.requests, [])

    def test_state_mismatch_is_rejected(self) -> None:
        coordinator, transport, session, store = _coordinator()
        _begin(coordinator, session)

        session.deliver(_callback_url("attacker-state", code="code-1"))

        self.assertIs(coordinator.state, WorkosSignInState.FAILED)
        self.assertIn("state", str(coordinator.error))
        self.assertIsNone(store.load())
        self.assertEqual(transport.requests, [])

    def test_callback_for_wrong_redirect_uri_is_rejected(self) -> None:
        coordinator, transport, session, _store = _coordinator()
        state = _begin(coordinator, session)

        session.deliver(f"ainomic://other/path?state={state}&code=code-1")

        self.assertIs(coordinator.state, WorkosSignInState.FAILED)
        self.assertEqual(transport.requests, [])

    def test_provider_access_denied_is_a_cancel(self) -> None:
        coordinator, _transport, session, _store = _coordinator()
        state = _begin(coordinator, session)

        session.deliver(_callback_url(state, error="access_denied"))

        self.assertIs(coordinator.state, WorkosSignInState.CANCELLED)

    def test_callback_without_code_fails(self) -> None:
        coordinator, _transport, session, _store = _coordinator()
        state = _begin(coordinator, session)

        session.deliver(_callback_url(state))

        self.assertIs(coordinator.state, WorkosSignInState.FAILED)

    def test_callback_without_active_request_fails(self) -> None:
        coordinator, _transport, _session, _store = _coordinator()

        coordinator.handle_callback(_callback_url("state", code="code-1"))

        self.assertIs(coordinator.state, WorkosSignInState.FAILED)


class ExpiredSessionRecoveryTests(unittest.TestCase):
    def test_access_token_clears_and_reprompts_on_spent_grant(self) -> None:
        coordinator, transport, session, store = _coordinator()
        _stored_token(store)
        transport.queue(400, {"error": "invalid_grant"})

        token = coordinator.access_token()

        self.assertIsNone(token)
        self.assertIsNone(store.load())
        self.assertEqual(len(session.opened), 1, "a fresh browser sign-in should start")
        self.assertIs(coordinator.state, WorkosSignInState.WAITING)

    def test_reprompted_sign_in_completes(self) -> None:
        coordinator, transport, session, store = _coordinator()
        _stored_token(store)
        transport.queue(400, {"error": "invalid_grant"})
        coordinator.access_token()

        state = parse_qs(urlparse(session.opened[-1]).query)["state"][0]
        _queue_exchange(transport, coordinator)
        session.deliver(_callback_url(state, code="code-2"))

        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_IN)
        self.assertEqual(coordinator.access_token(), "access-1")

    def test_sign_out_clears_store(self) -> None:
        coordinator, _transport, _session, store = _coordinator()
        _stored_token(store, expires_at=10_000.0)
        coordinator.restore()

        coordinator.sign_out()

        self.assertIsNone(store.load())
        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_OUT)
        self.assertIsNone(coordinator.access_token())


class IOSBoundaryIntegrationTests(unittest.TestCase):
    """The coordinator driving the real iOS bridge classes with a fake Swift side."""

    def test_scene_open_url_completes_waiting_sign_in(self) -> None:
        from luvatrix_core.platform.ios.auth_session import IOSWebAuthenticationSession
        from luvatrix_core.platform.ios.url_router import UrlRouter
        from tests.test_ios_auth_session import FakeSwiftAuthSession

        router = UrlRouter()
        session = IOSWebAuthenticationSession(
            bridge=FakeSwiftAuthSession(),
            callback_scheme="ainomic",
            router=router,
        )
        transport = FakeTransport()
        coordinator = WorkosSignInCoordinator(
            _config(),
            session=session,
            token_store=InMemoryWorkosTokenStore(),
            transport=transport,
            clock=lambda: 100.0,
        )

        coordinator.begin_sign_in()
        state = parse_qs(urlparse(session._bridge.started[-1][0]).query)["state"][0]
        _queue_exchange(transport, coordinator)

        handled = router.handle_open_url(_callback_url(state, code="code-1"))

        self.assertTrue(handled)
        self.assertIs(coordinator.state, WorkosSignInState.SIGNED_IN)
        self.assertEqual(coordinator.access_token(), "access-1")

    def test_build_ios_workos_coordinator_loads_config(self) -> None:
        from luvatrix_core.platform.ios.auth_session import build_ios_workos_coordinator

        with tempfile.TemporaryDirectory() as td:
            Path(td, "app.toml").write_text(
                "\n".join(
                    [
                        "[auth.workos]",
                        f'instance_url = "{INSTANCE}"',
                        f'authkit_domain = "{AUTHKIT}"',
                        'client_id = "client_01JIOS"',
                    ]
                ),
                encoding="utf-8",
            )
            coordinator = build_ios_workos_coordinator(app_dir=td, environ={})

        self.assertEqual(coordinator.config.client_id, "client_01JIOS")
        self.assertEqual(coordinator.session.callback_scheme, "ainomic")


if __name__ == "__main__":
    unittest.main()
