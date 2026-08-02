import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from stempelwerk.config import OrgFileConfig
from stempelwerk.domain import ClockEntry, Heading
from stempelwerk.revisions import revision_for_bytes

HEADING_RE = re.compile(r"^(?P<stars>\*+)\s+(?:(?P<todo>[A-Z]+)\s+)?(?P<title>.*?)(?:\s+:(?P<tags>[^:\s]+(?::[^:\s]+)*):)?\s*$")
CLOCK_RE = re.compile(
    r"^(?P<indent>\s*)CLOCK:\s+"
    r"\[(?P<start_date>\d{4}-\d{2}-\d{2})(?:\s+\w+)?\s+(?P<start_time>\d{2}:\d{2})\]"
    r"--"
    r"\[(?P<end_date>\d{4}-\d{2}-\d{2})(?:\s+\w+)?\s+(?P<end_time>\d{2}:\d{2})\]"
    r"(?:\s+=>\s+(?P<duration>\d+:\d{2}))?\s*$"
)


class OrgReader:
    """Semantic Org reader facade.

    The implementation will use orgparse for traversal while preserving a
    separate source-location model for lossless edits.
    """

    def __init__(self, files: list[OrgFileConfig], timezone: str) -> None:
        self._files = files
        self._timezone = ZoneInfo(timezone)

    def list_headings(self) -> list[Heading]:
        headings: list[Heading] = []
        for file_config in self._files:
            headings.extend(self._read_file(file_config)[0])
        return headings

    def list_clocks(
        self,
        start: datetime,
        end: datetime,
        file_ids: list[str] | None = None,
    ) -> tuple[list[ClockEntry], dict[str, str]]:
        selected_files = self._selected_files(file_ids)
        clocks: list[ClockEntry] = []
        revisions: dict[str, str] = {}

        for file_config in selected_files:
            _, file_clocks, revision = self._read_file(file_config)
            revisions[file_config.id] = revision
            clocks.extend(clock for clock in file_clocks if clock.start < end and clock.end > start)

        return clocks, revisions

    def _selected_files(self, file_ids: list[str] | None) -> list[OrgFileConfig]:
        if not file_ids:
            return self._files

        configured = {file.id: file for file in self._files}
        unknown = sorted(set(file_ids) - set(configured))
        if unknown:
            raise UnknownOrgFileError(unknown)

        return [configured[file_id] for file_id in file_ids]

    def _read_file(self, file_config: OrgFileConfig) -> tuple[list[Heading], list[ClockEntry], str]:
        raw = file_config.path.read_bytes()
        text = raw.decode("utf-8")
        revision = revision_for_bytes(raw)
        heading_stack: list[ParsedHeading] = []
        headings: list[Heading] = []
        clocks: list[ClockEntry] = []

        for line_number, line in enumerate(text.splitlines(), start=1):
            heading_match = HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group("stars"))
                title = heading_match.group("title").strip()
                tags = _split_tags(heading_match.group("tags"))
                heading_stack = heading_stack[: level - 1]
                outline = [heading.title for heading in heading_stack] + [title]
                heading = ParsedHeading(
                    id=_heading_id(file_config.id, outline, line_number),
                    file_id=file_config.id,
                    title=title,
                    outline=outline,
                    tags=tags,
                    todo=heading_match.group("todo"),
                    stable=False,
                )
                heading_stack.append(heading)
                headings.append(heading.to_domain())
                continue

            clock_match = CLOCK_RE.match(line)
            if clock_match and heading_stack:
                heading = heading_stack[-1]
                clock_start = _parse_org_datetime(
                    clock_match.group("start_date"),
                    clock_match.group("start_time"),
                    self._timezone,
                )
                clock_end = _parse_org_datetime(
                    clock_match.group("end_date"),
                    clock_match.group("end_time"),
                    self._timezone,
                )
                duration_minutes = int((clock_end - clock_start).total_seconds() // 60)
                if duration_minutes <= 0:
                    continue

                clocks.append(
                    ClockEntry(
                        id=_clock_id(file_config.id, revision, line_number, line),
                        file_id=file_config.id,
                        heading_id=heading.id,
                        heading_title=heading.title,
                        outline=heading.outline,
                        start=clock_start,
                        end=clock_end,
                        duration_minutes=duration_minutes,
                        revision=revision,
                    )
                )

        return headings, clocks, revision

    @staticmethod
    def read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")


class UnknownOrgFileError(ValueError):
    def __init__(self, file_ids: list[str]) -> None:
        self.file_ids = file_ids
        super().__init__(f"Unknown Org file id(s): {', '.join(file_ids)}")


class ParsedHeading:
    def __init__(
        self,
        *,
        id: str,
        file_id: str,
        title: str,
        outline: list[str],
        tags: list[str],
        todo: str | None,
        stable: bool,
    ) -> None:
        self.id = id
        self.file_id = file_id
        self.title = title
        self.outline = outline
        self.tags = tags
        self.todo = todo
        self.stable = stable

    def to_domain(self) -> Heading:
        return Heading(
            id=self.id,
            file_id=self.file_id,
            title=self.title,
            outline=self.outline,
            tags=self.tags,
            todo=self.todo,
            stable=self.stable,
        )


def _parse_org_datetime(date: str, time: str, timezone: ZoneInfo) -> datetime:
    return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone)


def _split_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    return [tag for tag in raw_tags.split(":") if tag]


def _heading_id(file_id: str, outline: list[str], line_number: int) -> str:
    source = f"{file_id}\0{line_number}\0{'/'.join(outline)}".encode()
    return f"heading:{sha256(source).hexdigest()}"


def _clock_id(file_id: str, revision: str, line_number: int, line: str) -> str:
    source = f"{file_id}\0{revision}\0{line_number}\0{line}".encode()
    return f"clock:{sha256(source).hexdigest()}"
