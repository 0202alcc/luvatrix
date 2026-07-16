from __future__ import annotations

from dataclasses import dataclass

from luvatrix.auth import (
    GoogleAuthorizationRequest,
    GoogleAuthError,
    GoogleOAuthClient,
    GoogleOAuthConfig,
    GoogleOAuthToken,
    GoogleSignInController,
    GoogleSignInState,
    InMemoryTokenStore,
    PlatformGoogleAuthSession,
    SecureAuthorizationRequestStore,
    SecureTokenStore,
)
from luvatrix.auth.ui import GoogleSignInButton
from luvatrix.app import InputState


def _oauth(*, store=None) -> GoogleOAuthClient:
    return GoogleOAuthClient(
        GoogleOAuthConfig("client-id", "com.example.app:/oauth2redirect", ("openid", "email", "profile")),
        token_store=store,
        post_form=lambda _url, _payload: {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        },
        clock=lambda: 100.0,
    )


@dataclass
class FakeAuthSession:
    request_url: str | None = None
    callback = None
    cancelled: bool = False

    def open(self, authorization_url: str, callback) -> None:
        self.request_url = authorization_url
        self.callback = callback

    def cancel(self) -> None:
        self.cancelled = True


def test_sign_in_opens_trusted_session_and_completes_from_callback() -> None:
    session = FakeAuthSession()
    invalidations: list[None] = []
    controller = GoogleSignInController(
        _oauth(),
        session=session,
        fetch_profile=lambda token: {
            "sub": "user-1",
            "email": "person@example.com",
            "name": "Person Example",
            "picture": "https://example.com/person.png",
        },
        invalidate=lambda: invalidations.append(None),
    )

    controller.sign_in()

    assert controller.state is GoogleSignInState.WAITING
    assert session.request_url is not None
    assert session.callback is not None
    session.callback(f"com.example.app:/oauth2redirect?code=auth-code&state={controller.pending_state}")

    assert controller.state is GoogleSignInState.SIGNED_IN
    assert controller.token is not None
    assert controller.profile is not None
    assert controller.profile.email == "person@example.com"
    assert len(invalidations) >= 2


def test_callback_rejects_mismatched_state_without_exchanging_code() -> None:
    session = FakeAuthSession()
    controller = GoogleSignInController(_oauth(), session=session)
    controller.sign_in()

    session.callback("com.example.app:/oauth2redirect?code=stolen&state=wrong")

    assert controller.state is GoogleSignInState.FAILED
    assert isinstance(controller.error, GoogleAuthError)
    assert controller.token is None


def test_callback_rejects_a_different_redirect_uri() -> None:
    session = FakeAuthSession()
    controller = GoogleSignInController(_oauth(), session=session)
    controller.sign_in()

    session.callback(f"evil.example:/oauth2redirect?code=auth-code&state={controller.pending_state}")

    assert controller.state is GoogleSignInState.FAILED
    assert isinstance(controller.error, GoogleAuthError)


def test_callback_surfaces_provider_error_and_cancellation() -> None:
    session = FakeAuthSession()
    controller = GoogleSignInController(_oauth(), session=session)
    controller.sign_in()

    session.callback(
        f"com.example.app:/oauth2redirect?error=access_denied&error_description=Nope&state={controller.pending_state}"
    )

    assert controller.state is GoogleSignInState.CANCELLED
    assert controller.error is None


def test_cancel_closes_active_session() -> None:
    session = FakeAuthSession()
    controller = GoogleSignInController(_oauth(), session=session)
    controller.sign_in()

    controller.cancel()

    assert session.cancelled
    assert controller.state is GoogleSignInState.CANCELLED


def test_restore_and_sign_out_use_the_configured_store() -> None:
    store = InMemoryTokenStore()
    token = GoogleOAuthToken("saved", "Bearer", expires_at=1000.0, refresh_token="refresh")
    store.save(token)
    controller = GoogleSignInController(
        _oauth(store=store),
        session=FakeAuthSession(),
        fetch_profile=lambda _token: {"sub": "user-1", "email": "person@example.com"},
    )

    restored = controller.restore()

    assert restored is token
    assert controller.state is GoogleSignInState.SIGNED_IN
    controller.sign_out()
    assert controller.state is GoogleSignInState.IDLE
    assert store.load() is None


