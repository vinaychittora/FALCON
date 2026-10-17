from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    appliance,
    configuration,
    evidence,
    health,
    jobs,
    live,
    remote,
    reviews,
    sensors,
    taxa,
    test_sessions,
    videos,
)
from app.config import Settings, settings
from app.media.probe import VideoLibrary
from app.remote_access import RemoteAccessMiddleware, RemoteAccessService
from app.security import LocalRequestPolicyMiddleware
from app.services.analyzer import Analyzer
from app.services.appliance import ApplianceService
from app.services.live import LiveService
from app.services.sensors import SensorHistoryProvider
from app.services.test_sessions import TestSessionService
from app.storage.cameras import CameraStore
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jobs import JobStore
from app.storage.jsonl import EventStore
from app.taxonomy.inaturalist import TaxaService
from app.web import install_frontend


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings
    config.prepare()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.evidence.recover_pending()
        app.state.test_sessions.startup()
        app.state.appliance.startup()
        try:
            yield
        finally:
            app.state.appliance.shutdown()
            app.state.test_sessions.shutdown()
            app.state.live.stop(wait=True)

    app = FastAPI(title="FALCON", version="0.2.0", lifespan=lifespan)

    app.add_middleware(LocalRequestPolicyMiddleware, upload_limit_bytes=config.upload_limit_bytes)
    app.state.remote = RemoteAccessService(config.data_dir)
    app.add_middleware(RemoteAccessMiddleware, service=app.state.remote)
    app.state.config = config
    app.state.database = Database(config.data_dir / "falcon.sqlite3")
    app.state.sensors = SensorHistoryProvider(
        app.state.database, sensor_id=config.sensor_id,
        stale_after_seconds=config.sensor_stale_after_seconds,
    )
    app.state.cameras = CameraStore(app.state.database, config.data_dir / "private" / "camera.key")
    app.state.library = VideoLibrary(config.data_dir / "samples", app.state.database)
    app.state.taxa = TaxaService(config.data_dir)
    app.state.events = EventStore(config.data_dir / "logs", app.state.database)
    app.state.jobs = JobStore(config.data_dir / "jobs", app.state.database)
    app.state.analyzer = Analyzer(
        config, app.state.taxa, app.state.events, app.state.jobs, app.state.sensors
    )
    app.state.test_sessions = TestSessionService(config, app.state.analyzer, app.state.library)
    app.state.evidence = EvidenceStore(app.state.database, config.data_dir / "evidence")
    app.state.live = LiveService(app.state.analyzer, app.state.evidence)
    app.state.appliance = ApplianceService(config, app.state.cameras, app.state.live)
    app.include_router(evidence.router)
    app.include_router(appliance.router)
    app.include_router(remote.router)
    app.include_router(live.router)
    app.include_router(reviews.router)
    app.include_router(jobs.router)
    app.include_router(configuration.router)
    app.include_router(taxa.router)
    app.include_router(health.router)
    app.include_router(videos.router)
    app.include_router(sensors.router)
    app.include_router(test_sessions.router)
    install_frontend(app, config.frontend_dir)
    return app


app = create_app()
