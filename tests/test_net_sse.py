from __future__ import annotations

import pytest

from luvatrix.net import ApiError, Event, HttpRequest, SseParser, stream_events


def _feed_all(*chunks: bytes) -> list[Event]:
    parser = SseParser()
    events: list[Event] = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.close())
    return events


def test_single_data_line_dispatches_message_event() -> None:
    events = _feed_all(b"data: hello\n\n")

    assert events == [Event(event=None, data="hello", id=None, retry=None)]


def test_multi_line_data_is_joined_with_newlines() -> None:
    events = _feed_all(b"data: line one\ndata: line two\n\n")

    assert [event.data for event in events] == ["line one\nline two"]


def test_named_event_carries_id_and_retry() -> None:
    events = _feed_all(b"event: delta\nid: 42\nretry: 1500\ndata: x\n\n")

    assert events == [Event(event="delta", data="x", id="42", retry=1500)]


def test_comment_lines_are_ignored() -> None:
    events = _feed_all(b": keep-alive\n\ndata: real\n\n")

    assert [event.data for event in events] == ["real"]


def test_crlf_and_cr_line_endings_are_accepted() -> None:
    assert [e.data for e in _feed_all(b"data: a\r\n\r\n")] == ["a"]
    assert [e.data for e in _feed_all(b"data: b\r\r")] == ["b"]
    assert [e.data for e in _feed_all(b"data: c\ndata: d\r\n\r\n")] == ["c\nd"]


def test_events_split_across_feeds() -> None:
    parser = SseParser()
    assert parser.feed(b"data: hel") == []
    assert parser.feed(b"lo\n") == []
    events = parser.feed(b"\n")

    assert [event.data for event in events] == ["hello"]


def test_cr_at_chunk_boundary_waits_for_possible_lf() -> None:
    parser = SseParser()
    assert parser.feed(b"data: a\r") == []
    events = parser.feed(b"\n\n")

    assert [event.data for event in events] == ["a"]


def test_event_without_data_is_not_dispatched() -> None:
    assert _feed_all(b"event: ping\n\n") == []


def test_field_without_colon_uses_empty_value() -> None:
    events = _feed_all(b"data\n\n")

    assert [event.data for event in events] == [""]


def test_last_event_id_persists_until_changed() -> None:
    events = _feed_all(b"id: 7\ndata: a\n\ndata: b\n\nid: \ndata: c\n\n")

    assert [(event.data, event.id) for event in events] == [("a", "7"), ("b", "7"), ("c", None)]


def test_non_digit_retry_is_ignored() -> None:
    events = _feed_all(b"retry: soon\ndata: x\n\n")

    assert [event.retry for event in events] == [None]


def test_close_flushes_trailing_event_without_blank_line() -> None:
    parser = SseParser()
    assert parser.feed(b"data: tail\n") == []

    events = parser.close()

    assert [event.data for event in events] == ["tail"]


def test_close_without_pending_data_dispatches_nothing() -> None:
    parser = SseParser()
    parser.feed(b"data: done\n\n")

    assert parser.close() == []


def test_utf8_data_is_decoded() -> None:
    events = _feed_all("data: héllo ✓\n\n".encode("utf-8"))

    assert [event.data for event in events] == ["héllo ✓"]


class FakeStream:
    def __init__(self, status: int, chunks: list[bytes]) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self._chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FakeStreamingTransport:
    def __init__(self, status: int, chunks: list[bytes]) -> None:
        self.requests: list[HttpRequest] = []
        self._stream = FakeStream(status, chunks)

    def stream(self, request: HttpRequest, *, timeout: float | None = None) -> FakeStream:
        self.requests.append(request)
        return self._stream


def test_stream_events_sends_last_event_id_and_yields_events() -> None:
    transport = FakeStreamingTransport(200, [b"data: a\n\n", b"data: b\n", b"\n"])
    request = HttpRequest(method="GET", url="https://tenant.example.com/api/v0/agents/1/watch")

    events = list(stream_events(transport, request, last_event_id="99"))

    assert [event.data for event in events] == ["a", "b"]
    sent = transport.requests[0]
    assert sent.headers["Last-Event-ID"] == "99"
    assert sent.headers["Accept"] == "text/event-stream"


def test_stream_events_raises_api_error_for_error_status() -> None:
    transport = FakeStreamingTransport(500, [b'{"error": "boom"}'])
    request = HttpRequest(method="GET", url="https://tenant.example.com/x")

    with pytest.raises(ApiError) as caught:
        list(stream_events(transport, request))

    assert caught.value.status == 500
    assert caught.value.body == b'{"error": "boom"}'
