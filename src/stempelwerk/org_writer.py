import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from stempelwerk.domain import ClockEntry
from stempelwerk.org_reader import (
    HEADING_RE,
    OrgReader,
    UnknownOrgFileError,
    _clock_id,
    _split_tags,
)
from stempelwerk.revisions import revision_for_bytes

_BACKUP_NAME_RE = re.compile(r"^.+\.bak\.(?P<timestamp>\d{8}T\d{12})$")
_LOGBOOK_RE = re.compile(r"^(?P<indent>\s*):LOGBOOK:\s*$")
_PROPERTIES_RE = re.compile(r"^\s*:PROPERTIES:\s*$")
_END_RE = re.compile(r"^\s*:END:\s*$")
_PLANNING_RE = re.compile(r"^\s*(SCHEDULED|DEADLINE|CLOSED):")

_WEEKDAY_ABBREVIATIONS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class TextEdit:
    start: int
    end: int
    replacement: str


class ClockNotFoundError(LookupError):
    def __init__(self, clock_id: str) -> None:
        self.clock_id = clock_id
        super().__init__(f"Unknown clock id: {clock_id}")


class HeadingNotFoundError(LookupError):
    def __init__(self, heading_id: str) -> None:
        self.heading_id = heading_id
        super().__init__(f"Unknown heading id: {heading_id}")


class InvalidHeadingTitleError(ValueError):
    def __init__(self, title: str, reason: str) -> None:
        self.title = title
        self.reason = reason
        super().__init__(f"Invalid heading title {title!r}: {reason}")


class RevisionConflictError(ValueError):
    def __init__(self, expected_revision: str, actual_revision: str) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__("File revision changed since it was loaded")


def backup_created_at(filename: str) -> datetime | None:
    """Parse the UTC timestamp from a backup file name, or return None."""

    match = _BACKUP_NAME_RE.match(filename)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%S%f").replace(tzinfo=UTC)
    except ValueError:
        return None


def list_backups(path: Path) -> list[Path]:
    """List backup files for *path* next to it, oldest first."""

    prefix = f"{path.name}.bak."
    backups = [
        entry
        for entry in path.parent.iterdir()
        if entry.is_file() and entry.name.startswith(prefix) and backup_created_at(entry.name)
    ]
    return sorted(
        backups, key=lambda entry: backup_created_at(entry.name) or datetime.min.replace(tzinfo=UTC)
    )


def _read_at_revision(path: Path, expected_revision: str) -> str:
    """Return the decoded file text, or raise RevisionConflictError."""

    raw = path.read_bytes()
    current_revision = revision_for_bytes(raw)
    if current_revision != expected_revision:
        raise RevisionConflictError(expected_revision, current_revision)
    return raw.decode("utf-8")


def format_clock_timestamp(moment: datetime) -> str:
    weekday = _WEEKDAY_ABBREVIATIONS[moment.weekday()]
    return f"[{moment:%Y-%m-%d} {weekday} {moment:%H:%M}]"


