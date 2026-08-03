from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stempelwerk.config import OrgFileConfig
from stempelwerk.org_reader import OrgReader


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
    window = {
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
