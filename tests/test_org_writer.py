from org_clock_calendar.org_writer import OrgWriter, TextEdit


def test_replace_clock_line_preserves_surrounding_text() -> None:
    source = "before\nCLOCK: old\n after\n"
    edit = TextEdit(start=7, end=17, replacement="CLOCK: new")

    assert OrgWriter().replace_clock_line(source, edit) == "before\nCLOCK: new\n after\n"
