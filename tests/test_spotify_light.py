"""Tests for the Spotify Light example app (examples/spotify_light).

The app's data layer (OAuth PKCE, Web API models, playback state math,
persistence, album-art caching, background worker) is exercised without
network access: HTTP boundaries are injected callables.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "examples" / "spotify_light"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import sl_api  # noqa: E402
import sl_art  # noqa: E402
import sl_models  # noqa: E402
import sl_oauth  # noqa: E402
import sl_store  # noqa: E402
import sl_ui  # noqa: E402
import sl_worker  # noqa: E402


# --------------------------------------------------------------------------
# PKCE + OAuth URL construction
# --------------------------------------------------------------------------

class TestPkce:
    def test_verifier_length_charset_and_uniqueness(self):
        verifier = sl_oauth.generate_verifier()
        assert len(verifier) == 64
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert set(verifier) <= allowed
        assert sl_oauth.generate_verifier() != sl_oauth.generate_verifier()

    def test_challenge_matches_rfc7636_appendix_b(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        assert sl_oauth.challenge_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    def test_challenge_is_base64url_unpadded_sha256(self):
        verifier = sl_oauth.generate_verifier()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert sl_oauth.challenge_s256(verifier) == expected
        assert len(sl_oauth.challenge_s256(verifier)) == 43

    def test_state_is_unique_and_url_safe(self):
        a, b = sl_oauth.generate_state(), sl_oauth.generate_state()
        assert a != b
        assert set(a) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class TestAuthorizeUrl:
    def test_carries_pkce_and_scope_parameters(self):
        url = sl_oauth.authorize_url(
            client_id="cid",
            redirect_uri="http://127.0.0.1:8888/callback",
            challenge="chal",
            state="st",
        )
        assert url.startswith(sl_oauth.AUTHORIZE_URL + "?")
        assert "response_type=code" in url
        assert "client_id=cid" in url
        assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback" in url
        assert "code_challenge=chal" in url
        assert "code_challenge_method=S256" in url
        assert "state=st" in url
        assert "user-modify-playback-state" in url
        assert " " not in url

    def test_redirect_uri_uses_loopback_callback(self):
        assert sl_oauth.redirect_uri_for_port(8888) == "http://127.0.0.1:8888/callback"


class TestCallbackParsing:
    def test_returns_code_on_state_match(self):
        code = sl_oauth.parse_callback_query("code=AQD-xyz123&state=expected", "expected")
        assert code == "AQD-xyz123"

    def test_rejects_state_mismatch(self):
        with pytest.raises(sl_oauth.OAuthError, match="state"):
            sl_oauth.parse_callback_query("code=abc&state=forged", "expected")

    def test_surfaces_spotify_error(self):
        with pytest.raises(sl_oauth.OAuthError, match="access_denied"):
            sl_oauth.parse_callback_query("error=access_denied&state=expected", "expected")

    def test_requires_code(self):
        with pytest.raises(sl_oauth.OAuthError):
            sl_oauth.parse_callback_query("state=expected", "expected")

    def test_decodes_urlencoded_code(self):
        assert sl_oauth.parse_callback_query("code=ab%2Fcd%2Be&state=s", "s") == "ab/cd+e"

    def test_extract_callback_query_from_request_line(self):
        assert (
            sl_oauth.extract_callback_query("GET /callback?code=abc&state=xyz HTTP/1.1")
            == "code=abc&state=xyz"
        )

    def test_parse_callback_url_full_url(self):
        # Embedded web-view intercept hands us the whole URL, not a request line.
        url = "http://127.0.0.1:8888/callback?code=AQD-xyz123&state=expected"
        assert sl_oauth.parse_callback_url(url, "expected") == "AQD-xyz123"

    def test_parse_callback_url_rejects_state_mismatch(self):
        url = "http://127.0.0.1:8888/callback?code=abc&state=forged"
        with pytest.raises(sl_oauth.OAuthError, match="state"):
            sl_oauth.parse_callback_url(url, "expected")

    def test_extract_callback_query_ignores_other_requests(self):
        assert sl_oauth.extract_callback_query("GET /favicon.ico HTTP/1.1") is None
        assert sl_oauth.extract_callback_query("garbage") is None
        assert sl_oauth.extract_callback_query("POST /callback?code=a HTTP/1.1") is None


class TestTokenSet:
    def _body(self, **overrides):
        payload = {
            "access_token": "BQD-access",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "AQD-refresh",
            "scope": "user-read-private user-read-email",
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_parse_full_response(self):
        tokens = sl_oauth.parse_token_response(self._body(), now=1_000.0)
        assert tokens.access_token == "BQD-access"
        assert tokens.refresh_token == "AQD-refresh"
        assert tokens.expires_at == 1_000.0 + 3600
        assert tokens.scope == "user-read-private user-read-email"

    def test_defaults_expires_in(self):
        tokens = sl_oauth.parse_token_response(json.dumps({"access_token": "x"}), now=500.0)
        assert tokens.expires_at == 500.0 + 3600

    def test_error_body_raises_with_description(self):
        body = json.dumps({"error": "invalid_grant", "error_description": "Refresh token revoked"})
        with pytest.raises(sl_oauth.OAuthError, match="Refresh token revoked"):
            sl_oauth.parse_token_response(body, now=0.0)

    def test_garbage_body_raises(self):
        with pytest.raises(sl_oauth.OAuthError):
            sl_oauth.parse_token_response("not json", now=0.0)

    def test_needs_refresh_within_skew(self):
        tokens = sl_oauth.parse_token_response(self._body(expires_in=3600), now=1_000.0)
        assert tokens.needs_refresh(1_000.0 + 3600 - 59)
        assert tokens.needs_refresh(1_000.0 + 3600)
        assert not tokens.needs_refresh(1_000.0 + 3600 - 61)

    def test_with_fallback_refresh_keeps_previous(self):
        old = sl_oauth.parse_token_response(self._body(), now=0.0)
        refreshed = sl_oauth.parse_token_response(
            json.dumps({"access_token": "new", "expires_in": 3600}), now=3600.0
        ).with_fallback_refresh(old)
        assert refreshed.refresh_token == "AQD-refresh"
        assert refreshed.access_token == "new"

    def test_with_fallback_refresh_prefers_new_token(self):
        old = sl_oauth.parse_token_response(self._body(), now=0.0)
        refreshed = sl_oauth.parse_token_response(
            self._body(access_token="new", refresh_token="new-refresh"), now=3600.0
        ).with_fallback_refresh(old)
        assert refreshed.refresh_token == "new-refresh"

    def test_json_roundtrip(self):
        tokens = sl_oauth.parse_token_response(self._body(), now=1_000.0)
        assert sl_oauth.TokenSet.from_json(tokens.to_json()) == tokens


class TestTokenEndpointCalls:
    def test_exchange_code_posts_pkce_form(self):
        calls = []

        def fake_post(url, form, headers=None):
            calls.append((url, form))
            return json.dumps({"access_token": "tok", "expires_in": 3600, "refresh_token": "r"})

        tokens = sl_oauth.exchange_code(
            client_id="cid",
            redirect_uri="http://127.0.0.1:8888/callback",
            code="the-code",
            verifier="the-verifier",
            http_post=fake_post,
            now=1_000.0,
        )
        assert tokens.access_token == "tok"
        url, form = calls[0]
        assert url == sl_oauth.TOKEN_URL
        assert form["grant_type"] == "authorization_code"
        assert form["code"] == "the-code"
        assert form["redirect_uri"] == "http://127.0.0.1:8888/callback"
        assert form["client_id"] == "cid"
        assert form["code_verifier"] == "the-verifier"

    def test_refresh_posts_refresh_grant(self):
        calls = []

        def fake_post(url, form, headers=None):
            calls.append((url, form))
            return json.dumps({"access_token": "tok2", "expires_in": 3600})

        tokens = sl_oauth.refresh_tokens("cid", "rt", http_post=fake_post, now=2_000.0)
        assert tokens.access_token == "tok2"
        _, form = calls[0]
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "rt"
        assert form["client_id"] == "cid"


class TestLoopbackReceiver:
    def test_roundtrip_code_delivery(self):
        import http.client
        import threading

        receiver = sl_oauth.LoopbackReceiver(port=0)
        receiver.start()
        try:
            port = receiver.port
            result = {}

            def wait():
                try:
                    result["code"] = receiver.wait_for_code(expected_state="st", timeout=5.0)
                except Exception as exc:  # pragma: no cover - diagnostic path
                    result["error"] = exc

            thread = threading.Thread(target=wait, daemon=True)
            thread.start()
            # Give the accept loop a moment, then deliver the callback.
            time.sleep(0.1)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/callback?code=loopback-code&state=st")
            response = conn.getresponse()
            response.read()
            conn.close()
            thread.join(timeout=5.0)
            assert result.get("code") == "loopback-code"
            assert response.status == 200
        finally:
            receiver.close()

    def test_timeout_raises(self):
        receiver = sl_oauth.LoopbackReceiver(port=0)
        receiver.start()
        try:
            with pytest.raises(sl_oauth.OAuthError, match="timed out"):
                receiver.wait_for_code(expected_state="st", timeout=0.2)
        finally:
            receiver.close()


# --------------------------------------------------------------------------
# Spotify Web API models
# --------------------------------------------------------------------------

def _image(url="https://i.scdn.co/image/abc", width=640, height=640):
    return {"url": url, "width": width, "height": height}


def _artist(name="Artist", artist_id="a1"):
    return {"id": artist_id, "name": name, "uri": f"spotify:artist:{artist_id}", "images": [_image()]}


def _album(name="Album", album_id="al1"):
    return {
        "id": album_id,
        "name": name,
        "uri": f"spotify:album:{album_id}",
        "artists": [_artist()],
        "images": [_image(), _image("https://i.scdn.co/image/small", 64, 64)],
        "release_date": "2024-01-01",
        "total_tracks": 10,
    }


def _track(name="Track", track_id="t1", duration=200_000):
    return {
        "id": track_id,
        "name": name,
        "uri": f"spotify:track:{track_id}",
        "duration_ms": duration,
        "explicit": False,
        "track_number": 3,
        "artists": [_artist()],
        "album": _album(),
    }


class TestModelParsing:
    def test_parse_track_full(self):
        track = sl_models.parse_track(_track())
        assert track.id == "t1"
        assert track.name == "Track"
        assert track.duration_ms == 200_000
        assert track.artists[0].name == "Artist"
        assert track.album is not None
        assert track.album.name == "Album"
        assert track.track_number == 3
        assert not track.explicit

    def test_parse_track_tolerates_missing_album_and_images(self):
        payload = _track()
        payload["album"] = None
        track = sl_models.parse_track(payload)
        assert track.album is None
        payload["album"] = _album()
        payload["album"]["images"] = []
        assert sl_models.parse_track(payload).album.images == ()

    def test_parse_track_or_none_filters_local_and_broken_items(self):
        assert sl_models.parse_track_or_none(None) is None
        assert sl_models.parse_track_or_none({}) is None
        local = _track()
        local["uri"] = "spotify:local:artist:album:track:1"
        assert sl_models.parse_track_or_none(local) is None
        assert sl_models.parse_track_or_none(_track()) is not None

    def test_parse_playlist(self):
        playlist = sl_models.parse_playlist(
            {
                "id": "p1",
                "name": "Chill",
                "uri": "spotify:playlist:p1",
                "images": [_image()],
                "owner": {"display_name": "Alec"},
                "tracks": {"total": 42},
            }
        )
        assert playlist.name == "Chill"
        assert playlist.owner_name == "Alec"
        assert playlist.track_count == 42

    def test_parse_device(self):
        device = sl_models.parse_device(
            {
                "id": "d1",
                "name": "MacBook",
                "type": "Computer",
                "is_active": True,
                "is_restricted": False,
                "volume_percent": 65,
            }
        )
        assert device.kind == "Computer"
        assert device.is_active
        assert device.volume_percent == 65

    def test_parse_player_state_with_track(self):
        state = sl_models.parse_player_state(
            {
                "device": {
                    "id": "d1",
                    "name": "MacBook",
                    "type": "Computer",
                    "is_active": True,
                    "is_restricted": False,
                    "volume_percent": 65,
                },
                "shuffle_state": True,
                "repeat_state": "context",
                "timestamp": 1_730_000_000_000,
                "progress_ms": 45_230,
                "is_playing": True,
                "item": _track(),
            }
        )
        assert state.is_playing
        assert state.shuffle
        assert state.repeat == "context"
        assert state.progress_ms == 45_230
        assert state.track is not None and state.track.name == "Track"
        assert state.device is not None and state.device.name == "MacBook"

    def test_parse_player_state_with_null_item_and_no_device(self):
        state = sl_models.parse_player_state(
            {
                "device": None,
                "shuffle_state": False,
                "repeat_state": "off",
                "progress_ms": None,
                "is_playing": False,
                "item": None,
            }
        )
        assert state.track is None
        assert state.device is None
        assert state.progress_ms == 0

    def test_parse_profile(self):
        profile = sl_models.parse_profile(
            {
                "id": "u1",
                "display_name": "Alec",
                "email": "alec@example.com",
                "images": [_image()],
                "product": "premium",
            }
        )
        assert profile.display_name == "Alec"
        assert profile.product == "premium"
        assert profile.image_url == "https://i.scdn.co/image/abc"

    def test_pick_image_prefers_smallest_covering_target(self):
        images = sl_models.parse_album(_album()).images
        assert sl_models.pick_image_url(images, 100) == "https://i.scdn.co/image/abc"
        assert sl_models.pick_image_url(images, 1000) == "https://i.scdn.co/image/abc"
        assert sl_models.pick_image_url(images, 32) == "https://i.scdn.co/image/small"
        assert sl_models.pick_image_url((), 100) is None


def _sized_images() -> tuple[sl_models.Image, ...]:
    return (
        sl_models.Image("https://i/64", 64, 64),
        sl_models.Image("https://i/300", 300, 300),
        sl_models.Image("https://i/640", 640, 640),
    )


class TestCardImageTarget:
    """Cards pick art URLs for the display's device pixels: a 180pt card on a
    2x Retina display needs ~360px of source, so the 640px image wins."""

    def test_card_defaults_to_point_target(self):
        album = sl_models.Album(id="a1", name="Al", uri="u", artists=(), images=_sized_images())
        assert sl_ui.album_card(album).image_url == "https://i/300"

    def test_card_honors_device_pixel_target(self):
        album = sl_models.Album(id="a1", name="Al", uri="u", artists=(), images=_sized_images())
        assert sl_ui.album_card(album, image_target_px=360).image_url == "https://i/640"

    def test_home_sections_thread_the_target(self):
        album = sl_models.Album(id="a1", name="Al", uri="u", artists=(), images=_sized_images())
        sections = sl_ui.build_home_sections(
            top_tracks=(), new_releases=(album,), playlists=(), top_artists=(),
            image_target_px=360,
        )
        assert sections[0].cards[0].image_url == "https://i/640"

    def test_parse_search_results(self):
        payload = {
            "tracks": {"items": [_track("One", "t1"), _track("Two", "t2")], "next": None},
            "albums": {"items": [_album()], "next": "https://..."},
            "artists": {"items": [_artist()], "next": None},
            "playlists": {
                "items": [
                    {
                        "id": "p1",
                        "name": "Chill",
                        "uri": "spotify:playlist:p1",
                        "images": [],
                        "owner": {"display_name": "Alec"},
                        "tracks": {"total": 42},
                    }
                ],
                "next": None,
            },
        }
        results = sl_models.parse_search_results(payload)
        assert [t.name for t in results.tracks] == ["One", "Two"]
        assert len(results.albums) == 1
        assert len(results.artists) == 1
        assert results.playlists[0].name == "Chill"

    def test_parse_search_results_tolerates_missing_sections(self):
        results = sl_models.parse_search_results({"tracks": {"items": [_track()]}})
        assert len(results.tracks) == 1
        assert results.albums == ()

    def test_parse_playlist_tracks_page_filters_unplayable(self):
        payload = {
            "items": [
                {"track": _track("Playable", "t1")},
                {"track": None},
                {"track": _track("Also playable", "t2")},
            ],
            "next": None,
        }
        tracks, has_more = sl_models.parse_playlist_tracks_page(payload)
        assert [t.name for t in tracks] == ["Playable", "Also playable"]
        assert not has_more

    def test_parse_playlists_page_has_more(self):
        payload = {
            "items": [
                {
                    "id": "p1",
                    "name": "A",
                    "uri": "spotify:playlist:p1",
                    "images": [],
                    "owner": {},
                    "tracks": {"total": 1},
                }
            ],
            "next": "https://api.spotify.com/v1/me/playlists?offset=50",
        }
        _, has_more = sl_models.parse_playlists_page(payload)
        assert has_more


# --------------------------------------------------------------------------
# API client (injected HTTP)
# --------------------------------------------------------------------------

class FakeHttp:
    """Minimal injectable HTTP transport matching sl_api's expected protocol."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def add(self, method, path_substring, status, payload, headers=None):
        self.routes[(method, path_substring)] = (status, payload, headers or {})

    def request(self, method, url, *, token, payload=None):
        self.calls.append((method, url, payload))
        for (m, sub), (status, body, headers) in self.routes.items():
            if m == method and sub in url:
                return status, body, headers
        return 404, {"error": {"status": 404, "message": "Not found"}}, {}


