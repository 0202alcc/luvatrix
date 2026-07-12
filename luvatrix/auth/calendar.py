"""Typed Google Calendar reads built on Luvatrix Google OAuth tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .google import GoogleOAuthClient


GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class GoogleCalendarError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GoogleCalendarListEntry:
    calendar_id: str
    summary: str = ""
    primary: bool = False
    selected: bool = False
    hidden: bool = False
    deleted: bool = False
    background_color: str | None = None
    foreground_color: str | None = None
    time_zone: str | None = None


@dataclass(frozen=True)
class GoogleCalendarEvent:
    event_id: str
    calendar_id: str
    summary: str = ""
    location: str = ""
    status: str = "confirmed"
    start: Mapping[str, object] | None = None
    end: Mapping[str, object] | None = None
    color_id: str | None = None
    html_link: str | None = None


JsonGet = Callable[[Request], Mapping[str, object]]


class GoogleCalendarClient:
    """Read selected Google calendars and cache bounded event windows."""

    def __init__(
        self,
        oauth_client: GoogleOAuthClient,
        *,
        get_json: JsonGet | None = None,
        clock: Callable[[], float] = time.monotonic,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self.oauth_client = oauth_client
        self._get_json = get_json or _get_json
        self._clock = clock
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._window_cache: dict[tuple[str, str, bool], tuple[float, tuple[GoogleCalendarEvent, ...]]] = {}

    def list_calendars(self) -> tuple[GoogleCalendarListEntry, ...]:
        items = self._paginated_get(
            f"{GOOGLE_CALENDAR_API_BASE}/users/me/calendarList",
            {"maxResults": "250"},
        )
        calendars = []
        for item in items:
            calendar_id = str(item.get("id") or "")
            if not calendar_id:
                continue
            calendars.append(
                GoogleCalendarListEntry(
                    calendar_id=calendar_id,
                    summary=str(item.get("summaryOverride") or item.get("summary") or ""),
                    primary=bool(item.get("primary", False)),
                    selected=bool(item.get("selected", False)),
                    hidden=bool(item.get("hidden", False)),
                    deleted=bool(item.get("deleted", False)),
                    background_color=_optional_string(item.get("backgroundColor")),
                    foreground_color=_optional_string(item.get("foregroundColor")),
                    time_zone=_optional_string(item.get("timeZone")),
                )
            )
        return tuple(calendars)

    def list_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
    ) -> tuple[GoogleCalendarEvent, ...]:
        _validate_window(time_min, time_max)
        encoded_calendar_id = quote(str(calendar_id), safe="")
        items = self._paginated_get(
            f"{GOOGLE_CALENDAR_API_BASE}/calendars/{encoded_calendar_id}/events",
            {
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "2500",
            },
        )
        events = []
        for item in items:
            event_id = str(item.get("id") or item.get("iCalUID") or "")
            if not event_id:
                continue
            events.append(
                GoogleCalendarEvent(
                    event_id=event_id,
                    calendar_id=str(calendar_id),
                    summary=str(item.get("summary") or ""),
                    location=str(item.get("location") or ""),
                    status=str(item.get("status") or "confirmed"),
                    start=item.get("start") if isinstance(item.get("start"), Mapping) else None,
                    end=item.get("end") if isinstance(item.get("end"), Mapping) else None,
                    color_id=_optional_string(item.get("colorId")),
                    html_link=_optional_string(item.get("htmlLink")),
                )
            )
        return tuple(events)

    def events_in_window(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        include_unselected: bool = False,
    ) -> tuple[GoogleCalendarEvent, ...]:
        _validate_window(time_min, time_max)
        key = (time_min.isoformat(), time_max.isoformat(), bool(include_unselected))
        cached = self._window_cache.get(key)
        now = self._clock()
        if cached is not None and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        calendars = self.list_calendars()
        visible_calendars = tuple(
            calendar
            for calendar in calendars
            if not calendar.deleted
            and not calendar.hidden
            and (include_unselected or calendar.selected or calendar.primary)
        )
        events = tuple(
            sorted(
                (
                    event
                    for calendar in visible_calendars
                    for event in self.list_events(
                        calendar.calendar_id,
                        time_min=time_min,
                        time_max=time_max,
                    )
                ),
                key=lambda event: (
                    str((event.start or {}).get("dateTime") or (event.start or {}).get("date") or ""),
                    event.calendar_id,
                    event.event_id,
                ),
            )
        )
        self._window_cache[key] = (now, events)
        return events

    def clear_cache(self) -> None:
        self._window_cache.clear()

    def _paginated_get(self, url: str, params: Mapping[str, str]) -> tuple[Mapping[str, object], ...]:
        items = []
        page_token = ""
        seen_tokens = set()
        while True:
            page_params = dict(params)
            if page_token:
                page_params["pageToken"] = page_token
            payload = self._authorized_get(f"{url}?{urlencode(page_params)}")
            page_items = payload.get("items") or []
            if not isinstance(page_items, list):
                raise GoogleCalendarError("Google Calendar returned an invalid items list")
            items.extend(item for item in page_items if isinstance(item, Mapping))
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                return tuple(items)
            if page_token in seen_tokens:
                raise GoogleCalendarError("Google Calendar repeated a pagination token")
            seen_tokens.add(page_token)

    def _authorized_get(self, url: str) -> Mapping[str, object]:
        token = self.oauth_client.current_token(refresh_if_needed=True)
        if token is None:
            raise GoogleCalendarError("no Google OAuth token is available")
        request = _authorized_request(url, token.access_token)
        try:
            return self._get_json(request)
        except GoogleCalendarError as exc:
            if exc.status_code != 401:
                raise
        token = self.oauth_client.refresh(token)
        return self._get_json(_authorized_request(url, token.access_token))


def _authorized_request(url: str, access_token: str) -> Request:
    return Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "Luvatrix/GoogleCalendar",
        },
    )


def _get_json(request: Request) -> Mapping[str, object]:
    try:
        with urlopen(request, timeout=20) as response:
            encoded = response.read(GOOGLE_CALENDAR_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise GoogleCalendarError(
            f"Google Calendar request failed with HTTP {exc.code}",
            status_code=exc.code,
        ) from exc
    except URLError as exc:
        raise GoogleCalendarError(f"Google Calendar network request failed: {exc.reason}") from exc
    if len(encoded) > GOOGLE_CALENDAR_MAX_RESPONSE_BYTES:
        raise GoogleCalendarError("Google Calendar response exceeded 4 MB")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleCalendarError("Google Calendar response was not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise GoogleCalendarError("Google Calendar response was not a JSON object")
    return payload


def _validate_window(time_min: datetime, time_max: datetime) -> None:
    if time_min.tzinfo is None or time_max.tzinfo is None:
        raise ValueError("time_min and time_max must include timezone offsets")
    if time_max <= time_min:
        raise ValueError("time_max must be later than time_min")


def _optional_string(value: object) -> str | None:
    text = str(value or "")
    return text or None
