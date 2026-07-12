from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from luvatrix.auth import (
    GoogleCalendarClient,
    GoogleCalendarError,
    GoogleOAuthClient,
    GoogleOAuthConfig,
    GoogleOAuthToken,
    InMemoryTokenStore,
)


def _oauth_client(*, expired=False, post_form=None):
    store = InMemoryTokenStore()
    store.save(
        GoogleOAuthToken(
            "old-access",
            "Bearer",
            expires_at=0.0 if expired else 10_000.0,
            refresh_token="refresh-token",
        )
    )
    return GoogleOAuthClient(
        GoogleOAuthConfig("client", "app:/oauth", ("calendar.readonly",)),
        token_store=store,
        post_form=post_form,
        clock=lambda: 100.0,
    )


def test_list_calendars_paginates_and_preserves_selection_metadata():
    requests = []
    responses = iter(
        (
            {
                "items": [
                    {"id": "primary@example.com", "summary": "Primary", "primary": True},
                ],
                "nextPageToken": "page-two",
            },
            {
                "items": [
                    {"id": "team@example.com", "summary": "Team", "selected": True},
                ]
            },
        )
    )

    def get_json(request):
        requests.append(request)
        return next(responses)

    calendars = GoogleCalendarClient(_oauth_client(), get_json=get_json).list_calendars()

    assert [calendar.calendar_id for calendar in calendars] == [
        "primary@example.com",
        "team@example.com",
    ]
    assert calendars[0].primary is True
    assert calendars[1].selected is True
    assert requests[0].get_header("Authorization") == "Bearer old-access"
    assert parse_qs(urlparse(requests[1].full_url).query)["pageToken"] == ["page-two"]


def test_list_events_expands_recurring_instances_and_paginates():
    requests = []
    responses = iter(
        (
            {"items": [{"id": "one", "summary": "One"}], "nextPageToken": "next"},
            {"items": [{"id": "two", "summary": "Two"}]},
        )
    )

    def get_json(request):
        requests.append(request)
        return next(responses)

    start = datetime(2026, 7, 8, tzinfo=timezone(timedelta(hours=-4)))
    end = start + timedelta(days=1)
    events = GoogleCalendarClient(_oauth_client(), get_json=get_json).list_events(
        "primary@example.com",
        time_min=start,
        time_max=end,
    )

    assert [event.event_id for event in events] == ["one", "two"]
    query = parse_qs(urlparse(requests[0].full_url).query)
    assert query["singleEvents"] == ["true"]
    assert query["orderBy"] == ["startTime"]
    assert query["timeMin"] == [start.isoformat()]
    assert query["timeMax"] == [end.isoformat()]
    assert parse_qs(urlparse(requests[1].full_url).query)["pageToken"] == ["next"]


def test_request_refreshes_once_after_unauthorized_response():
    requests = []
    refresh_payloads = []

    def post_form(url, payload):
        refresh_payloads.append(payload)
        return {"access_token": "new-access", "expires_in": 3600}

    def get_json(request):
        requests.append(request)
        if len(requests) == 1:
            raise GoogleCalendarError("expired", status_code=401)
        return {"items": []}

    client = GoogleCalendarClient(
        _oauth_client(post_form=post_form),
        get_json=get_json,
    )
    client.list_calendars()

    assert len(refresh_payloads) == 1
    assert requests[1].get_header("Authorization") == "Bearer new-access"


def test_events_in_window_uses_selected_calendars_and_ttl_cache():
    requests = []
    now = [100.0]

    def get_json(request):
        requests.append(request)
        if "/calendarList" in request.full_url:
            return {
                "items": [
                    {"id": "primary", "primary": True},
                    {"id": "selected", "selected": True},
                    {"id": "hidden", "selected": True, "hidden": True},
                    {"id": "off", "selected": False},
                ]
            }
        calendar_id = request.full_url.split("/calendars/", 1)[1].split("/events", 1)[0]
        return {"items": [{"id": f"event-{calendar_id}", "summary": calendar_id}]}

    start = datetime(2026, 7, 8, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    client = GoogleCalendarClient(
        _oauth_client(),
        get_json=get_json,
        clock=lambda: now[0],
        cache_ttl_seconds=300,
    )

    first = client.events_in_window(time_min=start, time_max=end)
    second = client.events_in_window(time_min=start, time_max=end)

    assert [event.calendar_id for event in first] == ["primary", "selected"]
    assert second is first
    assert len(requests) == 3


def test_events_in_window_rejects_inverted_range():
    client = GoogleCalendarClient(_oauth_client(), get_json=lambda request: {"items": []})
    instant = datetime(2026, 7, 8, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="time_max"):
        client.events_in_window(time_min=instant, time_max=instant)