def test_duplicate_sign_in_is_rejected_while_session_is_active() -> None:
    controller = GoogleSignInController(_oauth(), session=FakeAuthSession())
    controller.sign_in()

    try:
        controller.sign_in()
    except GoogleAuthError as exc:
        assert "already" in str(exc)
    else:
        raise AssertionError("duplicate sign-in should fail")


def test_platform_session_opens_browser_and_delivers_callback_once() -> None:
    opened: list[str] = []
    callbacks: list[str | None] = []
    session = PlatformGoogleAuthSession(open_browser=lambda url: opened.append(url))

    session.open("https://accounts.example/auth", callbacks.append)
    assert opened == ["https://accounts.example/auth"]
    assert session.active
    assert session.deliver_callback("myapp:/callback?code=one")
    assert not session.deliver_callback("myapp:/callback?code=two")
    assert callbacks == ["myapp:/callback?code=one"]
    assert not session.active


def test_platform_session_cancel_notifies_controller_callback() -> None:
    callbacks: list[str | None] = []
    session = PlatformGoogleAuthSession(open_browser=lambda _url: None)
    session.open("https://accounts.example/auth", callbacks.append)

    session.cancel()

    assert callbacks == [None]
    assert not session.active


def test_secure_authorization_request_store_round_trips_pkce_state() -> None:
    values: dict[str, str] = {}
    store = SecureAuthorizationRequestStore(
        read_secret=lambda key: values.get(key),
        write_secret=lambda key, value: values.__setitem__(key, value),
        delete_secret=lambda key: values.pop(key, None),
        key="google-pending-auth",
    )
    request = GoogleAuthorizationRequest(
        url="https://accounts.example/auth?state=state-one",
        state="state-one",
        code_verifier="pkce-verifier",
    )

    store.save(request, redirect_uri="com.example.app:/oauth2redirect", created_at=123.0)

    pending = store.load()
    assert pending is not None
    assert pending.request == request
    assert pending.redirect_uri == "com.example.app:/oauth2redirect"
    assert pending.created_at == 123.0
    store.clear()
    assert store.load() is None


def test_controller_resumes_saved_authorization_after_process_recreation() -> None:
    values: dict[str, str] = {}

    def authorization_store() -> SecureAuthorizationRequestStore:
        return SecureAuthorizationRequestStore(
            read_secret=lambda key: values.get(key),
            write_secret=lambda key, value: values.__setitem__(key, value),
            delete_secret=lambda key: values.pop(key, None),
            key="google-pending-auth",
        )

    first_session = PlatformGoogleAuthSession(open_browser=lambda _url: None)
    first = GoogleSignInController(
        _oauth(),
        session=first_session,
        pending_authorization_store=authorization_store(),
        clock=lambda: 100.0,
    )
    first.sign_in()
    pending_state = first.pending_state
    pending_request = authorization_store().load()
    assert pending_request is not None

    exchanges: list[dict[str, str]] = []
    oauth = GoogleOAuthClient(
        GoogleOAuthConfig("client-id", "com.example.app:/oauth2redirect", ("openid", "email", "profile")),
        post_form=lambda _url, payload: exchanges.append(payload) or {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        },
        clock=lambda: 101.0,
    )
    resumed = GoogleSignInController(
        oauth,
        session=PlatformGoogleAuthSession(open_browser=lambda _url: None),
        pending_authorization_store=authorization_store(),
        fetch_profile=lambda _token: {"sub": "user-1", "email": "person@example.com"},
        clock=lambda: 101.0,
    )

    assert resumed.deliver_callback(
        f"com.example.app:/oauth2redirect?code=auth-code&state={pending_state}"
    )

    assert resumed.state is GoogleSignInState.SIGNED_IN
    assert exchanges[0]["code_verifier"] == pending_request.request.code_verifier
    assert authorization_store().load() is None


