from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Self
from zoneinfo import ZoneInfo

import icalendar
import pytest
from pydantic import ValidationError

from stempelwerk import caldav_reader
from stempelwerk.caldav_reader import (
    Cache,
    CalDAVReader,
    MissingCalDAVCredentialsError,
    UnknownCalDAVCalendarError,
)
from stempelwerk.config import AppConfig, CalDAVCalendarConfig, load_config
from stempelwerk.domain import CalDAVEvent

ENV = {"U_ENV": "alice", "P_ENV": "s3cret-value"}
CALENDAR_URL = "https://calendar.example.test/dav/personal/"


class FakeResource:
    """Fake CalDAV object resource backed by a real icalendar component."""

    def __init__(self, component: icalendar.Component, url: str) -> None:
        self.url = url
        self._component = component

    def get_icalendar_component(self) -> icalendar.Component:
        return self._component


class FakeCalendar:
    def __init__(self, objects: list[FakeResource]) -> None:
        self.objects = objects
        self.search_calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[FakeResource]:
        self.search_calls.append(kwargs)
        return self.objects


class FakeClient:
    def __init__(
        self,
        calendars: dict[str, list[FakeResource]],
        **kwargs: object,
    ) -> None:
        self.init_kwargs = kwargs
        self.calendars = {url: FakeCalendar(objects) for url, objects in calendars.items()}
        self.calendar_calls: list[str] = []
        self.closed = False

    def calendar(self, url: str) -> FakeCalendar:
        self.calendar_calls.append(url)
        if url not in self.calendars:
            self.calendars[url] = FakeCalendar([])
        return self.calendars[url]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.closed = True


def make_resource(url: str, **properties: object) -> FakeResource:
    """Build a fake resource whose component is parsed by the real icalendar."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Stempelwerk Test//EN", "BEGIN:VEVENT"]
    for name, value in properties.items():
        if value is None:
            continue
        if isinstance(value, tuple):
            params, raw = value
            rendered = "".join(f";{key}={param}" for key, param in params.items())
            lines.append(f"{name}{rendered}:{raw}")
        else:
            lines.append(f"{name}:{value}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    calendar = icalendar.Calendar.from_ical("\r\n".join(lines))
    component = next(iter(calendar.subcomponents))
    return FakeResource(component, url)


def make_reader(
    calendars: list[CalDAVCalendarConfig],
    client: FakeClient,
    env: dict[str, str] | None = None,
    cache_seconds: int = 0,
    clock: Callable[[], float] | None = None,
    cache: Cache | None = None,
) -> CalDAVReader:
    def factory(**kwargs: object) -> FakeClient:
        client.init_kwargs = kwargs
        return client

    return CalDAVReader(
        calendars,
        timeout_seconds=7,
        env=ENV if env is None else env,
        client_factory=factory,
        # Existing tests stay deterministic: no caching unless a cache test
        # explicitly opts in.
        cache_seconds=cache_seconds,
        clock=clock,
        cache=cache,
    )


def make_config(calendar_id: str = "personal") -> CalDAVCalendarConfig:
    return CalDAVCalendarConfig(
        id=calendar_id,
        name="Personal",
        url=f"https://calendar.example.test/dav/{calendar_id}/",
        username_env="U_ENV",
        password_env="P_ENV",
    )


class FakeClock:
    """Deterministic monotonic clock advanced explicitly by tests."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestEventCache:
    @pytest.fixture(autouse=True)
    def clear_shared_cache(self) -> None:
        caldav_reader._CACHE.clear()

    def make_cached_reader(
        self,
        client: FakeClient,
        clock: FakeClock,
        cache_seconds: int = 60,
        cache: Cache | None = None,
    ) -> CalDAVReader:
        return make_reader(
            [make_config()],
            client,
            cache_seconds=cache_seconds,
            clock=clock,
            cache=cache,
        )

    def test_cache_hit_shared_across_reader_instances(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        first = make_reader([make_config()], client, cache_seconds=60, clock=clock)
        second = make_reader([make_config()], client, cache_seconds=60, clock=clock)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        first.read_events("personal", *range_args)
        search_count = len(client.calendars[CALENDAR_URL].search_calls)
        second.read_events("personal", *range_args)

        assert len(client.calendars[CALENDAR_URL].search_calls) == search_count

    def test_expired_entry_is_refreshed_and_removed(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        reader = self.make_cached_reader(client, clock)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        reader.read_events("personal", *range_args)
        clock.advance(60)
        reader.read_events("personal", *range_args)

        assert len(client.calendars[CALENDAR_URL].search_calls) == 2
        # The expired entry was removed and replaced by the fresh result.
        key = ("personal", CALENDAR_URL, "2026-03-01T00:00:00", "2026-04-01T00:00:00")
        assert caldav_reader._CACHE[key][1] == clock.now
        assert list(caldav_reader._CACHE) == [key]

    def test_fresh_entry_stays_cached_after_non_refresh_read(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        reader = self.make_cached_reader(client, clock)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        reader.read_events("personal", *range_args)
        clock.advance(59)
        reader.read_events("personal", *range_args)

        assert len(client.calendars[CALENDAR_URL].search_calls) == 1

    def test_refresh_bypasses_cache_and_replaces_entry(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        reader = self.make_cached_reader(client, clock)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        first = reader.read_events("personal", *range_args)
        clock.advance(1)
        second = reader.read_events("personal", *range_args, refresh=True)

        assert len(client.calendars[CALENDAR_URL].search_calls) == 2
        assert second == first
        key = ("personal", CALENDAR_URL, "2026-03-01T00:00:00", "2026-04-01T00:00:00")
        assert caldav_reader._CACHE[key][1] == clock.now

    def test_zero_cache_seconds_never_reads_or_writes_cache(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        cache: Cache = {}
        reader = make_reader([make_config()], client, cache_seconds=0, clock=clock, cache=cache)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        reader.read_events("personal", *range_args)
        reader.read_events("personal", *range_args)

        assert len(client.calendars[CALENDAR_URL].search_calls) == 2
        assert cache == {}

    def test_different_ranges_are_cached_separately(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        reader = self.make_cached_reader(client, clock)

        reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))
        reader.read_events("personal", datetime(2026, 4, 1), datetime(2026, 5, 1))

        assert len(client.calendars[CALENDAR_URL].search_calls) == 2

    def test_different_calendars_are_cached_separately(self) -> None:
        url_a = "https://calendar.example.test/dav/a/"
        url_b = "https://calendar.example.test/dav/b/"
        client = FakeClient({url_a: [], url_b: []})
        clock = FakeClock()
        reader = make_reader(
            [make_config("a"), make_config("b")],
            client,
            cache_seconds=60,
            clock=clock,
        )
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        reader.read_events("a", *range_args)
        reader.read_events("b", *range_args)

        assert len(client.calendars[url_a].search_calls) == 1
        assert len(client.calendars[url_b].search_calls) == 1

    def test_returned_list_is_a_copy_of_the_cached_list(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        clock = FakeClock()
        reader = self.make_cached_reader(client, clock)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        first = reader.read_events("personal", *range_args)
        first.clear()
        second = reader.read_events("personal", *range_args)

        assert len(second) == 1

    def test_exceptions_are_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = FakeClient({CALENDAR_URL: []})
        clock = FakeClock()
        reader = self.make_cached_reader(client, clock)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        calendar = client.calendars[CALENDAR_URL]

        def failing_search(**kwargs: object) -> list[FakeResource]:
            calendar.search_calls.append(kwargs)
            raise RuntimeError("server unreachable")

        monkeypatch.setattr(calendar, "search", failing_search)
        with pytest.raises(RuntimeError):
            reader.read_events("personal", *range_args)
        assert caldav_reader._CACHE == {}

        def succeeding_search(**kwargs: object) -> list[FakeResource]:
            calendar.search_calls.append(kwargs)
            return []

        monkeypatch.setattr(calendar, "search", succeeding_search)
        events = reader.read_events("personal", *range_args)

        assert events == []
        assert len(calendar.search_calls) == 2


class TestConfigParsing:
    def test_load_config_with_caldav_settings(self, tmp_path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            """
caldav_timeout_seconds = 10
caldav_cache_seconds = 60

[[caldav_calendars]]
id = "personal"
name = "Personal"
url = "https://calendar.example.test/dav/calendars/alice/personal/"
username_env = "PERSONAL_CALDAV_USERNAME"
password_env = "PERSONAL_CALDAV_PASSWORD"
color = "#7c3aed"
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert config.caldav_timeout_seconds == 10
        assert config.caldav_cache_seconds == 60
        calendar = config.caldav_calendars[0]
        assert calendar.id == "personal"
        assert calendar.name == "Personal"
        assert calendar.url == "https://calendar.example.test/dav/calendars/alice/personal/"
        assert calendar.username_env == "PERSONAL_CALDAV_USERNAME"
        assert calendar.password_env == "PERSONAL_CALDAV_PASSWORD"
        assert calendar.color == "#7c3aed"

    def test_caldav_defaults(self) -> None:
        config = AppConfig()

        assert config.caldav_timeout_seconds == 10
        assert config.caldav_cache_seconds == 60
        assert config.caldav_calendars == []

    def test_rejects_invalid_color(self) -> None:
        with pytest.raises(ValidationError):
            CalDAVCalendarConfig(
                id="a",
                name="A",
                url="https://example.test/",
                username_env="U",
                password_env="P",
                color="purple",
            )

    @pytest.mark.parametrize(
        "url",
        [
            "http://calendar.example.test/personal/",
            "https://alice:secret@calendar.example.test/personal/",
        ],
    )
    def test_rejects_insecure_or_credential_bearing_url(self, url: str) -> None:
        with pytest.raises(ValidationError):
            CalDAVCalendarConfig(
                id="a",
                name="A",
                url=url,
                username_env="U",
                password_env="P",
            )

    def test_rejects_nonpositive_timeout(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(caldav_timeout_seconds=0)

    def test_rejects_negative_cache_seconds(self) -> None:
        with pytest.raises(ValidationError):
            AppConfig(caldav_cache_seconds=-1)

    def test_allows_zero_cache_seconds(self) -> None:
        assert AppConfig(caldav_cache_seconds=0).caldav_cache_seconds == 0

    def test_rejects_duplicate_calendar_ids(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate CalDAV calendar id"):
            AppConfig(caldav_calendars=[make_config(), make_config()])

    def test_allows_shared_credential_env_names(self) -> None:
        config = AppConfig(caldav_calendars=[make_config("a"), make_config("b")])

        assert [calendar.id for calendar in config.caldav_calendars] == ["a", "b"]
        assert config.caldav_calendars[0].username_env == "U_ENV"
        assert config.caldav_calendars[1].password_env == "P_ENV"


class TestCredentialHandling:
    def test_reads_credentials_from_configured_env_names(self) -> None:
        client = FakeClient({})
        reader = make_reader([make_config()], client)

        reader.read_events("personal", datetime(2026, 1, 1), datetime(2026, 2, 1))

        assert client.init_kwargs["username"] == "alice"
        assert client.init_kwargs["password"] == "s3cret-value"
        assert client.init_kwargs["timeout"] == 7

    def test_missing_credentials_raise_without_leaking_values(self) -> None:
        client = FakeClient({})
        reader = make_reader([make_config()], client, env={})

        with pytest.raises(MissingCalDAVCredentialsError) as excinfo:
            reader.read_events("personal", datetime(2026, 1, 1), datetime(2026, 2, 1))

        message = str(excinfo.value)
        assert "personal" in message
        assert "U_ENV" in message
        assert "P_ENV" in message
        assert "s3cret" not in message
        assert "alice" not in message

    def test_unknown_calendar_id_raises(self) -> None:
        reader = make_reader([make_config()], FakeClient({}))

        with pytest.raises(UnknownCalDAVCalendarError):
            reader.read_events("other", datetime(2026, 1, 1), datetime(2026, 2, 1))

    def test_calendars_can_share_credential_env_names(self) -> None:
        client = FakeClient({})
        reader = make_reader([make_config("a"), make_config("b")], client)

        events_a = reader.read_events("a", datetime(2026, 1, 1), datetime(2026, 2, 1))
        events_b = reader.read_events("b", datetime(2026, 1, 1), datetime(2026, 2, 1))

        assert events_a == []
        assert events_b == []
        assert client.calendar_calls == [
            "https://calendar.example.test/dav/a/",
            "https://calendar.example.test/dav/b/",
        ]


class TestClientHandling:
    def test_client_requires_tls_verification_and_is_closed(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        reader = make_reader([make_config()], client)

        reader.read_events("personal", datetime(2026, 1, 1), datetime(2026, 2, 1))

        assert client.init_kwargs["ssl_verify_cert"] is True
        assert client.init_kwargs["require_tls"] is True
        assert client.closed is True


class TestEventQueries:
    def test_queries_requested_range_with_expansion(self) -> None:
        client = FakeClient({CALENDAR_URL: []})
        reader = make_reader([make_config()], client)
        start = datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/Vienna"))
        end = datetime(2026, 2, 1, tzinfo=ZoneInfo("Europe/Vienna"))

        reader.read_events("personal", start, end)

        search_kwargs = client.calendars[CALENDAR_URL].search_calls[0]
        assert search_kwargs == {"start": start, "end": end, "event": True, "expand": True}


class TestEventConversion:
    def test_datetime_event_with_dtend(self) -> None:
        start = datetime(2026, 3, 2, 9, 0, tzinfo=ZoneInfo("Europe/Vienna"))
        end = datetime(2026, 3, 2, 10, 30, tzinfo=ZoneInfo("Europe/Vienna"))
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART=({"TZID": "Europe/Vienna"}, "20260302T090000"),
            DTEND=({"TZID": "Europe/Vienna"}, "20260302T103000"),
            SUMMARY="Standup",
            LOCATION="Room 4",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert len(events) == 1
        event = events[0]
        assert event.id.startswith("caldav:personal:")
        assert event.calendar_id == "personal"
        assert event.calendar_name == "Personal"
        assert event.title == "Standup"
        assert event.start == start
        assert isinstance(event.start, datetime)
        assert event.start.utcoffset() == timedelta(hours=1)
        assert event.end == end
        assert event.all_day is False
        assert event.location == "Room 4"
        assert event.editable is False

    def test_datetime_event_preserves_its_own_timezone(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-utc.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
            DTEND="20260302T100000Z",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert events[0].start == datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        assert isinstance(events[0].start, datetime)
        assert events[0].start.utcoffset() == timedelta(0)

    def test_duration_is_applied(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
            DURATION="PT1H30M",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert events[0].end == datetime(2026, 3, 2, 10, 30, tzinfo=UTC)

    def test_missing_end_uses_start_instant(self) -> None:
        start = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert events[0].end == start

    def test_all_day_event_with_dtend_preserves_dates(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART=({"VALUE": "DATE"}, "20260501"),
            DTEND=({"VALUE": "DATE"}, "20260502"),
            SUMMARY="Holiday",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 4, 1), datetime(2026, 6, 1))

        assert events[0].all_day is True
        assert events[0].start == date(2026, 5, 1)
        assert events[0].end == date(2026, 5, 2)

    def test_all_day_event_without_end_ends_on_next_date(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART=({"VALUE": "DATE"}, "20260501"),
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 4, 1), datetime(2026, 6, 1))

        assert events[0].all_day is True
        assert events[0].start == date(2026, 5, 1)
        assert events[0].end == date(2026, 5, 2)

    def test_all_day_duration_is_applied_to_date(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART=({"VALUE": "DATE"}, "20260501"),
            DURATION="P2D",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 4, 1), datetime(2026, 6, 1))

        assert events[0].all_day is True
        assert events[0].end == date(2026, 5, 3)

    def test_mixed_all_day_and_datetime_events_sort_deterministically(self) -> None:
        resources = [
            make_resource(
                f"{CALENDAR_URL}later.ics",
                UID="uid-2",
                DTSTART=({"TZID": "Europe/Vienna"}, "20260302T120000"),
            ),
            make_resource(
                f"{CALENDAR_URL}all-day.ics",
                UID="uid-1",
                DTSTART=({"VALUE": "DATE"}, "20260302"),
            ),
        ]
        client = FakeClient({CALENDAR_URL: resources})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert [event.all_day for event in events] == [True, False]

    def test_cancelled_events_are_omitted(self) -> None:
        resources = [
            make_resource(
                f"{CALENDAR_URL}cancelled.ics",
                UID="uid-1",
                DTSTART="20260302T090000Z",
                SUMMARY="Cancelled",
                STATUS="CANCELLED",
            ),
            make_resource(
                f"{CALENDAR_URL}confirmed.ics",
                UID="uid-2",
                DTSTART="20260303T090000Z",
                SUMMARY="Confirmed",
                STATUS="CONFIRMED",
            ),
        ]
        client = FakeClient({CALENDAR_URL: resources})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert [event.title for event in events] == ["Confirmed"]

    def test_title_falls_back_when_summary_absent_or_empty(self) -> None:
        resources = [
            make_resource(
                f"{CALENDAR_URL}no-summary.ics",
                UID="uid-1",
                DTSTART="20260302T090000Z",
            ),
            make_resource(
                f"{CALENDAR_URL}empty-summary.ics",
                UID="uid-2",
                DTSTART="20260303T090000Z",
                SUMMARY="   ",
            ),
        ]
        client = FakeClient({CALENDAR_URL: resources})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert [event.title for event in events] == [
            "Untitled event",
            "Untitled event",
        ]

    def test_location_absent_returns_none(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert events[0].location is None

    def test_caldav_event_cannot_be_constructed_writable(self) -> None:
        with pytest.raises(ValidationError):
            CalDAVEvent.model_validate(
                {
                    "id": "x",
                    "calendar_id": "personal",
                    "calendar_name": "Personal",
                    "title": "T",
                    "start": date(2026, 5, 1),
                    "end": date(2026, 5, 2),
                    "all_day": True,
                    "editable": True,
                }
            )


class TestEventIds:
    def test_recurring_occurrences_do_not_collide(self) -> None:
        resources = [
            make_resource(
                f"{CALENDAR_URL}occurrence-1.ics",
                UID="uid-1",
                DTSTART=({"TZID": "Europe/Vienna"}, "20260302T090000"),
                RECURRENCE_ID=({"TZID": "Europe/Vienna"}, "20260302T090000"),
                SUMMARY="Weekly",
            ),
            make_resource(
                f"{CALENDAR_URL}occurrence-2.ics",
                UID="uid-1",
                DTSTART=({"TZID": "Europe/Vienna"}, "20260309T090000"),
                RECURRENCE_ID=({"TZID": "Europe/Vienna"}, "20260309T090000"),
                SUMMARY="Weekly",
            ),
        ]
        client = FakeClient({CALENDAR_URL: resources})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert len({event.id for event in events}) == 2

    def test_occurrences_without_recurrence_id_use_the_start(self) -> None:
        resources = [
            make_resource(
                f"{CALENDAR_URL}occurrence-1.ics",
                UID="uid-1",
                DTSTART="20260302T090000Z",
            ),
            make_resource(
                f"{CALENDAR_URL}occurrence-2.ics",
                UID="uid-1",
                DTSTART="20260309T090000Z",
            ),
        ]
        client = FakeClient({CALENDAR_URL: resources})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert len({event.id for event in events}) == 2

    def test_missing_uid_falls_back_to_resource_url(self) -> None:
        resources = [
            make_resource(
                f"{CALENDAR_URL}one.ics",
                DTSTART="20260302T090000Z",
            ),
            make_resource(
                f"{CALENDAR_URL}two.ics",
                DTSTART="20260302T090000Z",
            ),
        ]
        client = FakeClient({CALENDAR_URL: resources})
        reader = make_reader([make_config()], client)

        events = reader.read_events("personal", datetime(2026, 3, 1), datetime(2026, 4, 1))

        assert len(events) == 2
        assert len({event.id for event in events}) == 2

    def test_ids_are_stable_across_reads(self) -> None:
        resource = make_resource(
            f"{CALENDAR_URL}event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
        )
        client = FakeClient({CALENDAR_URL: [resource]})
        reader = make_reader([make_config()], client)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        first = reader.read_events("personal", *range_args)
        second = reader.read_events("personal", *range_args)

        assert first[0].id == second[0].id

    def test_equal_uids_in_different_calendars_do_not_collide(self) -> None:
        resource_a = make_resource(
            "https://calendar.example.test/dav/a/event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
        )
        resource_b = make_resource(
            "https://calendar.example.test/dav/b/event-1.ics",
            UID="uid-1",
            DTSTART="20260302T090000Z",
        )
        client = FakeClient(
            {
                "https://calendar.example.test/dav/a/": [resource_a],
                "https://calendar.example.test/dav/b/": [resource_b],
            }
        )
        reader = make_reader([make_config("a"), make_config("b")], client)
        range_args = (datetime(2026, 3, 1), datetime(2026, 4, 1))

        events_a = reader.read_events("a", *range_args)
        events_b = reader.read_events("b", *range_args)

        assert events_a[0].id != events_b[0].id
