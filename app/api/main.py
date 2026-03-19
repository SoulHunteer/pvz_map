from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.core import get_settings, setup_logging
from app.db.init_db import init_schema
from app.services.monitoring import MonitoringService
from app.services.mvp import MvpService


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    init_schema(migrate_legacy=True)

    monitoring_service = MonitoringService(settings)
    mvp_service = MvpService(settings, monitoring_service=monitoring_service)

    app = FastAPI(title="PVZ Monitor API", version="0.3.0")

    if settings.api_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api_cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.mount("/artifacts", StaticFiles(directory=str(settings.artifact_root)), name="artifacts")

    app.state.settings = settings
    app.state.monitoring_service = monitoring_service
    app.state.mvp_service = mvp_service
    app.include_router(router)
    return app


app = create_app()