def test_controller_rejects_expired_saved_authorization() -> None:
    values: dict[str, str] = {}
    store = SecureAuthorizationRequestStore(
        read_secret=lambda key: values.get(key),
        write_secret=lambda key, value: values.__setitem__(key, value),
        delete_secret=lambda key: values.pop(key, None),
        key="google-pending-auth",
    )
    store.save(
        GoogleAuthorizationRequest("https://accounts.example/auth", "old-state", "old-verifier"),
        redirect_uri="com.example.app:/oauth2redirect",
        created_at=100.0,
    )
    controller = GoogleSignInController(
        _oauth(),
        session=PlatformGoogleAuthSession(open_browser=lambda _url: None),
        pending_authorization_store=store,
        authorization_max_age_seconds=600.0,
        clock=lambda: 701.0,
    )

    assert not controller.deliver_callback(
        "com.example.app:/oauth2redirect?code=auth-code&state=old-state"
    )

    assert controller.state is GoogleSignInState.FAILED
    assert controller.error is not None
    assert "expired" in str(controller.error).lower()
    assert store.load() is None


def test_secure_token_store_round_trips_without_exposing_storage_policy() -> None:
    values: dict[str, str] = {}
    store = SecureTokenStore(
        read_secret=lambda key: values.get(key),
        write_secret=lambda key, value: values.__setitem__(key, value),
        delete_secret=lambda key: values.pop(key, None),
        key="google-account",
    )
    token = GoogleOAuthToken("access", "Bearer", 1234.0, "refresh", "openid email")

    store.save(token)

    assert store.load() == token
    assert "access" in values["google-account"]
    store.clear()
    assert store.load() is None


def test_secure_token_store_rejects_corrupted_data() -> None:
    store = SecureTokenStore(
        read_secret=lambda _key: '{"access_token":"broken"}',
        write_secret=lambda _key, _value: None,
        delete_secret=lambda _key: None,
        key="google-account",
    )

    try:
        store.load()
    except GoogleAuthError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("corrupted secure tokens should fail closed")


def test_sign_in_controller_requires_openid_scope() -> None:
    oauth = GoogleOAuthClient(
        GoogleOAuthConfig("client-id", "com.example.app:/callback", ("email",)),
        post_form=lambda _url, _payload: {},
    )

    try:
        GoogleSignInController(oauth, session=FakeAuthSession())
    except ValueError as exc:
        assert "openid" in str(exc)
    else:
        raise AssertionError("identity sign-in requires the openid scope")


def test_sign_in_button_drives_controller_and_reflects_state() -> None:
    session = FakeAuthSession()
    controller = GoogleSignInController(_oauth(), session=session)
    button = GoogleSignInButton(controller)
    click = InputState(mouse_x=50, mouse_y=20, mouse_in_window=True, left_clicked=True)

    assert button.update(click, x=0, y=0, width=120, height=44)

    assert controller.state is GoogleSignInState.WAITING
    assert button.label == "Waiting for Google..."
    assert button.disabled


def test_sign_in_button_ignores_clicks_outside_bounds() -> None:
    controller = GoogleSignInController(_oauth(), session=FakeAuthSession())
    button = GoogleSignInButton(controller)
    click = InputState(mouse_x=500, mouse_y=500, mouse_in_window=True, left_clicked=True)

    assert not button.update(click, x=0, y=0, width=120, height=44)
    assert controller.state is GoogleSignInState.IDLE


def test_sign_in_button_renders_complete_first_party_control() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Frame:
        def rect(self, **kwargs) -> None:
            calls.append(("rect", kwargs))

        def text(self, text: str, **kwargs) -> None:
            calls.append((text, kwargs))

    button = GoogleSignInButton(GoogleSignInController(_oauth(), session=FakeAuthSession()))

    button.render(Frame(), x=10, y=20, width=220, height=48)

    assert calls[0][0] == "rect"
    assert any(name == "G" for name, _kwargs in calls)
    assert any(name == "Sign in with Google" for name, _kwargs in calls)
