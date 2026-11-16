from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from stempelwerk.config import WriteMode


class Heading(BaseModel):
    id: str
    file_id: str
    title: str
    outline: list[str]
    tags: list[str] = Field(default_factory=list)
    todo: str | None = None
    stable: bool


class ClockEntry(BaseModel):
    id: str
    file_id: str
    heading_id: str
    heading_title: str
    outline: list[str]
    start: datetime
    end: datetime
    duration_minutes: int
    revision: str
    editable: bool = True


class CalDAVEvent(BaseModel):
    id: str
    calendar_id: str
    calendar_name: str
    title: str
    start: date | datetime
    end: date | datetime
    all_day: bool
    location: str | None = None
    # Literal so callers can never construct a writable CalDAV event.
    editable: Literal[False] = False


class CalendarSource(BaseModel):
    id: str
    name: str
    kind: Literal["org", "caldav"]
    color: str | None = None
    editable: bool


class CalDAVCalendarError(BaseModel):
    calendar_id: str
    code: Literal["unavailable"] = "unavailable"
    message: Literal["Calendar is unavailable"] = "Calendar is unavailable"


class CalDAVEventsResponse(BaseModel):
    events: list[CalDAVEvent] = Field(default_factory=list)
    errors: list[CalDAVCalendarError] = Field(default_factory=list)


class ClockEntriesResponse(BaseModel):
    clocks: list[ClockEntry]
    revisions: dict[str, str]


class ClockUpdateRequest(BaseModel):
    start: datetime
    end: datetime
    expected_revision: str
    heading_id: str | None = None


class ClockSplitRequest(BaseModel):
    split_at: datetime
    expected_revision: str


class ClockSplitResponse(BaseModel):
    clocks: list[ClockEntry]


class HeadingRenameRequest(BaseModel):
    title: str
    expected_revision: str


class StatusResponse(BaseModel):
    status: Literal["ok"]
    emacs_available: bool
    write_mode: WriteMode
    timezone: str
    files: list[str]
    file_colors: dict[str, str] = Field(default_factory=dict)
    sources: list[CalendarSource] = Field(default_factory=list)


class BackupInfo(BaseModel):
    file_id: str
    filename: str
    created_at: datetime


class BackupsListResponse(BaseModel):
    backups: list[BackupInfo]


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody
