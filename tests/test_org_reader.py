from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from stempelwerk.config import OrgFileConfig
from stempelwerk.org_reader import OrgReader, UnknownOrgFileError
from stempelwerk.revisions import revision_for_file


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


def test_clock_id_encodes_file_id_and_survives_unrelated_edits(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(
        "* Development\n"
        "CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n"
        "* Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 13:45] =>  0:45\n",
        encoding="utf-8",
    )
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")
    window: dict[str, Any] = {
        "start": datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        "end": datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    }

    clocks_before, revisions_before = reader.list_clocks(**window)
    development_before = next(c for c in clocks_before if c.heading_title == "Development")
    support_before = next(c for c in clocks_before if c.heading_title == "Support")

    assert development_before.id.startswith("clock:work:")

    org_file.write_text(
        "* Development\n"
        "CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n"
        "* Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 14:45] =>  1:45\n",
        encoding="utf-8",
    )

    clocks_after, revisions_after = reader.list_clocks(**window)
    development_after = next(c for c in clocks_after if c.heading_title == "Development")
    support_after = next(c for c in clocks_after if c.heading_title == "Support")

    assert revisions_after["work"] != revisions_before["work"]
    assert development_after.id == development_before.id
    assert support_after.id != support_before.id


def test_find_clock_locates_exact_line_including_indentation(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    text = (
        "* Acme\n"
        "** Development\n"
        ":LOGBOOK:\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n"
        ":END:\n"
        "** Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 13:45] =>  0:45\n"
    )
    org_file.write_text(text, encoding="utf-8")
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")

    clocks, _ = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )
    development = next(c for c in clocks if c.heading_title == "Development")

    parsed = reader.find_clock(development.id)

    assert parsed is not None
    assert parsed.entry == development
    assert parsed.file.id == "work"
    assert parsed.line == "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15"
    assert text[parsed.line_start : parsed.line_end] == parsed.line
    assert parsed.revision == revision_for_file(org_file)


def test_find_clock_returns_none_for_unknown_or_malformed_id(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(
        "* Development\nCLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n",
        encoding="utf-8",
    )
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")

    assert reader.find_clock("clock:work:doesnotexist") is None
    assert reader.find_clock("clock:unknown-file:abc123") is None
    assert reader.find_clock("not-a-clock-id") is None


def test_find_heading_returns_offsets_and_preserves_title_span(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    text = (
        "* Client Work :billable:\n"
        "** TODO Implementation :backend:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        "*** Sub Task\n"
    )
    org_file.write_text(text, encoding="utf-8")
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")
    heading_id = _heading_id_for_outline(reader, ["Client Work", "Implementation"], "work")

    parsed = reader.find_heading("work", heading_id)

    assert parsed is not None
    assert parsed.title == "Implementation"
    assert parsed.todo == "TODO"
    assert parsed.tags == ["backend"]
    assert text[parsed.title_start : parsed.title_end] == "Implementation"
    assert text[parsed.line_start : parsed.line_end] == parsed.line
    assert parsed.line == "** TODO Implementation :backend:"


def test_find_heading_returns_none_for_unknown_id(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Development\n", encoding="utf-8")
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")

    assert reader.find_heading("work", "heading:doesnotexist") is None


def test_find_heading_raises_for_unknown_file_id(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Development\n", encoding="utf-8")
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")

    with pytest.raises(UnknownOrgFileError):
        reader.find_heading("other", "heading:whatever")


def _heading_id_for_outline(reader: OrgReader, outline: list[str], file_id: str) -> str:
    heading = next(h for h in reader.list_headings() if h.outline == outline)
    assert heading.file_id == file_id
    return heading.id


def test_find_heading_reports_one_based_line_number(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* First\n\n* Second\n", encoding="utf-8")
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")

    second_id = _heading_id_for_outline(reader, ["Second"], "work")
    parsed = reader.find_heading("work", second_id)

    assert parsed is not None
    assert parsed.line_number == 3
    assert parsed.line == "* Second"


def test_clock_at_line_returns_clock_on_that_line(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        encoding="utf-8",
    )
    reader = OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna")

    parsed = reader.clock_at_line("work", 2)

    assert parsed is not None
    assert parsed.line_number == 2
    assert parsed.entry.heading_title == "Work"
    assert reader.clock_at_line("work", 1) is None
