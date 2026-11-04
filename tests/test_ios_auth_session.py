from __future__ import annotations

import unittest

import pytest

from luvatrix_core.platform.ios.auth_session import (
    IOSAuthSessionError,
    IOSWebAuthenticationSession,
    complete_auth_session,
)
from luvatrix_core.platform.ios.url_router import UrlRouter


class FakeSwiftAuthSession:
    """Fake for the ObjC `LuvatrixAuthSession` boundary on the Swift side.

    Selector names mirror `startSession:callbackScheme:` and `cancelSession`
    as rubicon-objc surfaces them to Python.
    """

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.cancel_calls = 0
        self.start_result = True

    def startSession_callbackScheme_(self, url: str, scheme: str) -> bool:
        self.started.append((url, scheme))
        return self.start_result

    def cancelSession(self) -> None:
        self.cancel_calls += 1


def _session(
    bridge: FakeSwiftAuthSession | None = None,
    *,
    router: UrlRouter | None = None,
) -> tuple[IOSWebAuthenticationSession, FakeSwiftAuthSession]:
    swift = bridge if bridge is not None else FakeSwiftAuthSession()
    session = IOSWebAuthenticationSession(
        bridge=swift,
        callback_scheme="ainomic",
        router=router if router is not None else UrlRouter(),
    )
    return session, swift


class IOSWebAuthenticationSessionTests(unittest.TestCase):
    def test_open_presents_session_with_url_and_scheme(self) -> None:
        session, swift = _session()
        callbacks: list[str | None] = []

        session.open("https://login.nomic.ai/oauth2/authorize?x=1", callbacks.append)

        self.assertEqual(swift.started, [("https://login.nomic.ai/oauth2/authorize?x=1", "ainomic")])
        self.assertTrue(session.active)

    def test_open_rejects_second_concurrent_session(self) -> None:
        session, _swift = _session()
        session.open("https://login.nomic.ai/one", lambda url: None)

        with pytest.raises(IOSAuthSessionError):
            session.open("https://login.nomic.ai/two", lambda url: None)

    def test_open_raises_when_swift_cannot_present(self) -> None:
        swift = FakeSwiftAuthSession()
        swift.start_result = False
        session, _ = _session(swift)

        with pytest.raises(IOSAuthSessionError):
            session.open("https://login.nomic.ai/oauth2/authorize", lambda url: None)
        self.assertFalse(session.active)

    def test_deliver_callback_routes_url_to_waiting_callback(self) -> None:
        session, _swift = _session()
        callbacks: list[str | None] = []
        session.open("https://login.nomic.ai/oauth2/authorize", callbacks.append)

        delivered = session.deliver_callback("ainomic://auth/callback?code=abc&state=s")

        self.assertTrue(delivered)
        self.assertEqual(callbacks, ["ainomic://auth/callback?code=abc&state=s"])
        self.assertFalse(session.active)
        self.assertFalse(session.deliver_callback("ainomic://auth/callback?code=again"))

    def test_complete_from_swift_delivers_callback_url(self) -> None:
        session, _swift = _session()
        callbacks: list[str | None] = []
        session.open("https://login.nomic.ai/oauth2/authorize", callbacks.append)

        session.complete_from_swift("ainomic://auth/callback?code=abc")

        self.assertEqual(callbacks, ["ainomic://auth/callback?code=abc"])

    def test_complete_from_swift_none_means_user_cancelled(self) -> None:
        session, _swift = _session()
        callbacks: list[str | None] = []
        session.open("https://login.nomic.ai/oauth2/authorize", callbacks.append)

        session.complete_from_swift(None)

        self.assertEqual(callbacks, [None])
        self.assertFalse(session.active)

    def test_cancel_cancels_swift_session_and_notifies_callback(self) -> None:
        session, swift = _session()
        callbacks: list[str | None] = []
        session.open("https://login.nomic.ai/oauth2/authorize", callbacks.append)

        session.cancel()

        self.assertEqual(swift.cancel_calls, 1)
        self.assertEqual(callbacks, [None])
        self.assertFalse(session.active)

    def test_module_level_complete_reaches_active_session(self) -> None:
        session, _swift = _session()
        callbacks: list[str | None] = []
        session.open("https://login.nomic.ai/oauth2/authorize", callbacks.append)
        try:
            self.assertTrue(complete_auth_session("ainomic://auth/callback?code=abc"))
        finally:
            session.cancel()
        self.assertEqual(callbacks, ["ainomic://auth/callback?code=abc"])

    def test_module_level_complete_without_active_session_returns_false(self) -> None:
        self.assertFalse(complete_auth_session("ainomic://auth/callback?code=abc"))

    def test_scene_open_url_reaches_waiting_session_via_router(self) -> None:
        router = UrlRouter()
        session, _swift = _session(router=router)
        callbacks: list[str | None] = []
        session.open("https://login.nomic.ai/oauth2/authorize", callbacks.append)

        handled = router.handle_open_url("ainomic://auth/callback?code=abc&state=s")

        self.assertTrue(handled)
        self.assertEqual(callbacks, ["ainomic://auth/callback?code=abc&state=s"])

    def test_scene_open_url_without_waiting_session_is_not_consumed(self) -> None:
        router = UrlRouter()
        _session(router=router)

        self.assertFalse(router.handle_open_url("ainomic://auth/callback?code=abc"))


if __name__ == "__main__":
    unittest.main()
