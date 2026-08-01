import pytest

from org_clock_calendar.org_reader import OrgReader


def test_org_reader_heading_listing_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        OrgReader([]).list_headings()