def format_clock_duration(start: datetime, end: datetime) -> str:
    total_minutes = int((end - start).total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


def format_clock_line(indent: str, start: datetime, end: datetime) -> str:
    """Return a CLOCK line without line break. start and end are local and whole minutes."""

    return (
        f"{indent}CLOCK: {format_clock_timestamp(start)}--{format_clock_timestamp(end)}"
        f" =>  {format_clock_duration(start, end)}"
    )


def _line_break(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return "\n"


class OrgWriter:
    """Lossless CLOCK line editor boundary."""

    def replace_clock_line(self, source: str, edit: TextEdit) -> str:
        if edit.start < 0 or edit.end < edit.start or edit.end > len(source):
            raise ValueError("invalid edit range")
        return source[: edit.start] + edit.replacement + source[edit.end :]

    def update_clock(
        self,
        reader: OrgReader,
        clock_id: str,
        start: datetime,
        end: datetime,
        expected_revision: str,
    ) -> ClockEntry:
        file_config = reader.resolve_file(clock_id)
        if file_config is None:
            raise ClockNotFoundError(clock_id)

        text = _read_at_revision(file_config.path, expected_revision)

        parsed = reader.find_clock(clock_id)
        if parsed is None:
            raise ClockNotFoundError(clock_id)

        local_start = start.astimezone(reader.timezone).replace(second=0, microsecond=0)
        local_end = end.astimezone(reader.timezone).replace(second=0, microsecond=0)
        indent = parsed.line[: len(parsed.line) - len(parsed.line.lstrip())]
        replacement = format_clock_line(indent, local_start, local_end)

        edit = TextEdit(start=parsed.line_start, end=parsed.line_end, replacement=replacement)
        updated_text = self.replace_clock_line(text, edit)

        _write_atomically(file_config.path, updated_text)

        new_id = _clock_id(
            parsed.entry.file_id, parsed.entry.heading_id, parsed.line_number, replacement
        )
        updated = reader.find_clock(new_id)
        if updated is None:
            raise RuntimeError(f"Updated clock {new_id} not found after write")
        return updated.entry

    def move_clock(
        self,
        reader: OrgReader,
        clock_id: str,
        target_heading_id: str,
        start: datetime,
        end: datetime,
        expected_revision: str,
    ) -> ClockEntry:
        """Move one CLOCK line into the target heading's drawer."""

        file_config = reader.resolve_file(clock_id)
        if file_config is None:
            raise ClockNotFoundError(clock_id)

        text = _read_at_revision(file_config.path, expected_revision)

        parsed = reader.find_clock(clock_id)
        if parsed is None:
            raise ClockNotFoundError(clock_id)

        target = reader.find_heading(file_config.id, target_heading_id)
        if target is None:
            raise HeadingNotFoundError(target_heading_id)

        if target.id == parsed.entry.heading_id:
            return self.update_clock(reader, clock_id, start, end, expected_revision)

        local_start = start.astimezone(reader.timezone).replace(second=0, microsecond=0)
        local_end = end.astimezone(reader.timezone).replace(second=0, microsecond=0)

        lines = text.splitlines(keepends=True)
        h = target.line_number - 1

        # Find the insertion point in the target section.
        section_end = len(lines)
        for i in range(h + 1, len(lines)):
            if HEADING_RE.match(lines[i].rstrip("\r\n")):
                section_end = i
                break

        logbook_match = None
        for i in range(h + 1, section_end):
            match = _LOGBOOK_RE.match(lines[i].rstrip("\r\n"))
            if match is not None:
                logbook_match = (i, match)
                break

        creates_drawer = logbook_match is None
        if logbook_match is not None:
            d, match = logbook_match
            insert_at = d + 1
            br = _line_break(lines[d])
            new_lines = [format_clock_line(match.group("indent"), local_start, local_end) + br]
        else:
            p = h + 1
            if p < section_end and _PLANNING_RE.match(lines[p].rstrip("\r\n")):
                p += 1
            if p < section_end and _PROPERTIES_RE.match(lines[p].rstrip("\r\n")):
                end_at = next(
                    (
                        i
                        for i in range(p + 1, section_end)
                        if _END_RE.match(lines[i].rstrip("\r\n"))
                    ),
                    None,
                )
                if end_at is not None:
                    p = end_at + 1
            insert_at = p
            br = _line_break(lines[h])
            new_lines = [
                ":LOGBOOK:" + br,
                format_clock_line("", local_start, local_end) + br,
                ":END:" + br,
            ]

        if insert_at > 0 and not lines[insert_at - 1].endswith(("\n", "\r\n")):
            lines[insert_at - 1] += br

        # Remove the source line and an empty source drawer.
        c = parsed.line_number - 1
        remove = [c]
        if (
            c - 1 >= 0
            and _LOGBOOK_RE.match(lines[c - 1].rstrip("\r\n"))
            and c + 1 < len(lines)
            and _END_RE.match(lines[c + 1].rstrip("\r\n"))
        ):
            remove = [c - 1, c, c + 1]

        # Apply the change with the higher index first.
        if insert_at > max(remove):
            lines[insert_at:insert_at] = new_lines
            del lines[min(remove) : max(remove) + 1]
        else:
            del lines[min(remove) : max(remove) + 1]
            lines[insert_at:insert_at] = new_lines

        # Compute the final 1-based line number of the moved clock line.
        index = insert_at + (1 if creates_drawer else 0)
        if max(remove) < insert_at:
            index -= len(remove)
        final_line_number = index + 1

        _write_atomically(file_config.path, "".join(lines))

        moved = reader.clock_at_line(file_config.id, final_line_number)
        if moved is None:
            raise RuntimeError("Moved clock not found after write")
        return moved.entry

    def create_backup(self, reader: OrgReader, file_id: str) -> Path:
        """Create a backup of the current contents of a configured Org file."""

        file_config = reader.file_by_id(file_id)
        if file_config is None:
            raise UnknownOrgFileError([file_id])
        raw = file_config.path.read_bytes()
        return _create_backup(file_config.path, raw)

    def rename_heading(
        self,
        reader: OrgReader,
        file_id: str,
        heading_id: str,
        title: str,
        expected_revision: str,
    ) -> bool:
        """Rename one heading. Return True if the file was written."""

        file_config = reader.file_by_id(file_id)
        if file_config is None:
            raise UnknownOrgFileError([file_id])

        text = _read_at_revision(file_config.path, expected_revision)

        parsed = reader.find_heading(file_id, heading_id)
        if parsed is None:
            raise HeadingNotFoundError(heading_id)

        new_title = title.strip()
        if not new_title:
            raise InvalidHeadingTitleError(title, "empty")
        if "\n" in new_title or "\r" in new_title:
            raise InvalidHeadingTitleError(title, "line break")

        relative_start = parsed.title_start - parsed.line_start
        relative_end = parsed.title_end - parsed.line_start
        new_line = parsed.line[:relative_start] + new_title + parsed.line[relative_end:]
        match = HEADING_RE.match(new_line)
        if (
            match is None
            or match.group("title").strip() != new_title
            or match.group("todo") != parsed.todo
            or _split_tags(match.group("tags")) != parsed.tags
        ):
            raise InvalidHeadingTitleError(title, "not preserved")

        if new_title == parsed.title:
            return False

        edit = TextEdit(start=parsed.title_start, end=parsed.title_end, replacement=new_title)
        updated_text = self.replace_clock_line(text, edit)
        _write_atomically(file_config.path, updated_text)
        return True


def _create_backup(path: Path, raw: bytes) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    backup_path = path.with_name(f"{path.name}.bak.{timestamp}")
    backup_path.write_bytes(raw)
    return backup_path


def _write_atomically(path: Path, content: str) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
