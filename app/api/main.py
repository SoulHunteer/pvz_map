from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.public import public_router
from app.api.router import router
from app.api.telegram_auth import auth_router
from app.core import get_settings, setup_logging
from app.db.schema_guard import ensure_schema_ready
from app.services.avito_monitoring import AvitoMonitoringService
from app.services.avito_scraper import AvitoScraper
from app.services.monitoring import MonitoringService
from app.services.mvp import MvpService


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    ensure_schema_ready()

    monitoring_service = MonitoringService(settings)
    mvp_service = MvpService(settings, monitoring_service=monitoring_service)

    # Avito monitoring
    avito_scraper: AvitoScraper | None = None
    avito_monitoring: AvitoMonitoringService | None = None
    if settings.enable_avito:
        avito_scraper = AvitoScraper(
            request_delay_min=settings.avito_request_delay_min,
            request_delay_max=settings.avito_request_delay_max,
        )
        avito_monitoring = AvitoMonitoringService(avito_scraper)

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
    app.state.avito_monitoring = avito_monitoring
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(public_router)
    return app


app = create_app()
