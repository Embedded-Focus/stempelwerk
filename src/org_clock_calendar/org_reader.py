from pathlib import Path

from org_clock_calendar.config import OrgFileConfig
from org_clock_calendar.domain import ClockEntry, Heading


class OrgReader:
    """Semantic Org reader facade.

    The implementation will use orgparse for traversal while preserving a
    separate source-location model for lossless edits.
    """

    def __init__(self, files: list[OrgFileConfig]) -> None:
        self._files = files

    def list_headings(self) -> list[Heading]:
        raise NotImplementedError

    def list_clocks(self, start: str, end: str) -> list[ClockEntry]:
        raise NotImplementedError

    @staticmethod
    def read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

