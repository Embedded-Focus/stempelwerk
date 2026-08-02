from dataclasses import dataclass


@dataclass(frozen=True)
class TextEdit:
    start: int
    end: int
    replacement: str


class OrgWriter:
    """Lossless CLOCK line editor boundary."""

    def replace_clock_line(self, source: str, edit: TextEdit) -> str:
        if edit.start < 0 or edit.end < edit.start or edit.end > len(source):
            raise ValueError("invalid edit range")
        return source[: edit.start] + edit.replacement + source[edit.end :]

