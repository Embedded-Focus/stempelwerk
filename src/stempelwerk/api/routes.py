import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from stempelwerk.config import AppConfig, load_config
from stempelwerk.domain import (
    BackupInfo,
    BackupsListResponse,
    ClockEntriesResponse,
    ClockEntry,
    ClockUpdateRequest,
    Heading,
    HeadingRenameRequest,
    StatusResponse,
)
from stempelwerk.org_reader import OrgReader, UnknownOrgFileError
from stempelwerk.org_writer import (
    ClockNotFoundError,
    HeadingNotFoundError,
    InvalidHeadingTitleError,
    OrgWriter,
    RevisionConflictError,
    backup_created_at,
    list_backups,
)

logger = logging.getLogger(__name__)
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
            raise HTTPException(
                status_code=422, detail={"code": "unknown_file_id", "files": unknown}
            )
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


def _ensure_writable(config: AppConfig, action: str) -> None:
    """Raise HTTPException if the configuration does not allow writes.

    `action` describes the rejected request for the log, for example
    "update of clock clock:work:abc".
    """
    if config.write_mode == "read-only":
        logger.warning(
            'Rejected %s: write_mode is "read-only" in the loaded config, '
            'set write_mode to "auto" or "disk" to allow writes',
            action,
        )
        raise HTTPException(status_code=422, detail={"code": "read_only"})
    if config.write_mode == "emacs":
        logger.warning(
            'Rejected %s: write_mode is "emacs", but Emacs-mediated writes are not yet supported',
            action,
        )
        raise HTTPException(status_code=422, detail={"code": "emacs_not_supported"})


@router.patch("/clocks/{clock_id}", response_model=ClockEntry)
def update_clock(clock_id: str, payload: ClockUpdateRequest) -> ClockEntry:
    start = payload.start.replace(second=0, microsecond=0)
    end = payload.end.replace(second=0, microsecond=0)
    if end <= start:
        logger.warning(
            "Rejected update of clock %s: end (%s) is not after start (%s)",
            clock_id,
            payload.end,
            payload.start,
        )
        raise HTTPException(status_code=422, detail={"code": "invalid_time_range"})

    config = load_config()
    _ensure_writable(config, f"update of clock {clock_id}")

    reader = OrgReader(config.files, config.timezone)
    writer = OrgWriter()
    try:
        updated = writer.update_clock(
            reader,
            clock_id,
            start=start,
            end=end,
            expected_revision=payload.expected_revision,
        )
    except ClockNotFoundError as error:
        logger.warning(
            "Rejected update of clock %s: no clock with that id exists in the current file",
            clock_id,
        )
        raise HTTPException(status_code=404, detail={"code": "unknown_clock_id"}) from error
    except RevisionConflictError as error:
        logger.warning(
            "Rejected update of clock %s: expected revision %s but file is now at %s "
            "(the underlying Org file changed since it was loaded)",
            clock_id,
            error.expected_revision,
            error.actual_revision,
        )
        raise HTTPException(status_code=409, detail={"code": "revision_conflict"}) from error
    except FileNotFoundError as error:
        logger.warning("Rejected update of clock %s: %s", clock_id, error)
        raise HTTPException(status_code=422, detail=str(error)) from error

    logger.info("Updated clock %s, new id %s", clock_id, updated.id)
    return updated


@router.patch("/files/{file_id}/headings/{heading_id}", status_code=204)
def rename_heading(file_id: str, heading_id: str, payload: HeadingRenameRequest) -> None:
    config = load_config()
    _ensure_writable(config, f"rename of heading {heading_id} in {file_id}")

    reader = OrgReader(config.files, config.timezone)
    writer = OrgWriter()
    try:
        written = writer.rename_heading(
            reader,
            file_id,
            heading_id,
            title=payload.title,
            expected_revision=payload.expected_revision,
        )
    except UnknownOrgFileError as error:
        logger.warning(
            "Rejected rename of heading %s in %s: unknown Org file id(s) %s",
            heading_id,
            file_id,
            ", ".join(error.file_ids),
        )
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_file_id", "files": error.file_ids},
        ) from error
    except HeadingNotFoundError as error:
        logger.warning(
            "Rejected rename of heading %s in %s: no heading with that id exists in the current file",
            heading_id,
            file_id,
        )
        raise HTTPException(status_code=404, detail={"code": "unknown_heading_id"}) from error
    except RevisionConflictError as error:
        logger.warning(
            "Rejected rename of heading %s in %s: expected revision %s but file is now at %s "
            "(the underlying Org file changed since it was loaded)",
            heading_id,
            file_id,
            error.expected_revision,
            error.actual_revision,
        )
        raise HTTPException(status_code=409, detail={"code": "revision_conflict"}) from error
    except InvalidHeadingTitleError as error:
        logger.warning(
            "Rejected rename of heading %s in %s: invalid title %r (%s)",
            heading_id,
            file_id,
            error.title,
            error.reason,
        )
        raise HTTPException(
            status_code=422, detail={"code": "invalid_title", "reason": error.reason}
        ) from error
    except FileNotFoundError as error:
        logger.warning("Rejected rename of heading %s in %s: %s", heading_id, file_id, error)
        raise HTTPException(status_code=422, detail=str(error)) from error

    if written:
        logger.info("Renamed heading %s in %s", heading_id, file_id)
    else:
        logger.info("Heading %s in %s already has this title", heading_id, file_id)


def _configured_file(config, file_id: str):
    return next((file for file in config.files if file.id == file_id), None)


@router.post("/files/{file_id}/backups", status_code=201, response_model=BackupInfo)
def create_file_backup(file_id: str) -> BackupInfo:
    config = load_config()
    reader = OrgReader(config.files, config.timezone)
    writer = OrgWriter()
    try:
        backup_path = writer.create_backup(reader, file_id)
    except UnknownOrgFileError as error:
        logger.warning(
            "Rejected backup creation: unknown Org file id(s) %s", ", ".join(error.file_ids)
        )
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_file_id", "files": error.file_ids},
        ) from error
    except FileNotFoundError as error:
        logger.warning("Rejected backup creation: %s", error)
        raise HTTPException(status_code=422, detail=str(error)) from error

    logger.info("Created backup %s", backup_path)
    created_at = backup_created_at(backup_path.name)
    assert created_at is not None
    return BackupInfo(file_id=file_id, filename=backup_path.name, created_at=created_at)


@router.get("/files/{file_id}/backups", response_model=BackupsListResponse)
def list_file_backups(file_id: str) -> BackupsListResponse:
    config = load_config()
    file_config = _configured_file(config, file_id)
    if file_config is None:
        logger.warning("Rejected backup listing: unknown Org file id %s", file_id)
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_file_id", "files": [file_id]},
        )

    backups = []
    for entry in list_backups(file_config.path):
        created_at = backup_created_at(entry.name)
        assert created_at is not None
        backups.append(BackupInfo(file_id=file_id, filename=entry.name, created_at=created_at))
    return BackupsListResponse(backups=backups)