def _client(http):
    return sl_api.SpotifyClient(token_provider=lambda: "tok", http=http)


class TestApiClient:
    def test_search_url_encodes_query_and_types(self):
        url = sl_api.search_url("bon iver", ("track", "album"), limit=7, offset=14)
        assert url.startswith(sl_api.API_BASE + "/search?")
        assert "q=bon+iver" in url or "q=bon%20iver" in url
        assert "type=track%2Calbum" in url or "type=track,album" in url
        assert "limit=7" in url
        assert "offset=14" in url

    def test_search_parses_results(self):
        http = FakeHttp()
        http.add("GET", "/search?", 200, {"tracks": {"items": [_track()]}})
        results = _client(http).search("hello")
        assert len(results.tracks) == 1
        assert http.calls[0][1].startswith(sl_api.API_BASE + "/search?")
        assert "q=hello" in http.calls[0][1]

    def test_player_state_handles_204_no_content(self):
        http = FakeHttp()
        http.add("GET", "/me/player", 204, None)
        assert _client(http).player_state() is None

    def test_devices_parse(self):
        http = FakeHttp()
        http.add(
            "GET",
            "/me/player/devices",
            200,
            {
                "devices": [
                    {
                        "id": "d1",
                        "name": "MacBook",
                        "type": "Computer",
                        "is_active": True,
                        "is_restricted": False,
                        "volume_percent": 65,
                    }
                ]
            },
        )
        devices = _client(http).devices()
        assert devices[0].name == "MacBook"

    def test_play_sends_context_body(self):
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 204, None)
        _client(http).play(context_uri="spotify:playlist:p1", offset_uri="spotify:track:t9", device_id="d1")
        method, url, payload = http.calls[0]
        assert method == "PUT"
        assert "device_id=d1" in url
        assert payload["context_uri"] == "spotify:playlist:p1"
        assert payload["offset"] == {"uri": "spotify:track:t9"}

    def test_play_sends_uris_body(self):
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 204, None)
        _client(http).play(uris=["spotify:track:t1"])
        _, _, payload = http.calls[0]
        assert payload == {"uris": ["spotify:track:t1"]}

    def test_seek_volume_shuffle_repeat_transfer(self):
        http = FakeHttp()
        http.add("PUT", "/me/player/seek", 204, None)
        http.add("PUT", "/me/player/volume", 204, None)
        http.add("PUT", "/me/player/shuffle", 204, None)
        http.add("PUT", "/me/player/repeat", 204, None)
        http.add("PUT", "/me/player", 204, None)
        client = _client(http)
        client.seek(12_345, device_id="d1")
        client.set_volume(40, device_id="d1")
        client.set_shuffle(True, device_id="d1")
        client.set_repeat("track", device_id="d1")
        client.transfer("d2", play=True)
        urls = [url for _, url, _ in http.calls]
        assert "position_ms=12345" in urls[0]
        assert "volume_percent=40" in urls[1]
        assert "state=true" in urls[2]
        assert "state=track" in urls[3]
        assert http.calls[4][2] == {"device_ids": ["d2"], "play": True}

    def test_error_mapping_premium_required(self):
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 403, {"error": {"status": 403, "message": "Premium required"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).play(uris=["spotify:track:t1"])
        assert excinfo.value.kind == sl_api.ErrorKind.PREMIUM_REQUIRED

    def test_error_mapping_device_not_found(self):
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 404, {"error": {"status": 404, "message": "Device not found"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).play(uris=["spotify:track:t1"])
        assert excinfo.value.kind == sl_api.ErrorKind.DEVICE_NOT_FOUND

    def test_error_mapping_unauthorized(self):
        http = FakeHttp()
        http.add("GET", "/me", 401, {"error": {"status": 401, "message": "The access token expired"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).me()
        assert excinfo.value.kind == sl_api.ErrorKind.UNAUTHORIZED

    def test_error_mapping_generic_includes_status(self):
        http = FakeHttp()
        http.add("GET", "/me", 500, {"error": {"status": 500, "message": "boom"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).me()
        assert excinfo.value.kind == sl_api.ErrorKind.API
        assert "500" in str(excinfo.value)

    def test_error_mapping_403_no_active_device_reason(self):
        """Round 28 (Alec): pressing play errored 403. Spotify answers
        play-without-an-active-device as 403 + reason NO_ACTIVE_DEVICE on
        some surfaces (not only the 404 mapping already handled) — that is
        the device flow, not a generic failure and not premium."""
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 403,
                 {"error": {"status": 403,
                            "message": "Player command failed: No active device found",
                            "reason": "NO_ACTIVE_DEVICE"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).play(uris=["spotify:track:t1"])
        assert excinfo.value.kind == sl_api.ErrorKind.DEVICE_NOT_FOUND

    def test_error_mapping_no_active_device_message_without_reason(self):
        """Same condition, body carrying only the message string."""
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 403,
                 {"error": {"status": 403,
                            "message": "Player command failed: No active device found"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).play(uris=["spotify:track:t1"])
        assert excinfo.value.kind == sl_api.ErrorKind.DEVICE_NOT_FOUND

    def test_error_mapping_restricted_device_is_not_premium(self):
        """A restricted device is not a premium problem: the old
        substring map misreported it as PREMIUM_REQUIRED, which toasted
        'Spotify Premium is required' at a paying user."""
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 403,
                 {"error": {"status": 403,
                            "message": "Player command failed: Restricted device",
                            "reason": "UNKNOWN"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).play(uris=["spotify:track:t1"])
        assert excinfo.value.kind == sl_api.ErrorKind.API
        assert "Restricted device" in str(excinfo.value)

    def test_error_reason_is_carried_verbatim(self):
        """The reason token is the actionable half of a Spotify player error
        (e.g. a development-mode restriction). It must reach the user
        verbatim — the toast is how Alec reports it."""
        http = FakeHttp()
        http.add("PUT", "/me/player/play", 403,
                 {"error": {"status": 403,
                            "message": "Player command failed: unsupported for this app",
                            "reason": "UNSUPPORTED_ACTION"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).play(uris=["spotify:track:t1"])
        message = str(excinfo.value)
        assert "unsupported for this app" in message
        assert "UNSUPPORTED_ACTION" in message

    def test_429_maps_to_rate_limited_with_retry_after(self):
        """Alec hit a spontaneous 429 while idling (round-28 build). The
        client must surface 429 as its own kind carrying the Retry-After
        seconds, so the app can pause its poll loop instead of hammering
        straight through the rate-limit window."""
        http = FakeHttp()
        http.add("GET", "/me/player/devices", 429,
                 {"error": {"status": 429, "message": "API rate limit exceeded"}},
                 headers={"Retry-After": "30"})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).devices()
        error = excinfo.value
        assert error.kind == sl_api.ErrorKind.RATE_LIMITED
        assert error.status == 429
        assert error.retry_after_secs == 30.0
        assert "rate limit" in str(error).lower()

    def test_429_retry_after_lookup_is_case_insensitive(self):
        """HTTP header names are case-insensitive; Spotify's casing is not
        a contract we control."""
        http = FakeHttp()
        http.add("GET", "/me/player/devices", 429,
                 {"error": {"status": 429, "message": "API rate limit exceeded"}},
                 headers={"retry-after": "7"})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).devices()
        assert excinfo.value.retry_after_secs == 7.0

    def test_429_without_retry_after_leaves_hint_none(self):
        """No header → the app falls back to its default backoff."""
        http = FakeHttp()
        http.add("GET", "/me/player/devices", 429,
                 {"error": {"status": 429, "message": "API rate limit exceeded"}})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).devices()
        assert excinfo.value.kind == sl_api.ErrorKind.RATE_LIMITED
        assert excinfo.value.retry_after_secs is None

    def test_429_non_numeric_retry_after_leaves_hint_none(self):
        http = FakeHttp()
        http.add("GET", "/me/player/devices", 429,
                 {"error": {"status": 429, "message": "API rate limit exceeded"}},
                 headers={"Retry-After": "soon"})
        with pytest.raises(sl_api.ApiError) as excinfo:
            _client(http).devices()
        assert excinfo.value.retry_after_secs is None


# --------------------------------------------------------------------------
# UI helpers (pure presentation logic)
# --------------------------------------------------------------------------

class TestUiHelpers:
    def test_format_duration(self):
        assert sl_ui.format_duration_ms(0) == "0:00"
        assert sl_ui.format_duration_ms(59_000) == "0:59"
        assert sl_ui.format_duration_ms(200_000) == "3:20"
        assert sl_ui.format_duration_ms(3_599_999) == "59:59"
        assert sl_ui.format_duration_ms(3_600_000) == "1:00:00"

    def test_truncate_adds_ellipsis(self):
        assert sl_ui.truncate("short", 10) == "short"
        assert sl_ui.truncate("a much longer title", 10) == "a much lo…"
        assert len(sl_ui.truncate("a much longer title", 10)) == 10
        assert sl_ui.truncate("abc", 3) == "abc"
        assert sl_ui.truncate("abcd", 3) == "ab…"

    def test_grid_columns_scales_and_clamps(self):
        assert sl_ui.grid_columns(600, card_width=180, gap=24) >= 2
        assert sl_ui.grid_columns(400, card_width=180, gap=24) == 2
        wide = sl_ui.grid_columns(4000, card_width=180, gap=24)
        assert wide <= 8
        assert sl_ui.grid_columns(940, card_width=180, gap=24) == 4

    def test_interpolate_progress_clamps_to_duration(self):
        base_ts = time.monotonic() - 2.0
        progress = sl_ui.interpolate_progress(
            base_ms=45_000, base_monotonic=base_ts, duration_ms=46_000, playing=True
        )
        assert progress == 46_000  # clamped, not 47_000

    def test_interpolate_progress_paused_is_static(self):
        base_ts = time.monotonic() - 10.0
        progress = sl_ui.interpolate_progress(
            base_ms=45_000, base_monotonic=base_ts, duration_ms=200_000, playing=False
        )
        assert progress == 45_000

    def test_seek_fraction(self):
        assert sl_ui.seek_fraction(0, 200_000) == 0.0
        assert sl_ui.seek_fraction(100_000, 200_000) == 0.5
        assert sl_ui.seek_fraction(300_000, 200_000) == 1.0
        assert sl_ui.seek_fraction(100, 0) == 0.0

    def test_home_sections_skip_empty_and_order(self):
        track = sl_models.parse_track(_track())
        album = sl_models.parse_album(_album())
        playlist = sl_models.parse_playlist(
            {
                "id": "p1",
                "name": "Chill",
                "uri": "spotify:playlist:p1",
                "images": [],
                "owner": {"display_name": "Alec"},
                "tracks": {"total": 42},
            }
        )
        sections = sl_ui.build_home_sections(
            top_tracks=[track], new_releases=[album], playlists=[playlist], top_artists=[]
        )
        titles = [s.title for s in sections]
        assert "Top tracks" in titles
        assert "New releases" in titles
        assert "Your playlists" in titles
        assert len(sections) == 3  # empty artists section skipped
        cards = sections[0].cards
        assert cards[0].title == "Track"
        assert cards[0].context_uri == "spotify:track:t1"

    def test_track_rows_format(self):
        tracks = [sl_models.parse_track(_track("One", "t1")), sl_models.parse_track(_track("Two", "t2"))]
        rows = sl_ui.build_track_rows(tracks)
        assert rows[0].index == 1
        assert rows[0].title == "One"
        assert rows[0].artists == "Artist"
        assert rows[0].duration == "3:20"
        assert rows[1].index == 2


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

class TestStore:
    def test_config_dir_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFY_LIGHT_CONFIG_DIR", str(tmp_path / "cfg"))
        assert sl_store.config_dir() == tmp_path / "cfg"

    def test_config_dir_defaults_under_home(self, monkeypatch):
        monkeypatch.delenv("SPOTIFY_LIGHT_CONFIG_DIR", raising=False)
        path = sl_store.config_dir()
        assert path.name == "spotify-light"
        assert path.parent.name == ".config"

    def test_client_id_roundtrip(self, tmp_path):
        assert sl_store.load_client_id(tmp_path) is None
        sl_store.save_client_id(tmp_path, "cid-123")
        assert sl_store.load_client_id(tmp_path) == "cid-123"

    def test_tokens_roundtrip_with_owner_only_perms(self, tmp_path):
        tokens = sl_oauth.parse_token_response(
            json.dumps({"access_token": "tok", "refresh_token": "r", "expires_in": 3600}),
            now=1_000.0,
        )
        sl_store.save_tokens(tmp_path, tokens)
        loaded = sl_store.load_tokens(tmp_path)
        assert loaded == tokens
        mode = (tmp_path / "tokens.json").stat().st_mode & 0o777
        assert mode == 0o600, f"token file must be owner-only, got {oct(mode)}"

    def test_clear_tokens_removes_file(self, tmp_path):
        tokens = sl_oauth.parse_token_response(
            json.dumps({"access_token": "tok", "expires_in": 3600}), now=0.0
        )
        sl_store.save_tokens(tmp_path, tokens)
        sl_store.clear_tokens(tmp_path)
        assert sl_store.load_tokens(tmp_path) is None

    def test_corrupt_tokens_load_as_none(self, tmp_path):
        (tmp_path / "tokens.json").write_text("not json", encoding="utf-8")
        assert sl_store.load_tokens(tmp_path) is None


# --------------------------------------------------------------------------
# Album art cache
# --------------------------------------------------------------------------

def _png_bytes(width=300, height=300, color=(200, 30, 30, 255)):
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class TestArtCache:
    def test_fetch_decodes_and_resizes_to_target(self, tmp_path):
        cache = sl_art.ArtCache(tmp_path)
        rgba = cache.fetch("https://i.scdn.co/image/abc", 64, http_get=lambda url: _png_bytes())
        assert rgba.shape == (64, 64, 4)
        assert int(rgba[0, 0, 0]) == 200  # red channel preserved

    def test_fetch_caches_in_memory(self, tmp_path):
        cache = sl_art.ArtCache(tmp_path)
        calls = []

        def http_get(url):
            calls.append(url)
            return _png_bytes()

        cache.fetch("https://i.scdn.co/image/abc", 64, http_get=http_get)
        cache.fetch("https://i.scdn.co/image/abc", 64, http_get=http_get)
        assert calls == ["https://i.scdn.co/image/abc"]

    def test_fetch_persists_to_disk_cache(self, tmp_path):
        first = sl_art.ArtCache(tmp_path)
        first.fetch("https://i.scdn.co/image/abc", 64, http_get=lambda url: _png_bytes())
        second = sl_art.ArtCache(tmp_path)

        def fail_get(url):  # pragma: no cover - must not be called
            raise AssertionError("disk cache miss")

        rgba = second.fetch("https://i.scdn.co/image/abc", 64, http_get=fail_get)
        assert rgba.shape == (64, 64, 4)

    def test_placeholder_is_deterministic_per_seed(self, tmp_path):
        cache = sl_art.ArtCache(tmp_path)
        a = cache.placeholder("Chill", 64)
        b = cache.placeholder("Chill", 64)
        c = cache.placeholder("Other", 64)
        assert a.shape == (64, 64, 4)
        assert (a == b).all()
        assert not (a == c).all()

    def test_bad_payload_raises(self, tmp_path):
        cache = sl_art.ArtCache(tmp_path)
        with pytest.raises(sl_art.ArtError):
            cache.fetch("https://bad", 64, http_get=lambda url: b"not an image")


class TestRoundedArt:
    """Round 28 (Alec): the pill's square album art sits flush at the pill's
    left cap, so its corners cross the rounded silhouette. The thumb is
    alpha-clipped to the same rounded tile the idle state draws."""

    def test_rounded_rgba_clips_corners_keeps_centre(self):
        import numpy as np

        rgba = np.full((44, 44, 4), (10, 20, 30, 255), dtype=np.uint8)
        out = sl_art.rounded_rgba(rgba, 8.0)
        assert out.shape == rgba.shape
        assert int(out[0, 0, 3]) == 0 and int(out[0, 43, 3]) == 0
        assert int(out[43, 0, 3]) == 0 and int(out[43, 43, 3]) == 0
        assert int(out[22, 22, 3]) == 255, "centre stays opaque"
        assert int(out[0, 22, 3]) == 255, "mid-edge stays opaque"
        partial = (out[:, :, 3] > 0) & (out[:, :, 3] < 255)
        assert partial.any(), "the arc needs supersampled partial-alpha pixels, not a hard step"
        assert int(rgba[0, 0, 3]) == 255, "the source (often a cache entry) stays untouched"

    def test_rounded_rgba_radius_scales_with_buffer(self):
        """Retina art buffers are device-pixel sized (88px for a 44pt thumb);
        the caller passes radius in buffer pixels and the same corner fraction
        is clipped."""
        import numpy as np

        rgba = np.full((88, 88, 4), (10, 20, 30, 255), dtype=np.uint8)
        out = sl_art.rounded_rgba(rgba, 16.0)
        assert int(out[0, 0, 3]) == 0
        assert int(out[44, 44, 3]) == 255
        # At half the corner radius from the corner the arc still clips.
        assert int(out[2, 2, 3]) == 0

    def test_masked_is_cached_per_key_and_radius(self, tmp_path):
        cache = sl_art.ArtCache(tmp_path)
        rgba = cache.placeholder("Chill", 44)
        a = cache.masked(rgba, 8.0, key="url-a")
        b = cache.masked(rgba, 8.0, key="url-a")
        assert a is b, "masked variants must hit the memory cache"
        assert int(a[0, 0, 3]) == 0
        c = cache.masked(rgba, 12.0, key="url-a")
        assert c is not a, "radius is part of the cache key"
        # The square original is still intact for other consumers.
        assert int(cache.placeholder("Chill", 44)[0, 0, 3]) == 255


# --------------------------------------------------------------------------
# Background worker
# --------------------------------------------------------------------------

class TestWorker:
    def test_results_arrive_in_submission_order(self):
        worker = sl_worker.Worker()
        try:
            worker.submit("a", lambda: 1)
            worker.submit("b", lambda: 2)
            deadline = time.monotonic() + 5.0
            seen = []
            while len(seen) < 2 and time.monotonic() < deadline:
                seen.extend(worker.poll())
                time.sleep(0.01)
            assert [label for label, _ in seen] == ["a", "b"]
            assert [value for _, value in seen] == [1, 2]
        finally:
            worker.shutdown()

    def test_exceptions_are_captured_not_raised(self):
        worker = sl_worker.Worker()
        try:
            def boom():
                raise RuntimeError("kaput")

            worker.submit("bad", boom)
            deadline = time.monotonic() + 5.0
            seen = []
            while not seen and time.monotonic() < deadline:
                seen.extend(worker.poll())
                time.sleep(0.01)
            label, outcome = seen[0]
            assert label == "bad"
            assert isinstance(outcome, Exception)
            assert "kaput" in str(outcome)
        finally:
            worker.shutdown()
