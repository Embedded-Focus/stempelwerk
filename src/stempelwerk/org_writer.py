import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from stempelwerk.org_reader import OrgReader, UnknownOrgFileError
from stempelwerk.revisions import revision_for_bytes

_BACKUP_NAME_RE = re.compile(r"^.+\.bak\.(?P<timestamp>\d{8}T\d{12})$")

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


def format_clock_timestamp(moment: datetime) -> str:
    weekday = _WEEKDAY_ABBREVIATIONS[moment.weekday()]
    return f"[{moment:%Y-%m-%d} {weekday} {moment:%H:%M}]"


def format_clock_duration(start: datetime, end: datetime) -> str:
    total_minutes = int((end - start).total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


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
    ) -> None:
        file_config = reader.resolve_file(clock_id)
        if file_config is None:
            raise ClockNotFoundError(clock_id)

        raw = file_config.path.read_bytes()
        current_revision = revision_for_bytes(raw)
        if current_revision != expected_revision:
            raise RevisionConflictError(expected_revision, current_revision)

        parsed = reader.find_clock(clock_id)
        if parsed is None:
            raise ClockNotFoundError(clock_id)

        local_start = start.astimezone(reader.timezone)
        local_end = end.astimezone(reader.timezone)
        indent = parsed.line[: len(parsed.line) - len(parsed.line.lstrip())]
        replacement = (
            f"{indent}CLOCK: {format_clock_timestamp(local_start)}--{format_clock_timestamp(local_end)}"
            f" =>  {format_clock_duration(local_start, local_end)}"
        )

        text = raw.decode("utf-8")
        edit = TextEdit(start=parsed.line_start, end=parsed.line_end, replacement=replacement)
        updated_text = self.replace_clock_line(text, edit)

        _write_atomically(file_config.path, updated_text)

    def create_backup(self, reader: OrgReader, file_id: str) -> Path:
        """Create a backup of the current contents of a configured Org file."""

        file_config = reader.file_by_id(file_id)
        if file_config is None:
            raise UnknownOrgFileError([file_id])
        raw = file_config.path.read_bytes()
        return _create_backup(file_config.path, raw)


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
