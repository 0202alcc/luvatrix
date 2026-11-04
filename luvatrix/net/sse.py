"""Incremental Server-Sent Events parser plus a transport streaming helper.

Follows the WHATWG event-stream rules: `data` fields join with newlines,
lines starting with `:` are comments, and \\n, \\r\\n, and lone \\r all
terminate lines. `feed()` accepts arbitrary byte splits, including a CR that
lands at a chunk boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator

from .client import ApiError
from .transport import HttpRequest, Transport

_LF = 0x0A
_CR = 0x0D


@dataclass(frozen=True)
class Event:
    """One dispatched server-sent event.

    `event` is None for an unnamed event (the spec's default "message" type).
    `id` is the last event-ID seen at dispatch time, or None when the stream
    never sent one (or reset it with an empty `id:` field).
    """

    event: str | None
    data: str
    id: str | None = None
    retry: int | None = None


class SseParser:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self._data_parts: list[str] = []
        self._event_name: str | None = None
        self._last_id: str | None = None
        self._retry: int | None = None

    def feed(self, data: bytes) -> list[Event]:
        self._buffer.extend(data)
        events: list[Event] = []
        for line in self._take_lines():
            event = self._process_line(line)
            if event is not None:
                events.append(event)
        return events

    def close(self) -> list[Event]:
        """Flush anything still buffered at end-of-stream."""
        events: list[Event] = []
        if self._buffer:
            line = bytes(self._buffer)
            self._buffer.clear()
            event = self._process_line(line)
            if event is not None:
                events.append(event)
        event = self._dispatch()
        if event is not None:
            events.append(event)
        return events

    def _take_lines(self) -> list[bytes]:
        lines: list[bytes] = []
        buffer = self._buffer
        start = 0
        i = 0
        end = len(buffer)
        while i < end:
            byte = buffer[i]
            if byte == _LF:
                lines.append(bytes(buffer[start:i]))
                i += 1
                start = i
            elif byte == _CR:
                if i + 1 == end:
                    # Might be the first half of a CRLF split across feeds.
                    break
                lines.append(bytes(buffer[start:i]))
                i += 2 if buffer[i + 1] == _LF else 1
                start = i
            else:
                i += 1
        del buffer[:start]
        return lines

    def _process_line(self, line: bytes) -> Event | None:
        text = line.decode("utf-8", errors="replace")
        if not text:
            return self._dispatch()
        if text.startswith(":"):
            return None
        field, separator, value = text.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            self._data_parts.append(value)
        elif field == "event":
            self._event_name = value
        elif field == "id":
            if "\x00" not in value:
                self._last_id = value or None
        elif field == "retry":
            if value.isdigit():
                self._retry = int(value)
        # Unknown fields are ignored, per spec.
        return None

    def _dispatch(self) -> Event | None:
        if not self._data_parts:
            self._event_name = None
            return None
        event = Event(
            event=self._event_name,
            data="\n".join(self._data_parts),
            id=self._last_id,
            retry=self._retry,
        )
        self._data_parts = []
        self._event_name = None
        return event


def stream_events(
    transport: Transport,
    request: HttpRequest,
    *,
    last_event_id: str | None = None,
    timeout: float | None = None,
) -> Iterator[Event]:
    """Open `request` as an event stream and yield events as they arrive.

    Sends `Accept: text/event-stream` and, when given, `Last-Event-ID` for
    resumption. Error statuses raise `ApiError` with the buffered body.
    """
    headers = {"Accept": "text/event-stream", **request.headers}
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id
    with transport.stream(replace(request, headers=headers), timeout=timeout) as stream:
        if stream.status >= 400:
            raise ApiError(stream.status, b"".join(stream), url=request.url)
        parser = SseParser()
        for chunk in stream:
            yield from parser.feed(chunk)
        yield from parser.close()
