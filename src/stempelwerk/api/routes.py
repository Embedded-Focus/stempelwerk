from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from stempelwerk.config import load_config
from stempelwerk.domain import ClockEntriesResponse, Heading, StatusResponse
from stempelwerk.org_reader import OrgReader, UnknownOrgFileError

router = APIRouter()
FileIdQuery = Annotated[list[str] | None, Query()]


@router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    config = load_config()
    return StatusResponse(
        status="ok",
        emacs_available=False,
        write_mode=config.write_mode,
        timezone=config.timezone,
        files=[file.id for file in config.files],
        file_colors={file.id: file.color for file in config.files if file.color is not None},
    )


@router.get("/headings", response_model=list[Heading])
def list_headings(
    query: str = "",
    file_id: FileIdQuery = None,
) -> list[Heading]:
    config = load_config()
    file_ids = file_id or []
    reader = OrgReader(config.files, config.timezone)
    try:
        headings = reader.list_headings()
    except FileNotFoundError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if file_ids:
        configured_ids = {file.id for file in config.files}
        unknown = sorted(set(file_ids) - configured_ids)
        if unknown:
            raise HTTPException(status_code=422, detail={"code": "unknown_file_id", "files": unknown})
        headings = [heading for heading in headings if heading.file_id in file_ids]

    normalized_query = query.casefold().strip()
    if normalized_query:
        headings = [
            heading
            for heading in headings
            if normalized_query in " / ".join(heading.outline).casefold()
            or any(normalized_query in tag.casefold() for tag in heading.tags)
        ]

    return headings


@router.get("/clocks", response_model=ClockEntriesResponse)
def list_clocks(
    start: datetime,
    end: datetime,
    file_id: FileIdQuery = None,
) -> ClockEntriesResponse:
    if end <= start:
        raise HTTPException(status_code=422, detail={"code": "invalid_time_range"})

    config = load_config()
    reader = OrgReader(config.files, config.timezone)
    try:
        clocks, revisions = reader.list_clocks(start=start, end=end, file_ids=file_id)
    except UnknownOrgFileError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "unknown_file_id", "files": error.file_ids},
        ) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return ClockEntriesResponse(clocks=clocks, revisions=revisions)
