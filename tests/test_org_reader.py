from datetime import datetime
from zoneinfo import ZoneInfo

from org_clock_calendar.config import OrgFileConfig
from org_clock_calendar.org_reader import OrgReader


def test_org_reader_lists_headings_and_clocks() -> None:
    reader = OrgReader(
        [OrgFileConfig(id="work", path="tests/data/basic.org")],
        timezone="Europe/Vienna",
    )

    headings = reader.list_headings()
    clocks, revisions = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )

    assert [heading.title for heading in headings] == ["Acme", "Development", "Support"]
    assert len(clocks) == 2
    assert clocks[0].file_id == "work"
    assert clocks[0].heading_title == "Development"
    assert clocks[0].duration_minutes == 135
    assert set(revisions) == {"work"}


def test_org_reader_filters_files() -> None:
    reader = OrgReader(
        [
            OrgFileConfig(id="work", path="tests/data/basic.org"),
            OrgFileConfig(id="other", path="tests/data/other.org"),
        ],
        timezone="Europe/Vienna",
    )

    clocks, revisions = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        file_ids=["other"],
    )

    assert [clock.file_id for clock in clocks] == ["other"]
    assert set(revisions) == {"other"}


def test_org_reader_parses_sample_fixture() -> None:
    reader = OrgReader(
        [OrgFileConfig(id="sample", path="tests/data/sample.org")],
        timezone="Europe/Vienna",
    )

    clocks, _ = reader.list_clocks(
        start=datetime(2026, 8, 3, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 9, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )

    assert len(clocks) == 5
    assert any(clock.heading_title == "Night maintenance" for clock in clocks)
    assert max(clock.duration_minutes for clock in clocks) == 90
