from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from stempelwerk.config import OrgFileConfig
from stempelwerk.org_reader import OrgReader, UnknownOrgFileError
from stempelwerk.org_writer import (
    ClockNotFoundError,
    HeadingNotFoundError,
    InvalidHeadingTitleError,
    OrgWriter,
    RevisionConflictError,
    TextEdit,
    backup_created_at,
    format_clock_duration,
    format_clock_timestamp,
    list_backups,
)
from stempelwerk.revisions import revision_for_file


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
    old_revision = development.revision

    updated = OrgWriter().update_clock(
        reader,
        development.id,
        start=datetime(2026, 7, 31, 9, 30, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 10, 45, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=development.revision,
    )

    assert updated.start == datetime(2026, 7, 31, 9, 30, tzinfo=ZoneInfo("Europe/Vienna"))
    assert updated.end == datetime(2026, 7, 31, 10, 45, tzinfo=ZoneInfo("Europe/Vienna"))
    assert updated.duration_minutes == 75
    assert updated.id != development.id
    assert updated.revision != old_revision

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


def test_rename_heading_changes_only_the_title_text(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Acme\n"
        "** TODO Implementation :backend:\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n"
        "** Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 13:45] =>  0:45\n",
    )
    heading_id = _heading_id_by_outline(reader, ["Acme", "Implementation"])

    written = OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="Coding",
        expected_revision=revision_for_file(org_file),
    )

    assert written is True
    assert org_file.read_text(encoding="utf-8") == (
        "* Acme\n"
        "** TODO Coding :backend:\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 11:30] =>  2:15\n"
        "** Support\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 13:45] =>  0:45\n"
    )


def test_rename_heading_keeps_whitespace_between_title_and_tags(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Client Work      :billable:x:\n",
    )
    heading_id = _heading_id_by_outline(reader, ["Client Work"])

    OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="Customer Work",
        expected_revision=revision_for_file(org_file),
    )

    assert org_file.read_text(encoding="utf-8") == "* Customer Work      :billable:x:\n"


def test_rename_heading_treats_priority_cookie_as_title(tmp_path: Path) -> None:
    reader, org_file = _reader(tmp_path, "*** [#A] Fix bug\n")
    heading_id = _heading_id_by_outline(reader, ["[#A] Fix bug"])

    OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="[#B] Fix bug",
        expected_revision=revision_for_file(org_file),
    )

    assert org_file.read_text(encoding="utf-8") == "*** [#B] Fix bug\n"


def test_rename_heading_changes_only_the_target_among_equal_titles(
    tmp_path: Path,
) -> None:
    reader, org_file = _reader(tmp_path, "* Notes\n* Notes\n")
    headings = reader.list_headings()
    first_id = headings[0].id
    second_id = headings[1].id

    OrgWriter().rename_heading(
        reader,
        "work",
        first_id,
        title="Journal",
        expected_revision=revision_for_file(org_file),
    )

    assert org_file.read_text(encoding="utf-8") == "* Journal\n* Notes\n"
    assert reader.find_heading("work", second_id) is not None
    assert reader.find_heading("work", first_id) is None


def test_rename_heading_updates_titles_seen_by_clocks_and_children(
    tmp_path: Path,
) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Acme\n"
        "** Development\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        "*** Coding\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n",
    )
    heading_id = _heading_id_by_outline(reader, ["Acme", "Development"])
    window: dict[str, Any] = {
        "start": datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        "end": datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    }

    OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="Engineering",
        expected_revision=revision_for_file(org_file),
    )

    clocks, _ = reader.list_clocks(**window)
    by_title = {clock.heading_title for clock in clocks}
    assert by_title == {"Engineering", "Coding"}
    outlines = {tuple(clock.outline) for clock in clocks}
    assert ("Acme", "Engineering", "Coding") in outlines


def test_rename_heading_strips_surrounding_whitespace(tmp_path: Path) -> None:
    reader, org_file = _reader(tmp_path, "* Work\n")
    heading_id = _heading_id_by_outline(reader, ["Work"])

    OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="  Paid Work  ",
        expected_revision=revision_for_file(org_file),
    )

    assert org_file.read_text(encoding="utf-8") == "* Paid Work\n"


