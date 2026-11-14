"""Read-only CalDAV event reader.

Reads events from explicitly configured calendar collection URLs. The reader
exposes no create, update, save, or delete operation.
"""

import os
import threading
import time
from collections.abc import Callable, Mapping, MutableMapping
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any, cast

import caldav

from stempelwerk.config import CalDAVCalendarConfig
from stempelwerk.domain import CalDAVEvent

ClientFactory = Callable[..., Any]
CacheKey = tuple[str, str, str, str]
CacheEntry = tuple[list["CalDAVEvent"], float]
Cache = MutableMapping[CacheKey, CacheEntry]

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_CACHE_SECONDS = 60
UNTITLED_EVENT = "Untitled event"

# Module-level cache shared by every reader instance that does not inject its
# own mapping. API routes create a new reader per request, so the default cache
# must outlive a single reader.
_CACHE: Cache = {}
_CACHE_LOCK = threading.Lock()


class CalDAVReaderError(RuntimeError):
    """Base error for CalDAV reading failures."""


class MissingCalDAVCredentialsError(CalDAVReaderError):
    """Raised when a configured credential environment variable is unset.

    The message names the calendar and the environment variable names, but
    never contains a credential value.
    """


class UnknownCalDAVCalendarError(CalDAVReaderError):
    """Raised when an event read is requested for an unconfigured calendar id."""


class CalDAVReader:
    """Read events from configured CalDAV calendar collections.

    Dependencies are injected for testability: the environment mapping and the
    client factory can be replaced so unit tests never touch a network
    service.
    """

    def __init__(
        self,
        calendars: list[CalDAVCalendarConfig],
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        env: Mapping[str, str] | None = None,
        client_factory: ClientFactory | None = None,
        cache_seconds: int = DEFAULT_CACHE_SECONDS,
        clock: Callable[[], float] | None = None,
        cache: Cache | None = None,
    ) -> None:
        self._calendars = {calendar.id: calendar for calendar in calendars}
        self._timeout_seconds = timeout_seconds
        self._env = os.environ if env is None else env
        self._client_factory = (
            client_factory if client_factory is not None else cast(ClientFactory, caldav.DAVClient)
        )
        self._cache_seconds = cache_seconds
        self._clock = time.monotonic if clock is None else clock
        self._cache: Cache = _CACHE if cache is None else cache

    def read_events(
        self,
        calendar_id: str,
        start: datetime,
        end: datetime,
        *,
        refresh: bool = False,
    ) -> list[CalDAVEvent]:
        """Return the events of one configured calendar in the given range."""
        config = self._calendars.get(calendar_id)
        if config is None:
            raise UnknownCalDAVCalendarError(f"Unknown CalDAV calendar id: {calendar_id}")

        key = (calendar_id, config.url, start.isoformat(), end.isoformat())
        if not refresh:
            cached = self._cached_events(key)
            if cached is not None:
                return cached

        events = self._query_events(config, start, end)

        if self._cache_seconds > 0:
            with _CACHE_LOCK:
                self._cache[key] = (list(events), self._clock())
        return list(events)

    def _cached_events(self, key: CacheKey) -> list[CalDAVEvent] | None:
        """Return a copy of an unexpired cached list, or None on a miss."""
        if self._cache_seconds <= 0:
            return None
        with _CACHE_LOCK:
            entry = self._cache.get(key)
            if entry is None:
                return None
            events, stored_at = entry
            if self._clock() - stored_at >= self._cache_seconds:
                del self._cache[key]
                return None
            return list(events)

    def _query_events(
        self,
        config: CalDAVCalendarConfig,
        start: datetime,
        end: datetime,
    ) -> list[CalDAVEvent]:
        """Run the CalDAV query without holding the cache lock."""
        username, password = self._resolve_credentials(config)

        client = self._client_factory(
            url=config.url,
            username=username,
            password=password,
            timeout=self._timeout_seconds,
            ssl_verify_cert=True,
            require_tls=True,
        )
        with client:
            calendar = client.calendar(url=config.url)
            found = calendar.search(start=start, end=end, event=True, expand=True)

        events = [
            event
            for object_resource in found
            if (event := self._to_event(config, object_resource)) is not None
        ]
        # ISO strings keep the sort deterministic without comparing date and
        # datetime objects directly, which raises TypeError.
        events.sort(key=lambda event: (event.start.isoformat(), event.end.isoformat(), event.id))
        return events

    def _resolve_credentials(self, config: CalDAVCalendarConfig) -> tuple[str, str]:
        missing = [
            variable
            for variable in (config.username_env, config.password_env)
            if not self._env.get(variable)
        ]
        if missing:
            raise MissingCalDAVCredentialsError(
                f"CalDAV calendar '{config.id}' requires credential environment "
                f"variable(s) that are unset: {', '.join(missing)}"
            )
        return self._env[config.username_env], self._env[config.password_env]

    def _to_event(
        self,
        config: CalDAVCalendarConfig,
        object_resource: Any,
    ) -> CalDAVEvent | None:
        component = object_resource.get_icalendar_component()
        if component is None:
            return None

        status = _text(component, "STATUS")
        if status is not None and status.strip().upper() == "CANCELLED":
            return None

        raw_start = component.decoded("DTSTART", None)
        if not isinstance(raw_start, (date, datetime)):
            return None

        return CalDAVEvent(
            id=_event_id(
                config.id,
                _uid(component, object_resource),
                _occurrence_key(component, raw_start),
            ),
            calendar_id=config.id,
            calendar_name=config.name,
            title=_title(component),
            start=raw_start,
            end=_end_value(component, raw_start),
            all_day=not isinstance(raw_start, datetime),
            location=_location(component),
            editable=False,
        )


def _text(component: Any, name: str) -> str | None:
    """Return a text property value converted to str, or None when absent."""
    value = component.get(name)
    return None if value is None else str(value)


def _title(component: Any) -> str:
    summary = _text(component, "SUMMARY")
    if summary is None or not summary.strip():
        return UNTITLED_EVENT
    return summary


def _location(component: Any) -> str | None:
    location = _text(component, "LOCATION")
    if location is None or not location.strip():
        return None
    return location


def _uid(component: Any, object_resource: Any) -> str:
    """Return the event UID, falling back to the resource URL when absent."""
    uid = _text(component, "UID")
    if uid is not None and uid.strip():
        return uid
    url = getattr(object_resource, "url", None)
    return "" if url is None else str(url)


def _end_value(component: Any, raw_start: date | datetime) -> date | datetime:
    raw_end = component.decoded("DTEND", None)
    if isinstance(raw_end, (date, datetime)):
        return raw_end
    duration = component.decoded("DURATION", None)
    if isinstance(duration, timedelta):
        return raw_start + duration
    if isinstance(raw_start, datetime):
        return raw_start
    # A date-only event without an end covers one full day so FullCalendar
    # renders it as a single-day event.
    return raw_start + timedelta(days=1)


def _occurrence_key(component: Any, start: date | datetime) -> str:
    recurrence_id = component.decoded("RECURRENCE-ID", None)
    if isinstance(recurrence_id, (date, datetime)):
        return recurrence_id.isoformat()
    return start.isoformat()


def _event_id(calendar_id: str, uid: str, occurrence_key: str) -> str:
    source = f"{calendar_id}\0{uid}\0{occurrence_key}".encode()
    return f"caldav:{calendar_id}:{sha256(source).hexdigest()}"
