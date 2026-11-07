from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stempelwerk.config import OrgFileConfig
from stempelwerk.org_reader import OrgReader
from stempelwerk.org_writer import (
    OrgWriter,
    TextEdit,
    format_clock_duration,
    format_clock_timestamp,
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


def test_update_clock_creates_backup_of_prior_contents(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    original_text = org_file.read_text(encoding="utf-8")
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

    backups = list(tmp_path.glob("work.org.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original_text
