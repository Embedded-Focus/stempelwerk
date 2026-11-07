from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from stempelwerk.config import OrgFileConfig
from stempelwerk.org_reader import OrgReader, UnknownOrgFileError
from stempelwerk.org_writer import (
    OrgWriter,
    TextEdit,
    backup_created_at,
    format_clock_duration,
    format_clock_timestamp,
    list_backups,
)


def test_replace_clock_line_preserves_surrounding_text() -> None:
    source = "before\nCLOCK: old\n after\n"
    edit = TextEdit(start=7, end=17, replacement="CLOCK: new")

    assert OrgWriter().replace_clock_line(source, edit) == "before\nCLOCK: new\n after\n"


def test_format_clock_timestamp_includes_weekday() -> None:
    moment = datetime(2026, 7, 31, 9, 30, tzinfo=ZoneInfo("Europe/Vienna"))

    assert format_clock_timestamp(moment) == "[2026-07-31 Fri 09:30]"


def test_format_clock_duration_formats_as_hmm() -> None:
    start = datetime(2026, 7, 31, 9, 30, tzinfo=ZoneInfo("Europe/Vienna"))
    end = datetime(2026, 7, 31, 10, 45, tzinfo=ZoneInfo("Europe/Vienna"))

    assert format_clock_duration(start, end) == "1:15"


def test_format_clock_duration_pads_single_digit_minutes() -> None:
    start = datetime(2026, 7, 31, 9, 0, tzinfo=ZoneInfo("Europe/Vienna"))
    end = datetime(2026, 7, 31, 9, 5, tzinfo=ZoneInfo("Europe/Vienna"))

    assert format_clock_duration(start, end) == "0:05"


def _reader(tmp_path: Path, org_text: str) -> tuple[OrgReader, Path]:
    org_file = tmp_path / "work.org"
    org_file.write_text(org_text, encoding="utf-8")
    return OrgReader([OrgFileConfig(id="work", path=org_file)], timezone="Europe/Vienna"), org_file


def test_update_clock_preserves_indentation_and_replaces_only_target_line(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Acme\n"
        "** Development\n"
        ":LOGBOOK:\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n"
        ":END:\n"
        "** Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 13:45] =>  0:45\n",
    )
    window: dict[str, Any] = {
        "start": datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        "end": datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    }
    clocks, _ = reader.list_clocks(**window)
    development = next(c for c in clocks if c.heading_title == "Development")

    OrgWriter().update_clock(
        reader,
        development.id,
        start=datetime(2026, 7, 31, 9, 30, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 10, 45, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=development.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Acme\n"
        "** Development\n"
        ":LOGBOOK:\n"
        "  CLOCK: [2026-07-31 Fri 09:30]--[2026-07-31 Fri 10:45] =>  1:15\n"
        ":END:\n"
        "** Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 13:45] =>  0:45\n"
    )


def test_update_clock_does_not_create_backup(tmp_path: Path) -> None:
    reader, _org_file = _reader(
        tmp_path,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    clocks, _ = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )
    clock = clocks[0]

    OrgWriter().update_clock(
        reader,
        clock.id,
        start=datetime(2026, 7, 31, 9, 30, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 10, 45, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert list(tmp_path.glob("work.org.bak.*")) == []


def test_create_backup_copies_current_contents_under_timestamped_name(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    original_text = org_file.read_text(encoding="utf-8")

    backup_path = OrgWriter().create_backup(reader, "work")

    assert backup_path.parent == tmp_path
    assert backup_path.name.startswith("work.org.bak.")
    assert backup_created_at(backup_path.name) is not None
    assert backup_path.read_text(encoding="utf-8") == original_text


def test_create_backup_unknown_file_id_raises(tmp_path: Path) -> None:
    reader, _org_file = _reader(
        tmp_path,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )

    with pytest.raises(UnknownOrgFileError):
        OrgWriter().create_backup(reader, "other")


def test_create_backup_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    reader = OrgReader(
        [OrgFileConfig(id="work", path=tmp_path / "missing.org")],
        timezone="Europe/Vienna",
    )

    with pytest.raises(FileNotFoundError):
        OrgWriter().create_backup(reader, "work")


def test_list_backups_returns_matching_files_oldest_first(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Work\n", encoding="utf-8")
    old = tmp_path / "work.org.bak.20260101T120000000000"
    new = tmp_path / "work.org.bak.20260201T090000000000"
    stray = tmp_path / "work.org.bak.not-a-timestamp"
    unrelated = tmp_path / "other.org.bak.20260101T120000000000"
    for path, content in ((old, "old"), (new, "new"), (stray, "stray"), (unrelated, "other")):
        path.write_text(content, encoding="utf-8")

    assert list_backups(org_file) == [old, new]


def test_backup_created_at_rejects_invalid_names() -> None:
    assert backup_created_at("work.org.bak.not-a-timestamp") is None
    assert backup_created_at("work.org") is None
    assert backup_created_at("work.org.bak.20260101T120000000000") == datetime(
        2026, 1, 1, 12, 0, 0, tzinfo=UTC
    )
