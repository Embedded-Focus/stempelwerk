import logging

from fastapi import FastAPI

from stempelwerk.api.routes import router


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title="Stempelwerk")
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