def test_rename_heading_same_title_is_a_no_op(tmp_path: Path) -> None:
    reader, org_file = _reader(tmp_path, "* Work\n")
    heading_id = _heading_id_by_outline(reader, ["Work"])
    before = org_file.read_bytes()

    written = OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="Work",
        expected_revision=revision_for_file(org_file),
    )

    assert written is False
    assert org_file.read_bytes() == before


def test_rename_heading_rejects_stale_revision(tmp_path: Path) -> None:
    reader, org_file = _reader(tmp_path, "* Work\n")
    heading_id = _heading_id_by_outline(reader, ["Work"])
    before = org_file.read_bytes()

    with pytest.raises(RevisionConflictError):
        OrgWriter().rename_heading(
            reader,
            "work",
            heading_id,
            title="New",
            expected_revision="sha256:stale",
        )

    assert org_file.read_bytes() == before


def test_rename_heading_unknown_heading_id_raises(tmp_path: Path) -> None:
    reader, org_file = _reader(tmp_path, "* Work\n")

    with pytest.raises(HeadingNotFoundError):
        OrgWriter().rename_heading(
            reader,
            "work",
            "heading:doesnotexist",
            title="New",
            expected_revision=revision_for_file(org_file),
        )


def test_rename_heading_unknown_file_id_raises(tmp_path: Path) -> None:
    reader, _org_file = _reader(tmp_path, "* Work\n")

    with pytest.raises(UnknownOrgFileError):
        OrgWriter().rename_heading(
            reader,
            "other",
            "heading:whatever",
            title="New",
            expected_revision="sha256:stale",
        )


@pytest.mark.parametrize(
    ("title", "org_text"),
    [
        ("", "* Work\n"),
        ("   ", "* Work\n"),
        ("a\nb", "* Work\n"),
        ("WIP changes", "* Work\n"),
        ("Done :tag:", "* Work\n"),
    ],
)
def test_rename_heading_rejects_invalid_titles_and_keeps_file(
    tmp_path: Path, title: str, org_text: str
) -> None:
    reader, org_file = _reader(tmp_path, org_text)
    heading_id = _heading_id_by_outline(reader, [org_text.removeprefix("*").strip()])
    before = org_file.read_bytes()

    with pytest.raises(InvalidHeadingTitleError):
        OrgWriter().rename_heading(
            reader,
            "work",
            heading_id,
            title=title,
            expected_revision=revision_for_file(org_file),
        )

    assert org_file.read_bytes() == before


def test_rename_heading_creates_no_backup(tmp_path: Path) -> None:
    reader, org_file = _reader(tmp_path, "* Work\n")
    heading_id = _heading_id_by_outline(reader, ["Work"])

    OrgWriter().rename_heading(
        reader,
        "work",
        heading_id,
        title="New",
        expected_revision=revision_for_file(org_file),
    )

    assert list(tmp_path.glob("work.org.bak.*")) == []


def _heading_id_by_outline(reader: OrgReader, outline: list[str]) -> str:
    return next(heading.id for heading in reader.list_headings() if heading.outline == outline)


def _heading_id_by_title(reader: OrgReader, title: str) -> str:
    return next(h.id for h in reader.list_headings() if h.title == title)


def test_move_clock_into_existing_drawer_inserts_first(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        ":END:\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-30 Thu 08:00]--[2026-07-30 Thu 09:00] =>  1:00\n"
        ":END:\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 30, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 2, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    moved = OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert moved.heading_title == "Target"
    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        "CLOCK: [2026-07-30 Thu 08:00]--[2026-07-30 Thu 09:00] =>  1:00\n"
        ":END:\n"
    )


def test_move_clock_into_indented_drawer_keeps_indent(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        ":END:\n"
        "* Target\n"
        " :LOGBOOK:\n"
        " :END:\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        " :LOGBOOK:\n"
        " CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        " :END:\n"
    )


def test_move_clock_creates_drawer_directly_after_heading(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    moved = OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert moved.heading_title == "Target"
    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
    )


def test_move_clock_creates_drawer_after_planning_line(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        ":END:\n"
        "* Target\n"
        "SCHEDULED: <2026-08-01 Sat>\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        "SCHEDULED: <2026-08-01 Sat>\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
    )


