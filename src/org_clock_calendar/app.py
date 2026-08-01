from fastapi import FastAPI

from org_clock_calendar.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Org Clock Calendar")
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()

