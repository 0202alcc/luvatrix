"""Spotify Web API client: browse, search, library, and Connect playback control.

The client is synchronous by design and always runs on the app's worker
thread, never on the render loop. The HTTP transport is an injectable object
with `request(method, url, *, token, payload=None) -> (status, json_body)`,
so tests need no network. All requests carry the user's access token; token
refresh is the caller's responsibility (see `token_provider`).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from enum import Enum
from typing import Callable

import sl_models

API_BASE = "https://api.spotify.com/v1"


class ErrorKind(Enum):
    UNAUTHORIZED = "unauthorized"
    PREMIUM_REQUIRED = "premium_required"
    DEVICE_NOT_FOUND = "device_not_found"
    API = "api"
    NETWORK = "network"


class ApiError(Exception):
    def __init__(self, kind: ErrorKind, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


def _extract_error_message(body: object, fallback: str) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error, str):
            return error
    return fallback


def classify_error(status: int, body: object) -> ApiError:
    message = _extract_error_message(body, f"Spotify request failed ({status})")
    lowered = message.lower()
    if status == 401:
        return ApiError(ErrorKind.UNAUTHORIZED, message, status)
    if status == 403 and ("premium" in lowered or "restricted" in lowered):
        return ApiError(ErrorKind.PREMIUM_REQUIRED, message, status)
    if status == 404:
        return ApiError(ErrorKind.DEVICE_NOT_FOUND, message, status)
    return ApiError(ErrorKind.API, f"{status}: {message}", status)


def search_url(query: str, types, *, limit: int = 10, offset: int = 0) -> str:
    params = {
        "q": query,
        "type": ",".join(types),
        "limit": str(int(limit)),
        "offset": str(int(offset)),
    }
    return f"{API_BASE}/search?{urllib.parse.urlencode(params)}"


def _with_device(url: str, device_id: str | None) -> str:
    if not device_id:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}device_id={urllib.parse.quote(device_id)}"


class _UrllibHttp:
    """Default transport: urllib with bearer auth and JSON bodies."""

    def request(self, method: str, url: str, *, token: str, payload: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
                return response.status, _safe_json(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, _safe_json(body)
        except OSError as exc:
            raise ApiError(ErrorKind.NETWORK, f"network error: {exc}") from exc


def _safe_json(body: str):
    try:
        return json.loads(body) if body else None
    except json.JSONDecodeError:
        return None


class SpotifyClient:
    def __init__(self, *, token_provider: Callable[[], str], http=None) -> None:
        self._token_provider = token_provider
        self._http = http or _UrllibHttp()

    def _request(self, method: str, url: str, payload: dict | None = None):
        token = self._token_provider()
        status, body = self._http.request(method, url, token=token, payload=payload)
        if status == 204 or status == 304:
            return None
        if status >= 400:
            raise classify_error(status, body)
        return body

    # -- user / library ----------------------------------------------------

    def me(self) -> sl_models.Profile:
        return sl_models.parse_profile(self._request("GET", f"{API_BASE}/me"))

    def my_playlists(self, *, limit: int = 50) -> list[sl_models.Playlist]:
        playlists: list[sl_models.Playlist] = []
        offset = 0
        while True:
            body = self._request("GET", f"{API_BASE}/me/playlists?limit={limit}&offset={offset}")
            page, has_more = sl_models.parse_playlists_page(body or {})
            playlists.extend(page)
            if not has_more or len(page) == 0:
                return playlists
            offset += len(page)

    def playlist_tracks(self, playlist_id: str, *, limit: int = 100) -> list[sl_models.Track]:
        tracks: list[sl_models.Track] = []
        offset = 0
        while True:
            body = self._request(
                "GET",
                f"{API_BASE}/playlists/{urllib.parse.quote(playlist_id)}/tracks?limit={limit}&offset={offset}",
            )
            page, has_more = sl_models.parse_playlist_tracks_page(body or {})
            tracks.extend(page)
            if not has_more or len(page) == 0:
                return tracks
            offset += len(page)

    def new_releases(self, *, limit: int = 20) -> list[sl_models.Album]:
        body = self._request("GET", f"{API_BASE}/browse/new-releases?limit={limit}")
        albums, _ = sl_models.parse_albums_page_items(body or {})
        return albums

    def top_artists(self, *, limit: int = 20) -> list[sl_models.Artist]:
        body = self._request("GET", f"{API_BASE}/me/top/artists?limit={limit}&time_range=medium_term")
        items = (body or {}).get("items")
        if not isinstance(items, list):
            return []
        return [sl_models.parse_artist(i) for i in items if isinstance(i, dict) and i.get("id")]

    def top_tracks(self, *, limit: int = 20) -> list[sl_models.Track]:
        body = self._request("GET", f"{API_BASE}/me/top/tracks?limit={limit}&time_range=medium_term")
        items = (body or {}).get("items")
        if not isinstance(items, list):
            return []
        return [t for t in (sl_models.parse_track_or_none(i) for i in items) if t is not None]

    def search(self, query: str, *, types=("track", "album", "artist", "playlist"), limit: int = 10):
        url = search_url(query, types, limit=limit)
        return sl_models.parse_search_results(self._request("GET", url) or {})

    # -- playback (Spotify Connect) -----------------------------------------

    def player_state(self) -> sl_models.PlayerState | None:
        body = self._request("GET", f"{API_BASE}/me/player?additional_types=track")
        if body is None:
            return None
        return sl_models.parse_player_state(body)

    def devices(self) -> list[sl_models.Device]:
        body = self._request("GET", f"{API_BASE}/me/player/devices")
        devices = (body or {}).get("devices")
        if not isinstance(devices, list):
            return []
        return [sl_models.parse_device(d) for d in devices if isinstance(d, dict)]

    def play(
        self,
        *,
        context_uri: str | None = None,
        uris: list[str] | None = None,
        offset_uri: str | None = None,
        position_ms: int | None = None,
        device_id: str | None = None,
    ) -> None:
        payload: dict = {}
        if context_uri is not None:
            payload["context_uri"] = context_uri
        if uris is not None:
            payload["uris"] = list(uris)
        if offset_uri is not None:
            payload["offset"] = {"uri": offset_uri}
        if position_ms is not None:
            payload["position_ms"] = int(position_ms)
        self._request("PUT", _with_device(f"{API_BASE}/me/player/play", device_id), payload or None)

    def pause(self, *, device_id: str | None = None) -> None:
        self._request("PUT", _with_device(f"{API_BASE}/me/player/pause", device_id))

    def next_track(self, *, device_id: str | None = None) -> None:
        self._request("POST", _with_device(f"{API_BASE}/me/player/next", device_id))

    def previous_track(self, *, device_id: str | None = None) -> None:
        self._request("POST", _with_device(f"{API_BASE}/me/player/previous", device_id))

    def seek(self, position_ms: int, *, device_id: str | None = None) -> None:
        url = f"{API_BASE}/me/player/seek?position_ms={int(position_ms)}"
        self._request("PUT", _with_device(url, device_id))

    def set_volume(self, percent: int, *, device_id: str | None = None) -> None:
        clamped = max(0, min(100, int(percent)))
        url = f"{API_BASE}/me/player/volume?volume_percent={clamped}"
        self._request("PUT", _with_device(url, device_id))

    def set_shuffle(self, enabled: bool, *, device_id: str | None = None) -> None:
        url = f"{API_BASE}/me/player/shuffle?state={'true' if enabled else 'false'}"
        self._request("PUT", _with_device(url, device_id))

    def set_repeat(self, mode: str, *, device_id: str | None = None) -> None:
        if mode not in ("off", "context", "track"):
            raise ValueError(f"invalid repeat mode: {mode}")
        self._request("PUT", _with_device(f"{API_BASE}/me/player/repeat?state={mode}", device_id))

    def transfer(self, device_id: str, *, play: bool = True) -> None:
        self._request("PUT", f"{API_BASE}/me/player", {"device_ids": [device_id], "play": bool(play)})
