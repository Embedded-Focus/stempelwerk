from fastapi import APIRouter

from org_clock_calendar.config import AppConfig
from org_clock_calendar.domain import StatusResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    config = AppConfig()
    return StatusResponse(
        status="ok",
        emacs_available=False,
        write_mode=config.write_mode,
        timezone=config.timezone,
        files=[file.id for file in config.files],
    )