def test_move_clock_creates_drawer_after_properties(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        ":END:\n"
        "* Target\n"
        "DEADLINE: <2023-02-02 Thu>\n"
        ":PROPERTIES:\n"
        ":ARCHIVE_TIME: 2023-02-02 Thu 11:10\n"
        ":END:\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        "DEADLINE: <2023-02-02 Thu>\n"
        ":PROPERTIES:\n"
        ":ARCHIVE_TIME: 2023-02-02 Thu 11:10\n"
        ":END:\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
    )


def test_move_clock_creates_drawer_between_heading_and_first_child(
    tmp_path: Path,
) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n** Child\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
        "** Child\n"
    )


def test_move_clock_removes_empty_source_drawer(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert ":LOGBOOK:" not in org_file.read_text(encoding="utf-8").split("* Target")[0]


def test_move_clock_keeps_drawer_with_remaining_clock(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 14:00] =>  1:00\n"
        ":END:\n"
        "* Target\n",
    )
    clocks, _ = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )
    first = next(c for c in clocks if c.start.hour == 9)
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        first.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=first.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 13:00]--[2026-07-31 Fri 14:00] =>  1:00\n"
        ":END:\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
    )


def test_move_clock_removes_bare_clock_line(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n* Target\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
    )


def test_move_clock_to_target_above_source(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Target\n:LOGBOOK:\nCLOCK: [2026-07-30 Thu 08:00]--[2026-07-30 Thu 09:00] =>  1:00\n:END:\n* Source\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    moved = OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert moved.heading_title == "Target"
    assert org_file.read_text(encoding="utf-8") == (
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        "CLOCK: [2026-07-30 Thu 08:00]--[2026-07-30 Thu 09:00] =>  1:00\n"
        ":END:\n"
        "* Source\n"
    )


def test_move_clock_to_last_heading_without_final_break(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    content = org_file.read_text(encoding="utf-8")
    assert content == (
        "* Source\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n"
        ":END:\n"
    )
    assert all(line.endswith("\n") for line in content.splitlines(keepends=True))


def test_move_clock_uses_crlf_line_breaks(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\r\n:LOGBOOK:\r\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\r\n:END:\r\n* Target\r\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")

    OrgWriter().move_clock(
        reader,
        clock.id,
        target_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert org_file.read_bytes() == (
        b"* Source\r\n"
        b"* Target\r\n"
        b":LOGBOOK:\r\n"
        b"CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\r\n"
        b":END:\r\n"
    )


def test_move_clock_to_current_heading_updates_times_only(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Work\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    heading_id = next(h.id for h in reader.list_headings() if h.title == "Work")
    before = org_file.read_bytes()

    moved = OrgWriter().move_clock(
        reader,
        clock.id,
        heading_id,
        start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        expected_revision=clock.revision,
    )

    assert moved.heading_title == "Work"
    assert org_file.read_bytes() != before
    assert org_file.read_text(encoding="utf-8") == (
        "* Work\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n:END:\n"
    )


def test_move_clock_rejects_stale_revision(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")
    before = org_file.read_bytes()

    with pytest.raises(RevisionConflictError):
        OrgWriter().move_clock(
            reader,
            clock.id,
            target_id,
            start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
            end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
            expected_revision="sha256:stale",
        )

    assert org_file.read_bytes() == before


def test_move_clock_unknown_clock_or_target_raises(tmp_path: Path) -> None:
    reader, org_file = _reader(
        tmp_path,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    clock = reader.list_clocks(
        start=datetime(2026, 7, 31, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
        end=datetime(2026, 8, 1, 0, 0, tzinfo=ZoneInfo("Europe/Vienna")),
    )[0][0]
    target_id = _heading_id_by_title(reader, "Target")
    before = org_file.read_bytes()

    with pytest.raises(ClockNotFoundError):
        OrgWriter().move_clock(
            reader,
            "clock:work:missing",
            target_id,
            start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
            end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
            expected_revision=clock.revision,
        )
    with pytest.raises(HeadingNotFoundError):
        OrgWriter().move_clock(
            reader,
            clock.id,
            "heading:missing",
            start=datetime(2026, 7, 31, 11, 0, tzinfo=ZoneInfo("Europe/Vienna")),
            end=datetime(2026, 7, 31, 12, 0, tzinfo=ZoneInfo("Europe/Vienna")),
            expected_revision=clock.revision,
        )

    assert org_file.read_bytes() == before
